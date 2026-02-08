"""
Document Orchestrator for Design Document Graph Management.

This module provides:
1. Parsing design documents into graph structure (sections, components, data flows)
2. Creating/updating graph nodes in Sanity
3. Orchestrating agent actions (generate, transform) based on review comments
4. Generating modification suggestions for write-back to Google Docs

Architecture:
    Google Doc -> Parse -> Sanity Graph -> Privacy Review -> Agent Actions -> Modifications -> Google Doc
"""

import os
import json
import logging
import re
import uuid
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field

import requests
from openai import OpenAI

from web_research import research_for_comments

logger = logging.getLogger("document_orchestrator")

# Sanity project configuration
SANITY_PROJECT_ID = os.getenv("SANITY_PROJECT_ID", "ukousf31")
SANITY_DATASET = os.getenv("SANITY_DATASET", "production")
SANITY_API_VERSION = "2024-01-01"
SANITY_TOKEN = os.getenv("SANITY_API_TOKEN", "")
SANITY_SCHEMA_ID = os.getenv("SANITY_SCHEMA_ID", "_.schemas.default")


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


@dataclass
class ModificationAction:
    """An action the orchestrator decides to take."""
    action_type: str  # 'generate', 'transform', 'image', 'replace'
    target_node_type: str  # 'section', 'component', 'dataFlow'
    target_node_id: str
    instruction: str
    related_issue_id: Optional[str] = None
    find_text: Optional[str] = None
    replace_text: Optional[str] = None


class SanityAgentActionsClient:
    """
    Client for Sanity Agent Actions API (generate, transform, image).

    Uses the experimental 'vX' API version for Agent Actions.
    https://www.sanity.io/docs/agent-actions
    """

    def __init__(self):
        self.project_id = SANITY_PROJECT_ID
        self.dataset = SANITY_DATASET
        self.token = SANITY_TOKEN
        self.schema_id = SANITY_SCHEMA_ID

    def _base_url(self) -> str:
        return f"https://{self.project_id}.api.sanity.io/vX/agent/action"

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def generate(
        self,
        document_id: str,
        instruction: str,
        instruction_params: Optional[Dict[str, Any]] = None,
        target_path: Optional[str] = None,
        async_mode: bool = False,
    ) -> Dict[str, Any]:
        """
        Call Sanity's Generate Agent Action to create or modify content.

        Args:
            document_id: The document to modify
            instruction: Natural language instruction for the AI
            instruction_params: Parameters to pass to the instruction ($key syntax)
            target_path: Specific field path to target (e.g., "description")
            async_mode: If True, returns immediately without waiting for completion
        """
        url = f"{self._base_url()}/generate/{self.dataset}"

        payload = {
            "schemaId": self.schema_id,
            "documentId": document_id,
            "instruction": instruction,
        }

        if instruction_params:
            payload["instructionParams"] = instruction_params

        if target_path:
            payload["target"] = {"path": target_path}

        if async_mode:
            payload["async"] = True

        logger.info(f"Calling Sanity Generate on {document_id}: {instruction[:100]}...")

        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=60,  # Agent Actions can take longer
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Generate completed for {document_id}")
            return result
        except Exception as e:
            logger.error(f"Generate failed for {document_id}: {e}")
            return {"error": str(e)}

    def transform(
        self,
        document_id: str,
        instruction: str,
        instruction_params: Optional[Dict[str, Any]] = None,
        target_paths: Optional[List[str]] = None,
        async_mode: bool = False,
    ) -> Dict[str, Any]:
        """
        Call Sanity's Transform Agent Action to modify existing content.

        Args:
            document_id: The document to transform
            instruction: Natural language instruction for the transformation
            instruction_params: Parameters to pass to the instruction
            target_paths: Specific field paths to target
            async_mode: If True, returns immediately without waiting
        """
        url = f"{self._base_url()}/transform/{self.dataset}"

        payload = {
            "schemaId": self.schema_id,
            "documentId": document_id,
            "instruction": instruction,
        }

        if instruction_params:
            payload["instructionParams"] = instruction_params

        if target_paths:
            payload["target"] = [{"path": [p]} for p in target_paths]

        if async_mode:
            payload["async"] = True

        logger.info(f"Calling Sanity Transform on {document_id}: {instruction[:100]}...")

        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=60,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Transform completed for {document_id}")
            return result
        except Exception as e:
            logger.error(f"Transform failed for {document_id}: {e}")
            return {"error": str(e)}

    def generate_image(
        self,
        document_id: str,
        image_path: str,
        instruction: str,
        async_mode: bool = True,  # Images default to async
    ) -> Dict[str, Any]:
        """
        Call Sanity's Generate Agent Action to create an image.

        Args:
            document_id: The document containing the image field
            image_path: Path to the image field (e.g., "mainImage")
            instruction: Description of the image to generate
            async_mode: If True (default), returns immediately
        """
        url = f"{self._base_url()}/generate/{self.dataset}"

        payload = {
            "schemaId": self.schema_id,
            "documentId": document_id,
            "instruction": instruction,
            "target": {"path": image_path},
            "async": async_mode,
        }

        logger.info(f"Calling Sanity Image Generation on {document_id}.{image_path}")

        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Image generation initiated for {document_id}.{image_path}")
            return result
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return {"error": str(e)}


class SanityMutationClient:
    """Client for Sanity mutations (create, update, delete)."""

    def __init__(self):
        self.project_id = SANITY_PROJECT_ID
        self.dataset = SANITY_DATASET
        self.token = SANITY_TOKEN
        self.api_version = SANITY_API_VERSION

    def _get_mutation_url(self) -> str:
        return f"https://{self.project_id}.api.sanity.io/v{self.api_version}/data/mutate/{self.dataset}"

    def _get_query_url(self) -> str:
        return f"https://{self.project_id}.api.sanity.io/v{self.api_version}/data/query/{self.dataset}"

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def query(self, groq_query: str) -> List[Dict[str, Any]]:
        """Execute a GROQ query."""
        try:
            response = requests.get(
                self._get_query_url(),
                params={"query": groq_query},
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("result", [])
        except Exception as e:
            logger.error(f"Sanity query failed: {e}")
            return []

    def create(self, document: Dict[str, Any]) -> Optional[str]:
        """Create a new document. Returns the document ID."""
        if "_id" not in document:
            document["_id"] = str(uuid.uuid4())

        mutations = {"mutations": [{"create": document}]}

        try:
            response = requests.post(
                self._get_mutation_url(),
                json=mutations,
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Created document {document['_id']} of type {document.get('_type')}")
            return document["_id"]
        except requests.exceptions.HTTPError as e:
            # Log the actual response body for debugging
            error_body = ""
            try:
                error_body = e.response.text
            except:
                pass
            logger.error(f"Failed to create document: {e}")
            logger.error(f"Response body: {error_body}")
            return None
        except Exception as e:
            logger.error(f"Failed to create document: {e}")
            return None

    def update(self, doc_id: str, patch: Dict[str, Any]) -> bool:
        """Update an existing document."""
        mutations = {"mutations": [{"patch": {"id": doc_id, "set": patch}}]}

        try:
            response = requests.post(
                self._get_mutation_url(),
                json=mutations,
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            logger.info(f"Updated document {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update document {doc_id}: {e}")
            return False

    def create_or_update(self, document: Dict[str, Any]) -> Optional[str]:
        """Create or update a document (upsert)."""
        mutations = {"mutations": [{"createOrReplace": document}]}

        try:
            response = requests.post(
                self._get_mutation_url(),
                json=mutations,
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            logger.info(f"Upserted document {document['_id']} of type {document.get('_type')}")
            return document["_id"]
        except Exception as e:
            logger.error(f"Failed to upsert document: {e}")
            return None

    def delete(self, doc_id: str) -> bool:
        """Delete a document by ID."""
        mutations = {"mutations": [{"delete": {"id": doc_id}}]}

        try:
            response = requests.post(
                self._get_mutation_url(),
                json=mutations,
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            logger.info(f"Deleted document {doc_id}")
            return True
        except requests.exceptions.HTTPError as e:
            error_body = ""
            try:
                error_body = e.response.text
            except:
                pass
            logger.error(f"Failed to delete document {doc_id}: {e}")
            logger.error(f"Response body: {error_body}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete document {doc_id}: {e}")
            return False

    def delete_batch(self, doc_ids: List[str]) -> Tuple[int, int]:
        """
        Delete multiple documents in a single batch mutation.
        Returns (success_count, failure_count).
        """
        if not doc_ids:
            return (0, 0)

        mutations = {"mutations": [{"delete": {"id": doc_id}} for doc_id in doc_ids]}

        try:
            response = requests.post(
                self._get_mutation_url(),
                json=mutations,
                headers=self._headers(),
                timeout=30,  # Longer timeout for batch operations
            )
            response.raise_for_status()
            logger.info(f"Batch deleted {len(doc_ids)} documents")
            return (len(doc_ids), 0)
        except requests.exceptions.HTTPError as e:
            error_body = ""
            try:
                error_body = e.response.text
            except:
                pass
            logger.error(f"Batch delete failed: {e}")
            logger.error(f"Response body: {error_body}")
            # Fall back to individual deletes
            success = 0
            for doc_id in doc_ids:
                if self.delete(doc_id):
                    success += 1
            return (success, len(doc_ids) - success)
        except Exception as e:
            logger.error(f"Batch delete failed: {e}")
            return (0, len(doc_ids))


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
    Orchestrates the document graph workflow:
    1. Parse documents into graph structure
    2. Store in Sanity
    3. Process review comments to generate modifications
    4. Create modification suggestions for write-back
    """

    def __init__(self):
        self.sanity = SanityMutationClient()
        self.agent_actions = SanityAgentActionsClient()
        self.parser = DocumentParser()
        self.openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def get_or_create_design_document(
        self,
        google_doc_id: str,
        doc_text: str,
        doc_title: str = "",
        include_sections: bool = False,
        parsed_components: Optional[List[Dict[str, Any]]] = None,
        parsed_data_flows: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new designDocument for the document.

        Always creates fresh documents for each run to avoid stale data issues.
        Old documents are cleaned up after successful apply or can be manually cleaned.

        Args:
            google_doc_id: The Google Doc ID (stored for reference)
            doc_text: Full document text (used for parsing)
            doc_title: Document title
            include_sections: If True, also create section documents (for orchestration).
                             If False, only create components + data flows (for review context).
            parsed_components: Pre-parsed components from review phase (skips LLM parsing)
            parsed_data_flows: Pre-parsed data flows from review phase (skips LLM parsing)

        Returns:
            {
                "design_doc_id": str,
                "is_new": bool,  # Always True now
                "components": [...],  # Sanity component docs
                "data_flows": [...],  # Sanity data flow docs
                "sections": [...],    # Sanity section docs (if include_sections=True)
            }
        """
        # Always create fresh documents - don't reuse from previous runs
        # This avoids stale data issues and makes each run independent
        logger.info(f"Creating new designDocument for googleDocId={google_doc_id}")

        # Use pre-parsed structure if provided, otherwise parse with LLM
        if parsed_components and parsed_data_flows:
            logger.info("Using pre-parsed structure from review phase (skipping LLM parsing)")
            # Convert dicts back to ParsedComponent/ParsedDataFlow for processing
            components = [
                ParsedComponent(
                    name=c.get("name", ""),
                    component_type=c.get("componentType", ""),
                    description=c.get("description", ""),
                    data_types=c.get("dataHandled", []),
                    privacy_measures=[],
                )
                for c in parsed_components
            ]
            data_flows = [
                ParsedDataFlow(
                    source=f.get("source", f.get("name", "").split(" -> ")[0] if " -> " in f.get("name", "") else ""),
                    target=f.get("target", f.get("name", "").split(" -> ")[1] if " -> " in f.get("name", "") else ""),
                    data_types=[dt.get("dataType", dt) if isinstance(dt, dict) else str(dt) for dt in f.get("dataTypes", [])],
                    encryption_in_transit=f.get("encryption", {}).get("inTransit", False) if isinstance(f.get("encryption"), dict) else False,
                )
                for f in parsed_data_flows
            ]
        else:
            logger.info("Parsing document structure with LLM...")
            components = self.parser.extract_components_with_llm(doc_text)
            data_flows = self.parser.extract_data_flows_with_llm(doc_text, components)

        logger.info(f"Using {len(components)} components, {len(data_flows)} data flows")

        # Create component documents
        component_id_map: Dict[str, str] = {}
        component_docs: List[Dict[str, Any]] = []
        for comp in components:
            comp_doc = {
                "_id": f"component-{uuid.uuid4()}",
                "_type": "technicalComponent",
                "name": comp.name,
                "componentType": comp.component_type,
                "description": comp.description,  # Tech stack should be included in description
                "dataHandled": comp.data_types,
                "privacyMeasures": comp.privacy_measures,
            }
            comp_id = self.sanity.create(comp_doc)
            if comp_id:
                component_id_map[comp.name] = comp_id
                comp_doc["_id"] = comp_id
                component_docs.append(comp_doc)

        # Create data flow documents
        flow_ids: List[str] = []
        flow_docs: List[Dict[str, Any]] = []
        for flow in data_flows:
            source_id = component_id_map.get(flow.source)
            target_id = component_id_map.get(flow.target)

            if source_id and target_id:
                flow_doc = {
                    "_id": f"dataflow-{uuid.uuid4()}",
                    "_type": "dataFlow",
                    "name": f"{flow.source} -> {flow.target}",
                    "sourceComponent": {"_type": "reference", "_ref": source_id},
                    "targetComponent": {"_type": "reference", "_ref": target_id},
                    "dataTypes": [{"dataType": dt} for dt in flow.data_types],
                    "protocol": flow.protocol,
                    "encryption": {"inTransit": flow.encryption_in_transit},
                    "authentication": flow.authentication,
                }
                flow_id = self.sanity.create(flow_doc)
                if flow_id:
                    flow_ids.append(flow_id)
                    flow_doc["_id"] = flow_id
                    flow_docs.append(flow_doc)

        # Optionally create section documents
        section_ids: List[str] = []
        section_docs: List[Dict[str, Any]] = []
        if include_sections:
            sections = self.parser.parse_sections(doc_text)
            logger.info(f"Parsed {len(sections)} sections")
            for section in sections:
                section_doc = {
                    "_id": f"section-{uuid.uuid4()}",
                    "_type": "documentSection",
                    "title": section.title,
                    "headingLevel": section.heading_level,
                    "originalText": section.content,
                    "sectionOrder": section.order,
                }
                section_id = self.sanity.create(section_doc)
                if section_id:
                    section_ids.append(section_id)
                    section_doc["_id"] = section_id
                    section_docs.append(section_doc)

        # Create the root design document
        doc_id = f"designdoc-{uuid.uuid4()}"
        design_doc = {
            "_id": doc_id,
            "_type": "designDocument",
            "title": doc_title or "Untitled Document",
            "components": [
                {"_type": "reference", "_ref": cid, "_key": str(i)}
                for i, cid in enumerate(component_id_map.values())
            ],
            "dataFlows": [{"_type": "reference", "_ref": fid, "_key": str(i)} for i, fid in enumerate(flow_ids)],
            "status": "draft",
        }

        if section_ids:
            design_doc["sections"] = [
                {"_type": "reference", "_ref": sid, "_key": str(i)} for i, sid in enumerate(section_ids)
            ]

        if google_doc_id:
            design_doc["googleDocId"] = google_doc_id

        created_id = self.sanity.create(design_doc)

        # Update all child documents with parent reference
        if created_id:
            for comp_id in component_id_map.values():
                self.sanity.update(comp_id, {"parentDocument": {"_type": "reference", "_ref": created_id}})
            for flow_id in flow_ids:
                self.sanity.update(flow_id, {"parentDocument": {"_type": "reference", "_ref": created_id}})
            for section_id in section_ids:
                self.sanity.update(section_id, {"parentDocument": {"_type": "reference", "_ref": created_id}})

        logger.info(f"Created new designDocument: {created_id}")

        return {
            "design_doc_id": created_id,
            "is_new": True,
            "components": component_docs,
            "data_flows": flow_docs,
            "sections": section_docs,
        }

    def parse_document_structure(self, doc_text: str) -> Dict[str, Any]:
        """
        Parse document into components and data flows WITHOUT persisting to Sanity.

        Use this for the review phase when you only need the structure for LLM context,
        not for orchestration. This avoids creating orphaned documents.

        Args:
            doc_text: Full document text

        Returns:
            {
                "components": [...],  # ParsedComponent as dicts (not persisted)
                "data_flows": [...],  # ParsedDataFlow as dicts (not persisted)
            }
        """
        logger.info("Parsing document structure (no Sanity persistence)")

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

    def add_sections_to_document(self, design_doc_id: str, doc_text: str) -> List[str]:
        """
        Add section documents to an existing designDocument.
        Used when sections weren't created during initial review phase.

        Returns list of created section IDs.
        """
        # Check if sections already exist
        existing_sections_query = f'''
        *[_type == "documentSection" && parentDocument._ref == "{design_doc_id}"] {{ _id }}
        '''
        existing_sections = self.sanity.query(existing_sections_query)

        if existing_sections and len(existing_sections) > 0:
            logger.info(f"Sections already exist for {design_doc_id}: {len(existing_sections)} sections")
            return [s["_id"] for s in existing_sections]

        # Parse and create sections
        sections = self.parser.parse_sections(doc_text)
        logger.info(f"Creating {len(sections)} sections for existing document")

        section_ids: List[str] = []
        for section in sections:
            section_doc = {
                "_id": f"section-{uuid.uuid4()}",
                "_type": "documentSection",
                "title": section.title,
                "headingLevel": section.heading_level,
                "originalText": section.content,
                "sectionOrder": section.order,
                "parentDocument": {"_type": "reference", "_ref": design_doc_id},
            }
            section_id = self.sanity.create(section_doc)
            if section_id:
                section_ids.append(section_id)

        # Update the design document with section references
        if section_ids:
            self.sanity.update(
                design_doc_id,
                {
                    "sections": [
                        {"_type": "reference", "_ref": sid, "_key": str(i)}
                        for i, sid in enumerate(section_ids)
                    ]
                },
            )

        return section_ids

    def create_document_graph(
        self,
        doc_text: str,
        doc_title: str,
        google_doc_id: Optional[str] = None,
        google_doc_url: Optional[str] = None,
    ) -> Optional[str]:
        """
        Parse a document and create its graph representation in Sanity.
        Returns the designDocument ID.
        """
        logger.info(f"Creating document graph for: {doc_title}")

        # Parse the document
        sections = self.parser.parse_sections(doc_text)
        components = self.parser.extract_components_with_llm(doc_text)
        data_flows = self.parser.extract_data_flows_with_llm(doc_text, components)

        logger.info(
            f"Parsed: {len(sections)} sections, {len(components)} components, {len(data_flows)} data flows"
        )

        # Create component documents first (we need their IDs for references)
        component_id_map: Dict[str, str] = {}
        for comp in components:
            comp_doc = {
                "_id": f"component-{uuid.uuid4()}",
                "_type": "technicalComponent",
                "name": comp.name,
                "componentType": comp.component_type,
                "description": comp.description,  # Tech stack included in description
                "dataHandled": comp.data_types,
                "privacyMeasures": comp.privacy_measures,
            }
            # Add reference to source section if available
            if comp.source_section_id:
                comp_doc["sourceSection"] = {"_type": "reference", "_ref": comp.source_section_id}

            comp_id = self.sanity.create(comp_doc)
            if comp_id:
                component_id_map[comp.name] = comp_id

        # Create data flow documents
        flow_ids: List[str] = []
        for flow in data_flows:
            source_id = component_id_map.get(flow.source)
            target_id = component_id_map.get(flow.target)

            if source_id and target_id:
                flow_doc = {
                    "_id": f"dataflow-{uuid.uuid4()}",
                    "_type": "dataFlow",
                    "name": f"{flow.source} -> {flow.target}",
                    "sourceComponent": {"_type": "reference", "_ref": source_id},
                    "targetComponent": {"_type": "reference", "_ref": target_id},
                    "dataTypes": [{"dataType": dt} for dt in flow.data_types],
                    "protocol": flow.protocol,
                    "encryption": {
                        "inTransit": flow.encryption_in_transit,
                    },
                    "authentication": flow.authentication,
                }
                # Add reference to source section if available
                if flow.source_section_id:
                    flow_doc["sourceSection"] = {"_type": "reference", "_ref": flow.source_section_id}

                flow_id = self.sanity.create(flow_doc)
                if flow_id:
                    flow_ids.append(flow_id)

        # Create section documents
        section_ids: List[str] = []
        for section in sections:
            section_doc = {
                "_id": f"section-{uuid.uuid4()}",
                "_type": "documentSection",
                "title": section.title,
                "headingLevel": section.heading_level,
                "originalText": section.content,
                "sectionOrder": section.order,
            }
            section_id = self.sanity.create(section_doc)
            if section_id:
                section_ids.append(section_id)

        # Create the root design document
        doc_id = f"designdoc-{uuid.uuid4()}"
        design_doc = {
            "_id": doc_id,
            "_type": "designDocument",
            "title": doc_title or "Untitled Document",
            "sections": [{"_type": "reference", "_ref": sid, "_key": str(i)} for i, sid in enumerate(section_ids)],
            "components": [
                {"_type": "reference", "_ref": cid, "_key": str(i)}
                for i, cid in enumerate(component_id_map.values())
            ],
            "dataFlows": [{"_type": "reference", "_ref": fid, "_key": str(i)} for i, fid in enumerate(flow_ids)],
            "status": "draft",
        }

        # Only add optional URL fields if they have valid values
        if google_doc_id:
            design_doc["googleDocId"] = google_doc_id
        if google_doc_url and google_doc_url.startswith(("http://", "https://")):
            design_doc["googleDocUrl"] = google_doc_url

        created_id = self.sanity.create(design_doc)

        # Update all child documents with parent reference
        if created_id:
            for section_id in section_ids:
                self.sanity.update(
                    section_id, {"parentDocument": {"_type": "reference", "_ref": created_id}}
                )
            for comp_id in component_id_map.values():
                self.sanity.update(
                    comp_id, {"parentDocument": {"_type": "reference", "_ref": created_id}}
                )
            for flow_id in flow_ids:
                self.sanity.update(
                    flow_id, {"parentDocument": {"_type": "reference", "_ref": created_id}}
                )

        logger.info(f"Created document graph with ID: {created_id}")
        return created_id

    def create_compliance_issues_from_review(
        self,
        design_doc_id: str,
        review_comments: List[Dict[str, Any]],
    ) -> List[str]:
        """
        Convert privacy review comments into compliance issue documents.
        Returns list of created issue IDs.
        """
        issue_ids: List[str] = []

        for comment in review_comments:
            issue_doc = {
                "_id": f"issue-{uuid.uuid4()}",
                "_type": "complianceIssue",
                "title": comment.get("comment", "")[:100],
                "originalComment": comment.get("comment", ""),
                "severity": comment.get("severity", "medium"),
                "targetQuote": comment.get("target_quote", ""),
                "parentDocument": {"_type": "reference", "_ref": design_doc_id},
            }

            issue_id = self.sanity.create(issue_doc)
            if issue_id:
                issue_ids.append(issue_id)

        # Update the design document with compliance issues
        if issue_ids:
            self.sanity.update(
                design_doc_id,
                {
                    "complianceIssues": [
                        {"_type": "reference", "_ref": iid, "_key": str(i)}
                        for i, iid in enumerate(issue_ids)
                    ],
                },
            )

        return issue_ids

    def decide_agent_actions(
        self,
        design_doc_id: str,
        issue_ids: List[str],
    ) -> List[ModificationAction]:
        """
        Use LLM to decide which agent actions to perform for each issue.
        Enriches context with web research for technical specificity.
        Returns a list of modification actions with proper target_node_id set.
        """
        # Fetch the issues
        issues_query = f"""
        *[_type == "complianceIssue" && _id in {json.dumps(issue_ids)}] {{
            _id,
            title,
            originalComment,
            severity,
            targetQuote
        }}
        """
        issues = self.sanity.query(issues_query)

        if not issues:
            return []

        # Fetch the document graph for target matching
        sections_query = f"""
        *[_type == "documentSection" && parentDocument._ref == "{design_doc_id}"] {{
            _id,
            title,
            headingLevel,
            originalText,
            sectionOrder
        }} | order(sectionOrder asc)
        """
        sections = self.sanity.query(sections_query)

        components_query = f"""
        *[_type == "technicalComponent" && parentDocument._ref == "{design_doc_id}"] {{
            _id,
            name,
            componentType,
            description,
            sourceSection
        }}
        """
        components = self.sanity.query(components_query)

        data_flows_query = f"""
        *[_type == "dataFlow" && parentDocument._ref == "{design_doc_id}"] {{
            _id,
            name,
            sourceComponent,
            targetComponent,
            sourceSection
        }}
        """
        data_flows = self.sanity.query(data_flows_query)

        logger.info(f"Fetched {len(sections)} sections, {len(components)} components, {len(data_flows)} data flows for targeting")

        # Run architecture-aware web research for compliance issues
        # Research identifies relevant components/dataFlows and their sourceSection refs
        logger.info("Running architecture-aware web research for compliance issues...")
        research_comments = [
            {"comment": issue.get("originalComment", ""), "target_quote": issue.get("targetQuote", "")}
            for issue in issues
        ]
        research_results = research_for_comments(
            research_comments,
            components=components,
            data_flows=data_flows,
            max_per_comment=3,
        )

        # Enrich issues with research context and relevant architecture elements
        for i, issue in enumerate(issues):
            if i in research_results:
                result = research_results[i]
                issue["research_context"] = result["research_context"]
                issue["research_reasoning"] = result["reasoning"]
                issue["relevant_components"] = result["relevant_components"]
                issue["relevant_data_flows"] = result["relevant_data_flows"]

                # Collect sourceSection refs from relevant components/dataFlows
                source_sections = set()
                for comp in result["relevant_components"]:
                    source_section = comp.get("sourceSection", {})
                    if isinstance(source_section, dict) and source_section.get("_ref"):
                        source_sections.add(source_section["_ref"])
                for flow in result["relevant_data_flows"]:
                    source_section = flow.get("sourceSection", {})
                    if isinstance(source_section, dict) and source_section.get("_ref"):
                        source_sections.add(source_section["_ref"])
                issue["target_section_ids"] = list(source_sections)

                logger.info(f"Issue {issue.get('_id')}: {len(result['research_context'])} chars research, "
                           f"{len(result['relevant_components'])} relevant components, "
                           f"{len(result['relevant_data_flows'])} relevant flows, "
                           f"{len(source_sections)} target sections")

                # Persist research context to Sanity
                self.sanity.update(issue["_id"], {"researchContext": result["research_context"]})

        # Build section/component context for the LLM
        # Use numeric indices instead of UUIDs - the LLM keeps failing to use UUIDs correctly
        sections_context = []
        section_id_map = {}  # index -> actual ID
        section_id_to_index = {}  # actual ID -> index (for mapping target_section_ids)
        section_full_text = {}  # index -> full original text (for validation)
        for i, s in enumerate(sections):
            original_text = s.get("originalText", "")
            # Provide full text up to 1000 chars for better matching (truncated only for very long sections)
            text_for_matching = original_text[:1000] if len(original_text) > 1000 else original_text
            sections_context.append({
                "index": i,  # Use simple numeric index
                "title": s.get("title"),
                "text": text_for_matching,  # Full or near-full text for exact matching
            })
            section_id_map[i] = s.get("_id")
            section_id_to_index[s.get("_id")] = i
            section_full_text[i] = original_text

        components_context = []
        component_id_map = {}  # index -> actual ID
        for i, c in enumerate(components):
            components_context.append({
                "index": i,  # Use simple numeric index
                "name": c.get("name"),
                "type": c.get("componentType"),
                "description": c.get("description", "")[:100],
            })
            component_id_map[i] = c.get("_id")

        # Convert target_section_ids to indices for each issue
        for issue in issues:
            target_ids = issue.get("target_section_ids", [])
            target_indices = [section_id_to_index[sid] for sid in target_ids if sid in section_id_to_index]
            issue["target_section_indices"] = target_indices

        # Prepare shared context for the orchestrator LLM
        sections_json = json.dumps(sections_context, indent=2)
        components_json = json.dumps(components_context, indent=2)

        # Log sections being passed to LLM for debugging find_text issues
        logger.info(f"Sections being passed to LLM ({len(sections_context)} total):")
        for s in sections_context:
            text_preview = s.get("text", "")[:80].replace("\n", "\\n")
            logger.info(f"  [{s['index']}] {s['title']}: '{text_preview}...'")

        # Log components to help identify where LLM might be pulling wrong find_text from
        logger.info(f"Components being passed to LLM ({len(components_context)} total):")
        for c in components_context:
            desc_preview = c.get("description", "")[:60]
            logger.info(f"  [{c['index']}] {c['name']} ({c['type']}): '{desc_preview}...'")

        # Process each issue individually, collecting all actions
        all_actions: List[ModificationAction] = []

        for issue in issues:
            # Get a brief description for logging
            issue_title = issue.get("title", "")
            issue_comment = issue.get("originalComment", "")
            brief_desc = issue_title if issue_title else (issue_comment[:80] + "..." if len(issue_comment) > 80 else issue_comment)
            logger.info(f"Generating fixes for compliance issue: {brief_desc}")

            # Build prompt for this single issue
            issue_json = json.dumps([issue], indent=2)

            prompt = f"""You are an orchestrator agent that performs TARGETED privacy improvements to a technical design document.

This compliance issue comes with:
1. **research_context**: Web research with specific implementation guidance
2. **research_reasoning**: Explanation of what needs to be done and which components are affected
3. **relevant_components/relevant_data_flows**: The specific technical components involved
4. **target_section_indices**: The EXACT sections where modifications should be made (pre-identified from component sourceSections)

IMPORTANT: The target sections have already been identified based on which components/data flows are relevant to this issue.
Focus your modifications on those specific target sections. Use the research_context to generate SPECIFIC, ACTIONABLE modifications.
Do NOT use vague language like "implement audit logs" - instead specify exact tools, configurations, and standards from the research.

## COMPLETE Document Structure (from Sanity)

### All Sections in the Document (use "index" to target):
{sections_json}

### All Technical Components Identified (use "index" to target):
{components_json}

## Compliance Issue to Address:
{issue_json}

IMPORTANT: The issue includes "target_section_indices" - these are the PRIMARY sections you should modify.
The relevant components/data flows have already been analyzed to identify these target sections.

## How to Target Sections/Components:
Use the numeric INDEX from the lists above:
- section_index: 0 = first section, 1 = second section, etc.
- component_index: 0 = first component, 1 = second component, etc.

Valid section indices: 0 to {len(sections) - 1}
Valid component indices: 0 to {len(components) - 1 if components else -1}

## Action Types:
1. "replace" - Replace specific text with improved privacy-compliant version
2. "transform" - Modify existing content to add privacy controls and specificity
3. "generate" - Generate entirely new content (for adding missing privacy sections)
4. "image" - Generate a diagram (e.g., data flow diagram showing encryption points)

## Your Task - TARGETED Privacy Improvements:

For this compliance issue:

1. **Use the pre-identified target sections** - The "target_section_indices" in the issue tell you exactly which sections to modify.
   These were determined by analyzing which components/data flows are relevant to the issue.

2. **Apply research-informed fixes** - Use the specific guidance from research_context and research_reasoning.
   The reasoning explains what needs to be done and which technical components are involved.

3. **Be EXTREMELY specific** - You MUST incorporate exact tools, protocols, configurations, parameter names from the research.
   - REQUIRED: Include specific tool names (e.g., "AWS CloudTrail", "Apache Log4j")
   - GOOD: "Enable PostgreSQL pg_audit extension with pgaudit.log = 'all' and pgaudit.log_parameter = on"
   - BAD: "Implement audit logging for the database" (too vague - what tool? what settings?)
   - BAD: "Regularly assess the system for compliance" (what frequency? what assessment tool? what checklist?)

4. **Preserve original formatting** - CRITICAL formatting rules:
   - Keep original content (diagrams, lists, flow arrows) intact - do not insert text within them
   - ADD recommendations as a new section below the original content
   - Use bullet points or numbered lists for clarity
   - Use bold headers to organize by component or topic

5. **Target the right sections** - If target_section_indices is empty, use the targetQuote to find the right section.
   Otherwise, prioritize modifying the sections indicated in target_section_indices.

### Example:
If an issue has:
- target_section_indices: [2, 5]
- research_reasoning: "Step 1: Need to add audit logging. Step 2: Patient Database (PostgreSQL) is relevant..."
- research_context: "PostgreSQL HIPAA audit logging requires pg_audit extension..."

Then you should create modifications for sections 2 and 5, using the specific PostgreSQL pg_audit guidance.

Return a JSON array where each object has:
- issue_id: The _id of the issue this action addresses (can have MULTIPLE actions per issue)
- action_type: One of "replace", "transform", "generate", "image"
- section_index: The numeric index of the target section (0, 1, 2, etc.) OR
- component_index: The numeric index of the target component (if targeting a component instead)
- instruction: Detailed instruction incorporating specifics from research_context
- find_text: EXACT text copied from the section's "text" field - must match character-for-character
- replace_text: REQUIRED for all actions - the privacy-improved replacement text

CRITICAL - find_text MUST BE EXACT:
- Copy the find_text EXACTLY from the section's "text" field shown above - character for character
- DO NOT use component names, component descriptions, or any text not in the section's "text" field
- Include exact capitalization, punctuation, and spacing
- The Google Docs API uses literal string matching - even a single character difference means no match
- Use a UNIQUE phrase (20-60 characters) that appears only once in the document
- DO NOT paraphrase, invent, or modify the original text in find_text

COMMON MISTAKE TO AVOID:
- WRONG: Using component names like "Ingestion: Service responsible for..." as find_text
- RIGHT: Copying actual text from section["text"] like "Vitals flowsheets" or "Provider notes"
- The find_text MUST be a substring that literally appears in the section's "text" field above

ACTION-SPECIFIC REQUIREMENTS:
- For "replace" and "transform": MUST have both find_text AND replace_text
- For "generate": MUST have both find_text AND replace_text:
  * find_text = the LAST sentence or phrase of the target section (copied EXACTLY from "text")
  * replace_text = that same exact text PLUS the new content appended after it
  * This allows the new content to be inserted at the end of the section
- For "image": Only need instruction (describes what diagram to generate)

EXAMPLE for "generate" action:
If the section ends with "...controlled with user permissions)." you would use:
- find_text: "controlled with user permissions)."
- replace_text: "controlled with user permissions).\n\n### Data Retention Policy\nNew policy content here..."

FORMATTING GUIDELINES:
- Keep original content (diagrams, lists, paragraphs) intact
- Add recommendations as a NEW section below the original content
- Use bullet points or numbered lists for implementation requirements
- Use bold headers to organize by component or topic
- Never insert lengthy text inline within existing structures

IMPORTANT NOTES:
- find_text MUST be copied exactly from the section's "text" field shown in the sections list above
- Look at the "text" value for your target section_index and copy a substring from it verbatim
- You CAN and SHOULD generate MULTIPLE actions to address this issue comprehensively
- Focus on making the document privacy-compliant for this specific issue
- Use section_index (0, 1, 2...) to target sections, NOT section names or titles

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

                # Clean up common JSON issues from LLM output
                # Remove trailing commas before ] or }
                result = re.sub(r',\s*([}\]])', r'\1', result)
                # Fix unquoted property names (common LLM mistake)
                result = re.sub(r'(\{|\,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', result)

                # Fix unescaped newlines in string values (LLM outputs literal newlines)
                # This regex finds content between quotes and escapes literal newlines
                def escape_newlines_in_strings(json_str: str) -> str:
                    """Escape literal newlines within JSON string values."""
                    result_chars = []
                    in_string = False
                    escape_next = False
                    for char in json_str:
                        if escape_next:
                            result_chars.append(char)
                            escape_next = False
                        elif char == '\\':
                            result_chars.append(char)
                            escape_next = True
                        elif char == '"':
                            result_chars.append(char)
                            in_string = not in_string
                        elif char == '\n' and in_string:
                            # Escape literal newline inside string
                            result_chars.append('\\n')
                        elif char == '\r' and in_string:
                            # Escape literal carriage return inside string
                            result_chars.append('\\r')
                        elif char == '\t' and in_string:
                            # Escape literal tab inside string
                            result_chars.append('\\t')
                        else:
                            result_chars.append(char)
                    return ''.join(result_chars)

                result = escape_newlines_in_strings(result)

                try:
                    actions_data = json.loads(result)
                except json.JSONDecodeError as je:
                    logger.error(f"JSON parse error for issue {issue.get('_id')}: {je}")
                    logger.error(f"Raw LLM response (first 500 chars): {result[:500]}")
                    # Try to extract just the array portion
                    match = re.search(r'\[[\s\S]*\]', result)
                    if match:
                        try:
                            actions_data = json.loads(match.group(0))
                        except:
                            actions_data = []
                    else:
                        actions_data = []

                # Map indices to actual IDs for this issue's actions
                for action in actions_data:
                    # Check for section_index or component_index
                    section_idx = action.get("section_index")
                    component_idx = action.get("component_index")

                    target_id = None
                    target_type = "section"

                    if section_idx is not None:
                        # Map section index to actual ID
                        if isinstance(section_idx, int) and section_idx in section_id_map:
                            target_id = section_id_map[section_idx]
                            target_type = "section"
                            logger.debug(f"Mapped section_index {section_idx} -> {target_id}")
                        else:
                            logger.warning(f"Invalid section_index: {section_idx} (valid: 0-{len(sections)-1})")
                    elif component_idx is not None:
                        # Map component index to actual ID
                        if isinstance(component_idx, int) and component_idx in component_id_map:
                            target_id = component_id_map[component_idx]
                            target_type = "component"
                            logger.debug(f"Mapped component_index {component_idx} -> {target_id}")
                        else:
                            logger.warning(f"Invalid component_index: {component_idx} (valid: 0-{len(components)-1})")

                    # Fallback to first section if no valid target
                    if not target_id:
                        if sections:
                            target_id = section_id_map.get(0, sections[0].get("_id", ""))
                            target_type = "section"
                            section_idx = 0  # Set for validation below
                            logger.warning(f"No valid target found, falling back to first section: {target_id}")
                        else:
                            logger.warning(f"No valid target and no sections available, skipping action")
                            continue

                    # Validate that find_text actually exists in the target section
                    find_text = action.get("find_text", "")
                    if find_text and section_idx is not None and section_idx in section_full_text:
                        full_text = section_full_text[section_idx]
                        if find_text not in full_text:
                            logger.warning(f"find_text NOT FOUND in section {section_idx}: '{find_text[:50]}...'")
                            logger.warning(f"  Section text starts with: '{full_text[:100]}...'")
                            # Still add the action but mark it as potentially invalid
                        else:
                            logger.debug(f"find_text validated in section {section_idx}")

                    all_actions.append(
                        ModificationAction(
                            action_type=action.get("action_type", "replace"),
                            target_node_type=target_type,
                            target_node_id=target_id,
                            instruction=action.get("instruction", ""),
                            related_issue_id=action.get("issue_id"),
                            find_text=find_text,
                            replace_text=action.get("replace_text"),
                        )
                    )

                logger.info(f"  Generated {len(actions_data)} actions for this issue")

                # Diagnostic: Log the research context vs generated replace_text for comparison
                research_ctx = issue.get("research_context", "")
                research_reasoning = issue.get("research_reasoning", "")
                if research_ctx or research_reasoning:
                    logger.info("=" * 30 + " VAGUENESS DIAGNOSTIC " + "=" * 30)
                    logger.info(f"Issue: {issue.get('title', issue.get('originalComment', '')[:80])}")
                    if research_reasoning:
                        logger.info(f"Research reasoning: {research_reasoning[:500]}...")
                    if research_ctx:
                        logger.info(f"Research context (first 500 chars): {research_ctx[:500]}...")
                    for action in actions_data:
                        replace_text = action.get("replace_text", "")
                        if replace_text:
                            logger.info(f"Generated replace_text: {replace_text[:300]}...")
                    logger.info("=" * 30 + " END VAGUENESS DIAGNOSTIC " + "=" * 30)

            except Exception as e:
                logger.error(f"Failed to generate actions for issue {issue.get('_id')}: {e}")
                continue

        # Log summary of all actions
        logger.info(f"Orchestrator decided on {len(all_actions)} total modification actions")
        for action in all_actions:
            logger.info(f"  - {action.action_type} on {action.target_node_type} {action.target_node_id}")
            if action.action_type == "image":
                # Image actions only need instruction
                logger.info(f"    instruction: '{action.instruction[:80]}...'")
            elif action.find_text and action.replace_text:
                # All other actions (replace, transform, generate) need both find_text and replace_text
                find_preview = action.find_text[:50] + "..." if len(action.find_text) > 50 else action.find_text
                replace_preview = action.replace_text[:50] + "..." if len(action.replace_text) > 50 else action.replace_text
                logger.info(f"    find_text: '{find_preview}' -> replace_text: '{replace_preview}'")
            else:
                logger.warning(f"    INCOMPLETE (won't write to GDoc): find_text={'yes' if action.find_text else 'NO'}, replace_text={'yes' if action.replace_text else 'NO'}")

        return all_actions

    def create_modification_suggestions(
        self,
        design_doc_id: str,
        actions: List[ModificationAction],
    ) -> List[str]:
        """
        Create modification suggestion documents from decided actions.
        Returns list of created suggestion IDs.
        """
        suggestion_ids: List[str] = []

        for action in actions:
            suggestion_doc = {
                "_id": f"mod-{uuid.uuid4()}",
                "_type": "modificationSuggestion",
                "title": action.instruction[:100],
                "modificationType": self._map_action_to_modification_type(action.action_type),
                "findText": action.find_text,
                "replaceText": action.replace_text,
                "rationale": action.instruction,
                "agentAction": action.action_type,
                "status": "pending",
                "parentDocument": {"_type": "reference", "_ref": design_doc_id},
            }

            if action.related_issue_id:
                suggestion_doc["relatedIssue"] = {
                    "_type": "reference",
                    "_ref": action.related_issue_id,
                }

            # Store target section reference if targeting a section
            if action.target_node_type == "section" and action.target_node_id:
                suggestion_doc["targetSection"] = {
                    "_type": "reference",
                    "_ref": action.target_node_id,
                }

            if action.find_text and action.replace_text:
                suggestion_doc["diffPreview"] = {
                    "before": action.find_text,
                    "after": action.replace_text,
                }

            suggestion_id = self.sanity.create(suggestion_doc)
            if suggestion_id:
                suggestion_ids.append(suggestion_id)

        logger.info(f"Created {len(suggestion_ids)} modification suggestions")
        return suggestion_ids

    def execute_agent_actions(
        self,
        actions: List[ModificationAction],
        research_context: Dict[int, str],
    ) -> List[Dict[str, Any]]:
        """
        Execute Sanity Agent Actions (generate, transform, image) for each action.

        This calls the actual Sanity Agent Actions API to modify documents.
        Returns list of results from each action.
        """
        results = []

        for i, action in enumerate(actions):
            if not action.target_node_id:
                logger.warning(f"Action {i} has no target node ID, skipping")
                continue

            # Build instruction with research context if available
            instruction = action.instruction
            if i in research_context:
                instruction = f"{instruction}\n\nResearch context for specificity:\n{research_context[i][:2000]}"

            try:
                if action.action_type == "generate":
                    # Use Generate for new content
                    result = self.agent_actions.generate(
                        document_id=action.target_node_id,
                        instruction=instruction,
                        instruction_params={
                            "research": {"type": "constant", "value": research_context.get(i, "")}
                        } if i in research_context else None,
                    )
                    results.append({"action": action, "result": result, "success": "error" not in result})

                elif action.action_type == "transform":
                    # Use Transform for modifying existing content
                    result = self.agent_actions.transform(
                        document_id=action.target_node_id,
                        instruction=instruction,
                        instruction_params={
                            "findText": {"type": "constant", "value": action.find_text or ""},
                        } if action.find_text else None,
                    )
                    results.append({"action": action, "result": result, "success": "error" not in result})

                elif action.action_type == "image":
                    # Use Generate with image target for diagrams
                    result = self.agent_actions.generate_image(
                        document_id=action.target_node_id,
                        image_path="diagram",  # Assumes diagram field exists
                        instruction=instruction,
                        async_mode=True,
                    )
                    results.append({"action": action, "result": result, "success": "error" not in result})

                elif action.action_type == "replace":
                    # For simple replacements, use Transform with specific instruction
                    if action.find_text and action.replace_text:
                        result = self.agent_actions.transform(
                            document_id=action.target_node_id,
                            instruction=f"Replace '{action.find_text}' with '{action.replace_text}'. Make this replacement exactly.",
                        )
                        results.append({"action": action, "result": result, "success": "error" not in result})

                logger.info(f"Executed {action.action_type} on {action.target_node_id}")

            except Exception as e:
                logger.error(f"Failed to execute {action.action_type} on {action.target_node_id}: {e}")
                results.append({"action": action, "error": str(e), "success": False})

        successful = sum(1 for r in results if r.get("success"))
        logger.info(f"Executed {successful}/{len(results)} agent actions successfully")

        return results

    def _map_action_to_modification_type(self, action_type: str) -> str:
        """Map action types to modification types."""
        mapping = {
            "replace": "replace",
            "transform": "rewrite",
            "generate": "insert",
            "image": "add_diagram",
        }
        return mapping.get(action_type, "replace")

    def get_pending_modifications(self, design_doc_id: str) -> List[Dict[str, Any]]:
        """Get all pending modifications for a document."""
        query = f"""
        *[_type == "modificationSuggestion" &&
          parentDocument._ref == "{design_doc_id}" &&
          status == "pending"] {{
            _id,
            title,
            modificationType,
            findText,
            replaceText,
            rationale,
            agentAction,
            diffPreview
        }}
        """
        return self.sanity.query(query)

    def export_modifications_for_google_docs(
        self, design_doc_id: str
    ) -> List[Dict[str, str]]:
        """
        Export pending modifications in a format suitable for the MCP apply-suggestions tool.
        Returns list of {findText, replaceText} pairs.
        """
        modifications = self.get_pending_modifications(design_doc_id)

        suggestions = []
        skipped = 0
        for mod in modifications:
            if mod.get("findText") and mod.get("replaceText"):
                suggestions.append(
                    {
                        "findText": mod["findText"],
                        "replaceText": mod["replaceText"],
                    }
                )
            else:
                skipped += 1
                logger.debug(f"Skipped mod {mod.get('_id')}: findText={bool(mod.get('findText'))}, replaceText={bool(mod.get('replaceText'))}")

        logger.info(f"Exported {len(suggestions)} modifications for Google Docs (skipped {skipped} incomplete)")
        return suggestions

    def export_guided_modifications(self, design_doc_id: str) -> List[Dict[str, Any]]:
        """
        Export modifications in a format suitable for guided user walkthrough.

        Returns structured data for each modification including:
        - modification_text: The text to add to the document
        - target_section: Section title and whether it's new
        - issue_reference: The compliance issue this addresses

        Returns:
            List of guided modification objects
        """
        # Query modifications with dereferenced related data
        query = f"""
        *[_type == "modificationSuggestion" &&
          parentDocument._ref == "{design_doc_id}" &&
          status == "pending"] {{
            _id,
            title,
            modificationType,
            replaceText,
            rationale,
            agentAction,
            "targetSection": targetSection->{{
                _id,
                title,
                originalText
            }},
            "relatedIssue": relatedIssue->{{
                _id,
                title,
                originalComment,
                severity,
                targetQuote
            }}
        }}
        """
        modifications = self.sanity.query(query)

        guided = []
        for i, mod in enumerate(modifications):
            # Determine target section info
            target_section = mod.get("targetSection")
            if target_section:
                section_info = {
                    "title": target_section.get("title", "Untitled Section"),
                    "is_new": False,
                }
            else:
                # No specific section - suggest adding as new section
                section_info = {
                    "title": "New Section (append to document)",
                    "is_new": True,
                }

            # Get issue reference text
            related_issue = mod.get("relatedIssue")
            if related_issue:
                # Use the original comment as the issue reference
                issue_ref = related_issue.get("originalComment") or related_issue.get("title", "")
            else:
                # Fallback to rationale
                issue_ref = mod.get("rationale", "")

            # The modification text is the replace_text (what to add)
            modification_text = mod.get("replaceText", "")

            guided.append({
                "index": i,
                "suggestion_id": mod.get("_id"),
                "modification_text": modification_text,
                "target_section": section_info,
                "issue_reference": issue_ref,
                "severity": related_issue.get("severity", "medium") if related_issue else "medium",
                "action_type": mod.get("agentAction", "generate"),
            })

        logger.info(f"Exported {len(guided)} guided modifications")
        return guided

    def mark_modifications_applied(
        self, design_doc_id: str, suggestion_ids: List[str]
    ) -> None:
        """Mark modifications as applied after successful write-back."""
        from datetime import datetime

        for suggestion_id in suggestion_ids:
            self.sanity.update(
                suggestion_id,
                {
                    "status": "applied",
                    "appliedAt": datetime.utcnow().isoformat() + "Z",
                },
            )

        # Check if all issues are resolved
        pending_query = f"""
        count(*[_type == "modificationSuggestion" &&
               parentDocument._ref == "{design_doc_id}" &&
               status == "pending"])
        """
        pending_count = self.sanity.query(pending_query)

        if pending_count == 0:
            self.sanity.update(design_doc_id, {"status": "approved"})

        logger.info(f"Marked {len(suggestion_ids)} modifications as applied")

    def cleanup_design_documents(
        self,
        design_doc_id: Optional[str] = None,
        google_doc_id: Optional[str] = None,
        delete_all: bool = False,
    ) -> Dict[str, Any]:
        """
        Clean up design-related documents from Sanity.

        Can be used to:
        1. Delete all documents for a specific designDocument (by design_doc_id or google_doc_id)
        2. Delete ALL design-related documents in the dataset (delete_all=True)

        The deletion order respects Sanity's reference integrity:
        1. modificationSuggestion (references complianceIssue, designDocument)
        2. complianceIssue (references designDocument)
        3. dataFlow (references technicalComponent, documentSection, designDocument)
        4. technicalComponent (references documentSection, designDocument)
        5. documentSection (references designDocument)
        6. designDocument

        Args:
            design_doc_id: Specific designDocument ID to clean up
            google_doc_id: Google Doc ID to look up the designDocument
            delete_all: If True, deletes ALL design-related documents (ignores other args)

        Returns:
            Dict with counts of deleted documents per type
        """
        deleted_counts: Dict[str, int] = {
            "modificationSuggestion": 0,
            "complianceIssue": 0,
            "dataFlow": 0,
            "technicalComponent": 0,
            "documentSection": 0,
            "designDocument": 0,
        }

        # Determine target scope
        if delete_all:
            logger.info("Cleaning up ALL design-related documents from Sanity...")
            scope_filter = ""  # No filter = all documents
        elif design_doc_id:
            logger.info(f"Cleaning up documents for designDocument: {design_doc_id}")
            scope_filter = f' && parentDocument._ref == "{design_doc_id}"'
        elif google_doc_id:
            # Look up the designDocument by googleDocId
            lookup_query = f'*[_type == "designDocument" && googleDocId == "{google_doc_id}"][0]._id'
            result = self.sanity.query(lookup_query)
            if not result:
                logger.warning(f"No designDocument found for googleDocId: {google_doc_id}")
                return deleted_counts
            design_doc_id = result
            logger.info(f"Found designDocument {design_doc_id} for googleDocId: {google_doc_id}")
            scope_filter = f' && parentDocument._ref == "{design_doc_id}"'
        else:
            logger.error("Must provide design_doc_id, google_doc_id, or delete_all=True")
            return deleted_counts

        # Delete in order that respects reference integrity
        # Order: modificationSuggestion -> complianceIssue -> dataFlow -> technicalComponent -> documentSection -> designDocument

        # 1. Delete modificationSuggestions
        if delete_all:
            query = '*[_type == "modificationSuggestion"]._id'
        else:
            query = f'*[_type == "modificationSuggestion"{scope_filter}]._id'
        mod_ids = self.sanity.query(query)
        if mod_ids:
            logger.info(f"Deleting {len(mod_ids)} modificationSuggestion documents...")
            success, _ = self.sanity.delete_batch(mod_ids)
            deleted_counts["modificationSuggestion"] = success

        # 2. Delete complianceIssues
        if delete_all:
            query = '*[_type == "complianceIssue"]._id'
        else:
            query = f'*[_type == "complianceIssue"{scope_filter}]._id'
        issue_ids = self.sanity.query(query)
        if issue_ids:
            logger.info(f"Deleting {len(issue_ids)} complianceIssue documents...")
            success, _ = self.sanity.delete_batch(issue_ids)
            deleted_counts["complianceIssue"] = success

        # 3. Delete dataFlows
        if delete_all:
            query = '*[_type == "dataFlow"]._id'
        else:
            query = f'*[_type == "dataFlow"{scope_filter}]._id'
        flow_ids = self.sanity.query(query)
        if flow_ids:
            logger.info(f"Deleting {len(flow_ids)} dataFlow documents...")
            success, _ = self.sanity.delete_batch(flow_ids)
            deleted_counts["dataFlow"] = success

        # 4. Delete technicalComponents
        if delete_all:
            query = '*[_type == "technicalComponent"]._id'
        else:
            query = f'*[_type == "technicalComponent"{scope_filter}]._id'
        comp_ids = self.sanity.query(query)
        if comp_ids:
            logger.info(f"Deleting {len(comp_ids)} technicalComponent documents...")
            success, _ = self.sanity.delete_batch(comp_ids)
            deleted_counts["technicalComponent"] = success

        # 5. Delete documentSections
        if delete_all:
            query = '*[_type == "documentSection"]._id'
        else:
            query = f'*[_type == "documentSection"{scope_filter}]._id'
        section_ids = self.sanity.query(query)
        if section_ids:
            logger.info(f"Deleting {len(section_ids)} documentSection documents...")
            success, _ = self.sanity.delete_batch(section_ids)
            deleted_counts["documentSection"] = success

        # 6. Delete designDocument(s)
        if delete_all:
            query = '*[_type == "designDocument"]._id'
            design_ids = self.sanity.query(query)
        else:
            design_ids = [design_doc_id] if design_doc_id else []

        if design_ids:
            logger.info(f"Deleting {len(design_ids)} designDocument documents...")
            success, _ = self.sanity.delete_batch(design_ids)
            deleted_counts["designDocument"] = success

        total_deleted = sum(deleted_counts.values())
        logger.info(f"Cleanup complete. Total deleted: {total_deleted}")
        for doc_type, count in deleted_counts.items():
            if count > 0:
                logger.info(f"  {doc_type}: {count}")

        return deleted_counts


def process_document_with_review(
    doc_text: str,
    doc_title: str,
    review_comments: List[Dict[str, Any]],
    google_doc_id: Optional[str] = None,
    google_doc_url: Optional[str] = None,
    execute_actions: bool = True,
    parsed_components: Optional[List[Dict[str, Any]]] = None,
    parsed_data_flows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Full pipeline: get/create document graph -> add sections -> process review -> execute agent actions.

    Flow:
    1. Get or create document graph in Sanity (reuses existing if googleDocId matches)
    2. Add sections if needed (sections are required for orchestration but not for initial review)
    3. Create compliance issues from review comments
    4. Use You.com to research implementation specifics
    5. Orchestrator decides which Sanity Agent Actions to call
    6. Execute Agent Actions (generate, transform, image) on Sanity documents
    7. Export modified content as findText/replaceText for Google Docs

    On failure, cleans up any documents created during this run to prevent orphaned data.

    Args:
        parsed_components: Pre-parsed components from review phase (skips LLM parsing if provided)
        parsed_data_flows: Pre-parsed data flows from review phase (skips LLM parsing if provided)

    Returns a dict with:
    - design_doc_id: The Sanity document ID
    - issue_ids: List of compliance issue IDs
    - action_results: Results from executing Sanity Agent Actions
    - suggestions: List of {findText, replaceText} for Google Docs
    """
    orchestrator = DocumentGraphOrchestrator()
    design_doc_id = None
    is_new = False

    try:
        # Step 1: Get or create document graph
        if parsed_components:
            logger.info("Step 1: Creating document graph using pre-parsed structure...")
        else:
            logger.info("Step 1: Creating document graph (parsing with LLM)...")

        doc_result = orchestrator.get_or_create_design_document(
            google_doc_id=google_doc_id or "",
            doc_text=doc_text,
            doc_title=doc_title,
            include_sections=True,  # Include sections for orchestration phase
            parsed_components=parsed_components,
            parsed_data_flows=parsed_data_flows,
        )

        design_doc_id = doc_result.get("design_doc_id")
        is_new = doc_result.get("is_new", True)

        if not design_doc_id:
            return {"error": "Failed to get or create document graph"}

        logger.info(f"Document {'created' if is_new else 'reused from Sanity'}: {design_doc_id}")

        # Step 1b: Add sections if the document was reused and didn't have them
        if not is_new and not doc_result.get("sections"):
            logger.info("Step 1b: Adding sections to existing document...")
            orchestrator.add_sections_to_document(design_doc_id, doc_text)

        # Step 2: Create compliance issues from review
        logger.info("Step 2: Creating compliance issues from review comments...")
        issue_ids = orchestrator.create_compliance_issues_from_review(
            design_doc_id=design_doc_id,
            review_comments=review_comments,
        )

        # Step 3: Decide agent actions (includes You.com research)
        logger.info("Step 3: Deciding agent actions with You.com research...")
        actions = orchestrator.decide_agent_actions(
            design_doc_id=design_doc_id,
            issue_ids=issue_ids,
        )

        # Build research context map from issues
        research_context = {}
        issues_query = f'*[_type == "complianceIssue" && _id in {json.dumps(issue_ids)}] {{ _id, researchContext }}'
        issues = orchestrator.sanity.query(issues_query)
        for i, issue in enumerate(issues):
            if issue.get("researchContext"):
                research_context[i] = issue["researchContext"]

        action_results = []
        suggestion_ids = []

        if execute_actions and actions:
            # Step 4: Execute Sanity Agent Actions
            logger.info("Step 4: Executing Sanity Agent Actions (generate, transform, image)...")
            action_results = orchestrator.execute_agent_actions(
                actions=actions,
                research_context=research_context,
            )

            # Step 5: Create modification suggestions to track what was done
            logger.info("Step 5: Recording modification suggestions...")
            suggestion_ids = orchestrator.create_modification_suggestions(
                design_doc_id=design_doc_id,
                actions=actions,
            )
        else:
            # If not executing, just create suggestions for manual review
            logger.info("Step 4: Creating modification suggestions (actions not executed)...")
            suggestion_ids = orchestrator.create_modification_suggestions(
                design_doc_id=design_doc_id,
                actions=actions,
            )

        # Step 6: Export guided modifications for user walkthrough
        logger.info("Step 6: Exporting guided modifications...")
        guided_modifications = orchestrator.export_guided_modifications(design_doc_id)

        # Serialize action results properly
        serialized_action_results = []
        for r in action_results:
            action = r.get("action")
            if action and isinstance(action, ModificationAction):
                serialized_action_results.append({
                    "action_type": action.action_type,
                    "target": action.target_node_id,
                    "success": r.get("success", False),
                    "error": r.get("error"),
                })
            else:
                serialized_action_results.append({
                    "action_type": "unknown",
                    "target": "unknown",
                    "success": r.get("success", False),
                    "error": r.get("error"),
                })

        return {
            "design_doc_id": design_doc_id,
            "issue_ids": issue_ids,
            "suggestion_ids": suggestion_ids,
            "action_results": serialized_action_results,
            "guided_modifications": guided_modifications,
        }

    except Exception as e:
        # Re-raise the original exception (each run creates separate documents, no cleanup needed)
        raise


def process_document_with_review_status(
    doc_text: str,
    doc_title: str,
    review_comments: List[Dict[str, Any]],
    google_doc_id: Optional[str] = None,
    google_doc_url: Optional[str] = None,
    execute_actions: bool = True,
    parsed_components: Optional[List[Dict[str, Any]]] = None,
    parsed_data_flows: Optional[List[Dict[str, Any]]] = None,
    status: Optional["StatusEmitter"] = None,
) -> Dict[str, Any]:
    """
    Full pipeline with status updates for the frontend.

    Same as process_document_with_review but emits status updates.
    """
    from status_stream import StatusEmitter

    # Create a no-op emitter if none provided
    if status is None:
        status = StatusEmitter()

    orchestrator = DocumentGraphOrchestrator()
    design_doc_id = None
    is_new = False

    try:
        # Step 1: Get or create document graph
        if parsed_components:
            status.step("Creating document graph from pre-parsed structure")
        else:
            status.step("Parsing document and creating graph structure")

        doc_result = orchestrator.get_or_create_design_document(
            google_doc_id=google_doc_id or "",
            doc_text=doc_text,
            doc_title=doc_title,
            include_sections=True,
            parsed_components=parsed_components,
            parsed_data_flows=parsed_data_flows,
        )

        design_doc_id = doc_result.get("design_doc_id")
        is_new = doc_result.get("is_new", True)

        if not design_doc_id:
            status.error("Failed to create document graph")
            return {"error": "Failed to get or create document graph"}

        # Emit graph stats
        num_components = len(doc_result.get("components", []))
        num_flows = len(doc_result.get("data_flows", []))
        num_sections = len(doc_result.get("sections", []))
        status.info(
            f"Created graph with {num_components} components, {num_flows} flows, {num_sections} sections",
            {"components": num_components, "data_flows": num_flows, "sections": num_sections}
        )

        # Step 1b: Add sections if needed
        if not is_new and not doc_result.get("sections"):
            status.detail("Adding sections to existing document")
            orchestrator.add_sections_to_document(design_doc_id, doc_text)

        # Step 2: Create compliance issues
        status.step(f"Creating compliance issues from {len(review_comments)} review comments")
        issue_ids = orchestrator.create_compliance_issues_from_review(
            design_doc_id=design_doc_id,
            review_comments=review_comments,
        )
        status.info(f"Created {len(issue_ids)} compliance issues")

        # Step 3: Research and decide agent actions
        status.step("Running architecture-aware web research for compliance issues")

        # Get the issues for research
        issues_query = f"""
        *[_type == "complianceIssue" && _id in {json.dumps(issue_ids)}] {{
            _id,
            title,
            originalComment,
            severity,
            targetQuote
        }}
        """
        issues = orchestrator.sanity.query(issues_query)

        # Get document graph for research
        components = doc_result.get("components", [])
        data_flows = doc_result.get("data_flows", [])

        # Run research with status updates
        from web_research import research_comment_with_architecture

        research_results = {}
        for i, issue in enumerate(issues):
            comment = {
                "comment": issue.get("originalComment", ""),
                "target_quote": issue.get("targetQuote", "")
            }
            comment_preview = issue.get("title") or issue.get("originalComment", "")[:60]
            status.detail(f"Researching: {comment_preview}...")

            result = research_comment_with_architecture(
                comment=comment,
                components=components,
                data_flows=data_flows,
                search_count=3,
            )

            if result.get("research_context") or result.get("relevant_components"):
                research_results[i] = result

                # Show research reasoning if available
                if result.get("reasoning"):
                    reasoning_preview = result["reasoning"][:100] + "..." if len(result["reasoning"]) > 100 else result["reasoning"]
                    status.detail(f"Research insight: {reasoning_preview}")

                # Update issue with research context
                if result.get("research_context"):
                    orchestrator.sanity.update(issue["_id"], {"researchContext": result["research_context"]})

        status.info(f"Completed research for {len(research_results)}/{len(issues)} issues")

        # Decide agent actions
        status.step("Determining necessary modifications")

        # Enrich issues with research results
        for i, issue in enumerate(issues):
            if i in research_results:
                result = research_results[i]
                issue["research_context"] = result.get("research_context", "")
                issue["research_reasoning"] = result.get("reasoning", "")
                issue["relevant_components"] = result.get("relevant_components", [])
                issue["relevant_data_flows"] = result.get("relevant_data_flows", [])

                # Map components to target sections
                target_section_ids = []
                for comp in result.get("relevant_components", []):
                    source_section = comp.get("sourceSection", {})
                    if isinstance(source_section, dict) and source_section.get("_ref"):
                        target_section_ids.append(source_section["_ref"])
                for flow in result.get("relevant_data_flows", []):
                    source_section = flow.get("sourceSection", {})
                    if isinstance(source_section, dict) and source_section.get("_ref"):
                        if source_section["_ref"] not in target_section_ids:
                            target_section_ids.append(source_section["_ref"])
                issue["target_section_ids"] = target_section_ids

        # Now run the full decide_agent_actions
        actions = orchestrator.decide_agent_actions(
            design_doc_id=design_doc_id,
            issue_ids=issue_ids,
        )

        status.info(f"Determined {len(actions)} modifications", {"actions": len(actions)})

        # Build research context map from issues
        research_context = {}
        for i, issue in enumerate(issues):
            if issue.get("research_context"):
                research_context[i] = issue["research_context"]

        action_results = []
        suggestion_ids = []

        if execute_actions and actions:
            # Step 4: Execute agent actions
            status.step(f"Executing {len(actions)} modification actions")

            action_results = orchestrator.execute_agent_actions(
                actions=actions,
                research_context=research_context,
            )

            success_count = sum(1 for r in action_results if r.get("success"))
            status.info(f"Executed {success_count}/{len(actions)} actions successfully")

            # Step 5: Create modification suggestions
            status.step("Recording modification suggestions")
            suggestion_ids = orchestrator.create_modification_suggestions(
                design_doc_id=design_doc_id,
                actions=actions,
            )
        else:
            status.step("Creating modification suggestions")
            suggestion_ids = orchestrator.create_modification_suggestions(
                design_doc_id=design_doc_id,
                actions=actions,
            )

        # Step 6: Export guided modifications for user walkthrough
        status.step("Preparing guided modifications")
        guided_modifications = orchestrator.export_guided_modifications(design_doc_id)

        if guided_modifications:
            status.success(
                f"Generated {len(guided_modifications)} modifications to review",
                {"modifications": len(guided_modifications)}
            )
            # Show first modification preview
            first_mod = guided_modifications[0]
            section_title = first_mod.get("target_section", {}).get("title", "Unknown")
            status.detail(f"First modification targets: {section_title}")
        else:
            status.warning("No modifications generated")

        # Serialize action results
        serialized_action_results = []
        for r in action_results:
            action = r.get("action")
            if action and isinstance(action, ModificationAction):
                serialized_action_results.append({
                    "action_type": action.action_type,
                    "target": action.target_node_id,
                    "success": r.get("success", False),
                    "error": r.get("error"),
                })
            else:
                serialized_action_results.append({
                    "action_type": "unknown",
                    "target": "unknown",
                    "success": r.get("success", False),
                    "error": r.get("error"),
                })

        return {
            "design_doc_id": design_doc_id,
            "issue_ids": issue_ids,
            "suggestion_ids": suggestion_ids,
            "action_results": serialized_action_results,
            "guided_modifications": guided_modifications,
        }

    except Exception as e:
        status.error(f"Pipeline failed: {str(e)}")
        raise
