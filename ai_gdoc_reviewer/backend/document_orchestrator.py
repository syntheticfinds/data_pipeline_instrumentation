"""
Document Orchestrator for Design Document Graph Management.

This module provides parsing of design documents into structured components and data flows
for privacy review context.
"""

import os
import json
import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from openai import OpenAI

logger = logging.getLogger("document_orchestrator")


@dataclass
class ParsedSection:
    """A parsed section from a design document."""
    title: str
    heading_level: int
    content: str
    order: int
    components_mentioned: List[str] = field(default_factory=list)


@dataclass
class ParsedComponent:
    """A technical component extracted from the document."""
    name: str
    component_type: str
    description: str  # Should include tech stack (e.g., "PostgreSQL database for patient records")
    data_types: List[Dict[str, Any]] = field(default_factory=list)
    privacy_measures: List[str] = field(default_factory=list)  # Simple list of privacy control strings
    source_section_id: Optional[str] = None  # Reference to the section where this component appears


@dataclass
class ParsedDataFlow:
    """A data flow between components."""
    source: str
    target: str
    data_types: List[str] = field(default_factory=list)
    protocol: Optional[str] = None
    encryption_in_transit: bool = False
    authentication: Optional[str] = None
    source_section_id: Optional[str] = None  # Reference to the section where this flow is described


class DocumentParser:
    """Parses design documents into structured components."""

    def __init__(self):
        self.openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def parse_sections(self, doc_text: str) -> List[ParsedSection]:
        """Parse document text into sections based on headings."""
        sections = []
        current_section = None
        current_content = []
        order = 0

        lines = doc_text.split("\n")

        for line in lines:
            # Detect headings (markdown style or document-style)
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if not heading_match:
                # Try Google Docs style (ALL CAPS or title case with no punctuation)
                if line.strip() and line.strip().isupper() and len(line.strip()) > 3:
                    heading_match = (1, line.strip())
                elif line.strip() and line.strip().istitle() and len(line.strip().split()) <= 8:
                    heading_match = (2, line.strip())

            if heading_match:
                # Save previous section
                if current_section is not None:
                    current_section.content = "\n".join(current_content).strip()
                    sections.append(current_section)

                # Start new section
                if isinstance(heading_match, tuple):
                    level, title = heading_match
                else:
                    level = len(heading_match.group(1))
                    title = heading_match.group(2)

                current_section = ParsedSection(
                    title=title,
                    heading_level=level,
                    content="",
                    order=order,
                )
                current_content = []
                order += 1
            else:
                current_content.append(line)

        # Don't forget the last section
        if current_section is not None:
            current_section.content = "\n".join(current_content).strip()
            sections.append(current_section)

        # If no sections were parsed, create a default section with the entire content
        if not sections and doc_text.strip():
            sections.append(ParsedSection(
                title="Document Content",
                heading_level=1,
                content=doc_text.strip(),
                order=0,
            ))
            logger.info("No headings found - created default 'Document Content' section")

        return sections

    def extract_components_with_llm(self, doc_text: str) -> List[ParsedComponent]:
        """Use LLM to extract technical components from the document."""
        prompt = f"""Analyze this technical design document and extract all technical components mentioned.

For each component, identify:
1. name: The component name (e.g., "User API", "Patient Database", "Auth Service")
2. component_type: One of: api, database, service, datastore, external, ui, auth, queue, storage, llm, other
3. description: Brief description that MUST include the specific technology/tech stack
   (e.g., "PostgreSQL database for storing patient records", "Node.js Express REST API", "GPT-4 based summarization service")
4. data_types: List of data types it handles, each with:
   - dataType: name of the data
   - isPHI: true if it contains Protected Health Information
   - isPII: true if it contains Personally Identifiable Information
   - sensitivity: low, medium, high, or critical
5. privacy_measures: List of privacy controls in place (simple strings)
   (e.g., ["encryption at rest", "audit logging", "role-based access control"])

Return a JSON array of components. Example:
[
  {{
    "name": "Patient API",
    "component_type": "api",
    "description": "Node.js Express REST API for patient data access with OAuth 2.0 authentication",
    "data_types": [{{"dataType": "Patient records", "isPHI": true, "isPII": true, "sensitivity": "critical"}}],
    "privacy_measures": ["OAuth 2.0 authentication", "TLS encryption", "audit logging"]
  }}
]

Document text:
{doc_text[:8000]}

Return ONLY the JSON array, no explanation."""

        try:
            response = self.openai.chat.completions.create(
                model=self.model,
                temperature=0.0,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )

            result = (response.choices[0].message.content or "[]").strip()
            if result.startswith("```"):
                result = result.strip("`").strip()
                if result.startswith("json"):
                    result = result[4:].strip()

            components_data = json.loads(result)
            return [
                ParsedComponent(
                    name=c.get("name", "Unknown"),
                    component_type=c.get("component_type", "other"),
                    description=c.get("description", ""),
                    data_types=c.get("data_types", []),
                    privacy_measures=c.get("privacy_measures", []),
                )
                for c in components_data
            ]
        except Exception as e:
            logger.error(f"Failed to extract components with LLM: {e}")
            return []

    def extract_data_flows_with_llm(
        self, doc_text: str, components: List[ParsedComponent]
    ) -> List[ParsedDataFlow]:
        """Use LLM to extract data flows between components."""
        component_names = [c.name for c in components]

        prompt = f"""Analyze this technical design document and identify data flows between components.

Known components: {json.dumps(component_names)}

For each data flow, identify:
1. source: Source component name (must be from the list above)
2. target: Target component name (must be from the list above)
3. data_types: List of data types being transferred
4. protocol: Transfer protocol (https, grpc, graphql, websocket, queue, database, file, internal, other)
5. encryption_in_transit: true/false - is the data encrypted during transfer?
6. authentication: Authentication method (api_key, oauth2, jwt, mtls, basic, none, other)

Return a JSON array of flows. Example:
[
  {{
    "source": "Patient API",
    "target": "Patient Database",
    "data_types": ["patient records", "medical history"],
    "protocol": "database",
    "encryption_in_transit": true,
    "authentication": "mtls"
  }}
]

Document text:
{doc_text[:8000]}

Return ONLY the JSON array, no explanation."""

        try:
            response = self.openai.chat.completions.create(
                model=self.model,
                temperature=0.0,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )

            result = (response.choices[0].message.content or "[]").strip()
            if result.startswith("```"):
                result = result.strip("`").strip()
                if result.startswith("json"):
                    result = result[4:].strip()

            flows_data = json.loads(result)
            return [
                ParsedDataFlow(
                    source=f.get("source", ""),
                    target=f.get("target", ""),
                    data_types=f.get("data_types", []),
                    protocol=f.get("protocol"),
                    encryption_in_transit=f.get("encryption_in_transit", False),
                    authentication=f.get("authentication"),
                )
                for f in flows_data
                if f.get("source") in component_names and f.get("target") in component_names
            ]
        except Exception as e:
            logger.error(f"Failed to extract data flows with LLM: {e}")
            return []


class DocumentGraphOrchestrator:
    """
    Orchestrates parsing of design documents into structured components and data flows.
    """

    def __init__(self):
        self.parser = DocumentParser()

    def parse_document_structure(self, doc_text: str) -> Dict[str, Any]:
        """
        Parse document into components and data flows WITHOUT persisting to Sanity.

        Use this for the review phase when you only need the structure for LLM context.

        Args:
            doc_text: Full document text

        Returns:
            {
                "components": [...],  # ParsedComponent as dicts
                "data_flows": [...],  # ParsedDataFlow as dicts
            }
        """
        logger.info("Parsing document structure")

        # Parse document
        components = self.parser.extract_components_with_llm(doc_text)
        data_flows = self.parser.extract_data_flows_with_llm(doc_text, components)

        logger.info(f"Parsed {len(components)} components, {len(data_flows)} data flows")

        # Convert to dicts matching the format expected by review_llm._format_sanity_structure
        component_dicts = [
            {
                "name": comp.name,
                "componentType": comp.component_type,
                "description": comp.description,
                "dataHandled": comp.data_types,
            }
            for comp in components
        ]

        flow_dicts = [
            {
                "name": f"{flow.source} -> {flow.target}",
                "source": flow.source,
                "target": flow.target,
                "dataTypes": [{"dataType": dt} for dt in flow.data_types],
                "encryption": {"inTransit": flow.encryption_in_transit},
            }
            for flow in data_flows
        ]

        return {
            "components": component_dicts,
            "data_flows": flow_dicts,
        }
