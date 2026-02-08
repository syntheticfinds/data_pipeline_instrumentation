"""
Sanity client for fetching HIPAA regulations.

Uses the Sanity HTTP API to query regulations from the hippa-privacy dataset.
"""
import os
import logging
import time
import json
import requests
from typing import List, Dict, Any, Optional
from functools import lru_cache

from openai import OpenAI

# Configure logging
logger = logging.getLogger("sanity_client")

# Sanity project configuration
SANITY_PROJECT_ID = os.getenv("SANITY_PROJECT_ID", "ukousf31")
SANITY_DATASET = os.getenv("SANITY_DATASET", "production")
SANITY_API_VERSION = "2024-01-01"


def _get_sanity_url() -> str:
    """Build the Sanity API URL."""
    return f"https://{SANITY_PROJECT_ID}.api.sanity.io/v{SANITY_API_VERSION}/data/query/{SANITY_DATASET}"


def _run_groq_query(query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Execute a GROQ query against Sanity."""
    url = _get_sanity_url()
    payload = {"query": query}
    if params:
        payload["params"] = params

    logger.debug(f"Executing GROQ query against {SANITY_PROJECT_ID}/{SANITY_DATASET}")
    start_time = time.time()

    try:
        response = requests.get(url, params={"query": query}, timeout=10)
        response.raise_for_status()
        data = response.json()
        results = data.get("result", [])
        elapsed = (time.time() - start_time) * 1000
        result_count = len(results) if isinstance(results, list) else 1
        logger.info(f"Sanity query completed: {result_count} results in {elapsed:.1f}ms")
        return results
    except requests.RequestException as e:
        elapsed = (time.time() - start_time) * 1000
        logger.error(f"Sanity query failed after {elapsed:.1f}ms: {e}")
        return []


def _portable_text_to_plain(blocks: List[Dict[str, Any]]) -> str:
    """Convert Sanity portable text blocks to plain text."""
    if not blocks:
        return ""

    text_parts = []
    for block in blocks:
        if block.get("_type") == "block":
            children = block.get("children", [])
            block_text = "".join(child.get("text", "") for child in children)

            # Handle list items with indentation
            list_item = block.get("listItem")
            level = block.get("level", 1)
            if list_item:
                indent = "  " * (level - 1)
                if list_item == "number":
                    block_text = f"{indent}• {block_text}"
                else:
                    block_text = f"{indent}- {block_text}"

            text_parts.append(block_text)

    return "\n".join(text_parts)


def _extract_concepts_with_llm(text: str) -> List[str]:
    """
    Use LLM to extract privacy/HIPAA-relevant concepts from text.
    Returns a list of search terms for finding relevant regulations.
    """
    logger.info("Extracting concepts from selection using LLM")
    start_time = time.time()

    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        model = os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini")

        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=[
                {
                    "role": "system",
                    "content": """You extract HIPAA-relevant concepts from text for regulation lookup.

Output a JSON array of 5-10 search terms that would help find relevant HIPAA regulations.

Focus on:
- Data handling concepts (PHI, disclosure, authorization, access, storage, transmission)
- Entity types (covered entity, business associate, health plan, provider)
- Security concepts (safeguards, breach, encryption, audit, controls)
- Compliance concepts (notification, consent, rights, penalties, violations)
- Procedural concepts (hearing, investigation, enforcement, complaint)

Return ONLY a JSON array of strings, no explanation. Example:
["PHI disclosure", "business associate", "breach notification", "access controls"]"""
                },
                {
                    "role": "user",
                    "content": f"Extract HIPAA-relevant concepts from this text:\n\n{text[:2000]}"
                }
            ],
        )

        result = response.choices[0].message.content or "[]"
        # Strip code fences if present
        if result.startswith("```"):
            result = result.strip("`").strip()
            if result.startswith("json"):
                result = result[4:].strip()

        concepts = json.loads(result)
        elapsed = (time.time() - start_time) * 1000
        logger.info(f"LLM concept extraction completed in {elapsed:.1f}ms")
        logger.info(f"Extracted concepts: {concepts}")
        return concepts if isinstance(concepts, list) else []

    except Exception as e:
        logger.warning(f"LLM concept extraction failed: {e}, falling back to keyword matching")
        return []


@lru_cache(maxsize=1)
def fetch_all_regulations_summary() -> List[Dict[str, str]]:
    """
    Fetch a summary of all HIPAA regulations (cached).
    Returns lightweight records for quick keyword matching.
    """
    query = """
    *[_type == "hipaaRegulation"] | order(sectionNumber asc) {
        _id,
        sectionNumber,
        title,
        "subpartTitle": subpart->title,
        aiRelevance,
        riskLevel
    }
    """
    results = _run_groq_query(query)
    return [
        {
            "id": r.get("_id", ""),
            "section": r.get("sectionNumber", ""),
            "title": r.get("title", ""),
            "subpart": r.get("subpartTitle", ""),
            "ai_relevance": r.get("aiRelevance", ""),
            "risk_level": r.get("riskLevel", "medium"),
        }
        for r in results
    ]


def fetch_regulation_by_id(doc_id: str) -> Optional[Dict[str, Any]]:
    """Fetch full regulation details by document ID."""
    query = f'*[_type == "hipaaRegulation" && _id == "{doc_id}"][0]'
    results = _run_groq_query(query)
    if not results:
        return None

    reg = results if isinstance(results, dict) else results[0] if results else None
    if not reg:
        return None

    return {
        "section": reg.get("sectionNumber", ""),
        "title": reg.get("title", ""),
        "content": _portable_text_to_plain(reg.get("content", [])),
        "compliance_guidance": _portable_text_to_plain(reg.get("complianceGuidance", [])),
        "ai_relevance": reg.get("aiRelevance", ""),
        "risk_level": reg.get("riskLevel", "medium"),
        "citations": reg.get("citations", []),
    }


def fetch_regulations_by_ids(doc_ids: List[str]) -> List[Dict[str, Any]]:
    """Fetch full details for multiple regulations."""
    if not doc_ids:
        return []

    ids_str = ", ".join(f'"{d}"' for d in doc_ids)
    query = f"""
    *[_type == "hipaaRegulation" && _id in [{ids_str}]] {{
        _id,
        sectionNumber,
        title,
        content,
        complianceGuidance,
        aiRelevance,
        riskLevel,
        citations
    }}
    """
    results = _run_groq_query(query)

    return [
        {
            "id": r.get("_id", ""),
            "section": r.get("sectionNumber", ""),
            "title": r.get("title", ""),
            "content": _portable_text_to_plain(r.get("content", [])),
            "compliance_guidance": _portable_text_to_plain(r.get("complianceGuidance", [])),
            "ai_relevance": r.get("aiRelevance", ""),
            "risk_level": r.get("riskLevel", "medium"),
            "citations": r.get("citations", []),
        }
        for r in results
    ]


def search_regulations_by_concepts(concepts: List[str], limit: int = 10) -> List[Dict[str, Any]]:
    """
    Search regulations by concepts in title, content, aiRelevance, and complianceGuidance.
    """
    if not concepts:
        logger.warning("No concepts provided for regulation search")
        return []

    logger.debug(f"Searching regulations with {len(concepts)} concepts: {concepts}")

    # Build match conditions for each concept
    match_conditions = []
    for concept in concepts:
        concept_lower = concept.lower()
        match_conditions.append(
            f'(title match "*{concept_lower}*" || aiRelevance match "*{concept_lower}*")'
        )

    # Combine with OR - find regulations matching any concept
    combined_condition = " || ".join(match_conditions)

    query = f"""
    *[_type == "hipaaRegulation" && ({combined_condition})] [0...{limit}] {{
        _id,
        sectionNumber,
        title,
        content,
        complianceGuidance,
        aiRelevance,
        riskLevel,
        citations
    }}
    """

    logger.debug(f"GROQ query concepts: {concepts[:5]}...")

    results = _run_groq_query(query)

    return [
        {
            "id": r.get("_id", ""),
            "section": r.get("sectionNumber", ""),
            "title": r.get("title", ""),
            "content": _portable_text_to_plain(r.get("content", [])),
            "compliance_guidance": _portable_text_to_plain(r.get("complianceGuidance", [])),
            "ai_relevance": r.get("aiRelevance", ""),
            "risk_level": r.get("riskLevel", "medium"),
            "citations": r.get("citations", []),
        }
        for r in results
    ]


def find_relevant_regulations(text: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Find HIPAA regulations relevant to the given text.

    Uses LLM-based concept extraction for better relevance matching.
    Falls back to keyword matching if LLM extraction fails.
    """
    logger.info(f"Finding relevant regulations for text ({len(text)} chars)")
    logger.debug(f"Selection text preview: {text[:200]}..." if len(text) > 200 else f"Selection text: {text}")

    # Try LLM-based concept extraction first
    concepts = _extract_concepts_with_llm(text)

    if not concepts:
        # Fallback to basic keyword extraction
        logger.info("Using fallback keyword extraction")
        fallback_keywords = [
            "privacy", "security", "breach", "notification", "disclosure",
            "authorization", "consent", "access", "PHI", "protected health information",
            "covered entity", "business associate", "safeguard", "encryption",
            "audit", "training", "minimum necessary", "de-identification",
            "individual rights", "accounting", "restriction", "confidential",
            "penalty", "violation", "enforcement", "complaint", "investigation",
            "data", "information", "patient", "health", "medical", "record",
            "transmission", "electronic", "physical", "administrative",
        ]
        text_lower = text.lower()
        concepts = [kw for kw in fallback_keywords if kw.lower() in text_lower]

        if not concepts:
            concepts = ["privacy", "security", "PHI", "covered entity"]
            logger.info("No keywords found, using default concepts")

    logger.info(f"Using {len(concepts)} concepts for search: {concepts[:10]}")

    # Search for regulations matching these concepts
    regulations = search_regulations_by_concepts(concepts[:10], limit=max_results)

    logger.info(f"Retrieved {len(regulations)} relevant regulations:")
    for reg in regulations:
        has_guidance = "yes" if reg.get("compliance_guidance") else "no"
        logger.info(f"  - § {reg.get('section')} - {reg.get('title')} (risk: {reg.get('risk_level')}, guidance: {has_guidance})")

    return regulations


def format_regulations_for_prompt(regulations: List[Dict[str, Any]]) -> str:
    """
    Format regulations into a string suitable for LLM context.
    Includes full content and compliance guidance when available.
    """
    if not regulations:
        return "No specific HIPAA regulations found for this context."

    formatted = []
    for reg in regulations:
        section = reg.get("section", "Unknown")
        title = reg.get("title", "")
        ai_relevance = reg.get("ai_relevance", "")
        risk_level = reg.get("risk_level", "medium")
        content = reg.get("content", "")
        compliance_guidance = reg.get("compliance_guidance", "")
        citations = reg.get("citations", [])

        reg_text = f"""
=== § {section} - {title} ===
Risk Level: {risk_level}
Citations: {', '.join(citations) if citations else 'N/A'}

Why this regulation matters for AI systems:
{ai_relevance}

What the regulation requires:
{content}
"""

        if compliance_guidance:
            reg_text += f"""
Recommended actions:
{compliance_guidance}
"""
        else:
            reg_text += """
Recommended actions: None available. Only state what the regulation requires.
"""

        formatted.append(reg_text)

    return "\n" + "="*60 + "\n".join(formatted)


def get_available_regulation_sections() -> List[str]:
    """
    Get a list of all available regulation section numbers.
    Used for validating citations.
    """
    query = '*[_type == "hipaaRegulation"] { sectionNumber }'
    results = _run_groq_query(query)
    return [r.get("sectionNumber", "") for r in results if r.get("sectionNumber")]
