"""
Web research module using You.com Search API.

Enhanced research strategy:
  1. Identify relevant technical components and data flows for each comment
  2. Extract search-relevant information from those components (tech stack, data types)
  3. Run targeted searches informed by the actual architecture
  4. Return research context along with the relevant components/dataFlows
     (with their sourceSection refs) so the orchestrator knows which sections to modify
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional, TypedDict

import requests
from openai import OpenAI

logger = logging.getLogger("web_research")

YDC_API_URL = "https://ydc-index.io/v1/search"


class RelevantArchitecture(TypedDict):
    """Architecture elements relevant to a compliance comment."""
    components: List[Dict[str, Any]]  # Relevant technicalComponent docs
    data_flows: List[Dict[str, Any]]  # Relevant dataFlow docs
    search_queries: List[str]  # Generated search queries
    reasoning: str  # LLM's reasoning about what needs to be done


class CommentResearchResult(TypedDict):
    """Research result for a single comment."""
    research_context: str  # Web research results
    relevant_components: List[Dict[str, Any]]  # Components with _id, name, sourceSection
    relevant_data_flows: List[Dict[str, Any]]  # DataFlows with _id, name, sourceSection
    reasoning: str  # What needs to be done and why these components are relevant


class RegulationResearchResult(TypedDict):
    """Research result for HIPAA regulations relevant to a selection."""
    regulations: List[Dict[str, Any]]  # List of {regulation, what_youre_doing, description, fine_range, action}
    raw_research: str  # Raw web research text


def _get_api_key() -> Optional[str]:
    return os.getenv("YDC_API_KEY")


def _ydc_search(query: str, count: int = 5) -> List[Dict[str, Any]]:
    """
    Call You.com Search API and return the raw web results list.
    Returns empty list on failure.
    """
    api_key = _get_api_key()
    if not api_key:
        return []

    try:
        resp = requests.get(
            YDC_API_URL,
            headers={"X-API-Key": api_key},
            params={"query": query, "count": count},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return (data.get("results") or {}).get("web") or []
    except Exception as e:
        logger.warning(f"You.com search failed for query '{query[:80]}': {e}")
        return []


def _format_snippets(web_results: List[Dict[str, Any]], max_results: int = 3) -> str:
    """Format web results into a prompt-ready string."""
    snippets: List[str] = []
    for result in web_results[:max_results]:
        title = result.get("title", "")
        url = result.get("url", "")
        result_snippets = result.get("snippets") or []
        for snippet in result_snippets[:2]:
            snippets.append(f"[{title}]\n{snippet}")
        # Diagnostic: Log what snippets we're getting
        logger.debug(f"  Research source: {title}")
        logger.debug(f"    URL: {url}")
        for i, snippet in enumerate(result_snippets[:2]):
            logger.debug(f"    Snippet {i+1}: {snippet[:150]}...")
    return "\n\n".join(snippets)


def _identify_relevant_architecture(
    comment: Dict[str, Any],
    components: List[Dict[str, Any]],
    data_flows: List[Dict[str, Any]],
) -> RelevantArchitecture:
    """
    Use LLM to identify which components and data flows are relevant to a compliance comment,
    and extract search-relevant information from them.

    The LLM reasons through:
    1. What needs to be done given the comment
    2. Which components/dataFlows are involved
    3. What technical details from those components inform the search

    Returns structured data with relevant architecture elements and search queries.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — skipping architecture analysis")
        return RelevantArchitecture(
            components=[], data_flows=[], search_queries=[], reasoning=""
        )

    comment_text = comment.get("comment", "")
    target_quote = comment.get("target_quote", "")

    # Format components for the prompt
    components_str = ""
    if components:
        comp_lines = []
        for i, comp in enumerate(components):
            comp_id = comp.get("_id", f"comp_{i}")
            name = comp.get("name", "Unknown")
            ctype = comp.get("componentType", "")
            desc = comp.get("description", "")[:200]
            source_section = comp.get("sourceSection", {})
            source_ref = source_section.get("_ref", "") if isinstance(source_section, dict) else ""
            comp_lines.append(f"[{comp_id}] {name} ({ctype}): {desc} | sourceSection: {source_ref}")
        components_str = "\n".join(comp_lines)

    # Format data flows for the prompt
    flows_str = ""
    if data_flows:
        flow_lines = []
        for i, flow in enumerate(data_flows):
            flow_id = flow.get("_id", f"flow_{i}")
            name = flow.get("name", "Unknown")
            source = flow.get("sourceComponent", {})
            target = flow.get("targetComponent", {})
            source_name = source.get("name", source.get("_ref", "?")) if isinstance(source, dict) else "?"
            target_name = target.get("name", target.get("_ref", "?")) if isinstance(target, dict) else "?"
            source_section = flow.get("sourceSection", {})
            source_ref = source_section.get("_ref", "") if isinstance(source_section, dict) else ""
            flow_lines.append(f"[{flow_id}] {name or f'{source_name} -> {target_name}'} | sourceSection: {source_ref}")
        flows_str = "\n".join(flow_lines)

    prompt = f"""You are analyzing a HIPAA compliance comment to identify which technical components and data flows need to be modified.

COMPLIANCE COMMENT:
"{comment_text}"

TARGET QUOTE FROM DOCUMENT:
"{target_quote}"

TECHNICAL COMPONENTS IN THE SYSTEM:
{components_str if components_str else "(none)"}

DATA FLOWS IN THE SYSTEM:
{flows_str if flows_str else "(none)"}

Your task: Think through this step by step.

1. WHAT NEEDS TO BE DONE: Describe what modification or fix is needed based on the comment.

2. RELEVANT COMPONENTS/DATA FLOWS: For each relevant component or data flow:
   - State which one is relevant (by ID)
   - Explain WHY it's relevant to this comment
   - Extract SEARCH-RELEVANT INFO: What technical details (tech stack, protocols, data types) should inform our search for implementation guidance?

3. SEARCH QUERIES: Based on the technical details extracted, generate 2-4 specific search queries.
   - Make queries PURELY TECHNICAL - focus on HOW to implement the feature with specific tools
   - DO NOT include "HIPAA", "compliance", "regulation", or "privacy" in search queries
   - The comment already specifies the compliance requirement - searches should find technical implementation details only
   - Include terms like "configuration", "implementation", "code example", "setup guide", or specific tool names
   - Example good queries: "PostgreSQL pg_audit configuration example", "AWS S3 encryption at rest setup guide", "event logging best practices microservices"
   - Example bad queries: "HIPAA compliance database" (includes compliance), "audit logging HIPAA" (includes HIPAA), "privacy data retention" (includes privacy)

Return JSON:
{{
  "reasoning": "Step 1: [what needs to be done]\\n\\nStep 2:\\n- [component/flow ID]: [why relevant] → search info: [tech details]\\n- ...\\n\\nStep 3: These components/flows will be passed to an orchestrator that will modify their source sections.",
  "relevant_component_ids": ["comp-id-1", "comp-id-2"],
  "relevant_data_flow_ids": ["flow-id-1"],
  "search_queries": ["PostgreSQL HIPAA audit logging pg_audit", "..."]
}}

Return ONLY the JSON, no explanation."""

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.0,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = (resp.choices[0].message.content or "").strip()

        # Strip code fences if present
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json\n"):
                text = text[len("json\n"):]
            text = text.strip()

        result = json.loads(text)

        # Map IDs back to full component/dataFlow objects
        comp_id_set = set(result.get("relevant_component_ids", []))
        flow_id_set = set(result.get("relevant_data_flow_ids", []))

        relevant_components = [
            {
                "_id": c.get("_id"),
                "name": c.get("name"),
                "componentType": c.get("componentType"),
                "description": c.get("description"),
                "sourceSection": c.get("sourceSection"),
            }
            for c in components if c.get("_id") in comp_id_set
        ]

        relevant_data_flows = [
            {
                "_id": f.get("_id"),
                "name": f.get("name"),
                "sourceComponent": f.get("sourceComponent"),
                "targetComponent": f.get("targetComponent"),
                "sourceSection": f.get("sourceSection"),
            }
            for f in data_flows if f.get("_id") in flow_id_set
        ]

        search_queries = result.get("search_queries", [])
        if isinstance(search_queries, list):
            search_queries = [q for q in search_queries if isinstance(q, str)][:4]

        reasoning = result.get("reasoning", "")

        logger.info(f"Identified {len(relevant_components)} relevant components, {len(relevant_data_flows)} relevant flows")
        logger.info(f"Generated {len(search_queries)} search queries")

        return RelevantArchitecture(
            components=relevant_components,
            data_flows=relevant_data_flows,
            search_queries=search_queries,
            reasoning=reasoning,
        )

    except Exception as e:
        logger.warning(f"Architecture analysis failed: {e}")
        return RelevantArchitecture(
            components=[], data_flows=[], search_queries=[], reasoning=""
        )


def _run_searches(queries: List[str], count_per_query: int = 3) -> str:
    """Run search queries and combine results."""
    if not queries:
        return ""

    all_sections: List[str] = []
    for query in queries:
        logger.info(f"  Searching: {query}")
        results = _ydc_search(query, count=count_per_query)
        text = _format_snippets(results, max_results=2)
        if text:
            all_sections.append(f"--- {query} ---\n{text}")

    return "\n\n".join(all_sections)


def research_comment_with_architecture(
    comment: Dict[str, Any],
    components: List[Dict[str, Any]],
    data_flows: List[Dict[str, Any]],
    search_count: int = 3,
) -> CommentResearchResult:
    """
    Research a comment using architecture-aware analysis.

    1. Identifies which components/dataFlows are relevant
    2. Extracts search-relevant info from them
    3. Runs targeted searches
    4. Returns research context with the relevant architecture elements

    Args:
        comment: The compliance comment to research
        components: All technicalComponent documents from Sanity
        data_flows: All dataFlow documents from Sanity
        search_count: Max results per search query

    Returns:
        CommentResearchResult with research_context, relevant_components,
        relevant_data_flows, and reasoning.
    """
    api_key = _get_api_key()
    if not api_key:
        logger.warning("YDC_API_KEY not set — skipping web research")
        return CommentResearchResult(
            research_context="",
            relevant_components=[],
            relevant_data_flows=[],
            reasoning="",
        )

    # Step 1: Identify relevant architecture and generate search queries
    architecture = _identify_relevant_architecture(comment, components, data_flows)

    # Step 2: Run the searches
    research_text = ""
    if architecture["search_queries"]:
        research_text = _run_searches(architecture["search_queries"], count_per_query=search_count)

    if research_text:
        logger.info(f"Research completed: {len(research_text)} chars")
        # Diagnostic: Log the full research context so we can compare to generated output
        logger.info("=" * 40 + " RESEARCH CONTEXT START " + "=" * 40)
        logger.info(research_text[:2000] if len(research_text) > 2000 else research_text)
        if len(research_text) > 2000:
            logger.info(f"... (truncated, full length: {len(research_text)} chars)")
        logger.info("=" * 40 + " RESEARCH CONTEXT END " + "=" * 40)
    else:
        logger.info("No research results found")

    return CommentResearchResult(
        research_context=research_text,
        relevant_components=architecture["components"],
        relevant_data_flows=architecture["data_flows"],
        reasoning=architecture["reasoning"],
    )


def research_for_comments(
    comments: List[Dict[str, Any]],
    components: Optional[List[Dict[str, Any]]] = None,
    data_flows: Optional[List[Dict[str, Any]]] = None,
    max_per_comment: int = 3,
) -> Dict[int, CommentResearchResult]:
    """
    Run architecture-aware web research for each compliance comment.

    For each comment:
    1. Identifies which components/dataFlows are relevant to the comment
    2. Extracts search-relevant info (tech stack, protocols) from those components
    3. Runs targeted searches based on the extracted info
    4. Returns research context along with the relevant components/dataFlows

    The relevant components/dataFlows include their sourceSection references,
    allowing the orchestrator to know which document sections to modify.

    Args:
        comments: List of compliance comments to research
        components: All technicalComponent documents from Sanity (with _id, name,
                   componentType, description, sourceSection)
        data_flows: All dataFlow documents from Sanity (with _id, name,
                   sourceComponent, targetComponent, sourceSection)
        max_per_comment: Max search results per query

    Returns:
        Dict mapping comment index to CommentResearchResult containing:
        - research_context: Web research text
        - relevant_components: Components relevant to this comment (with sourceSection)
        - relevant_data_flows: DataFlows relevant to this comment (with sourceSection)
        - reasoning: LLM's reasoning about what needs to be done
    """
    ydc_key = _get_api_key()
    openai_key = os.getenv("OPENAI_API_KEY")

    if not ydc_key:
        logger.warning("YDC_API_KEY not set — returning empty research")
        return {}

    if not openai_key:
        logger.warning("OPENAI_API_KEY not set — returning empty research")
        return {}

    components = components or []
    data_flows = data_flows or []

    research: Dict[int, CommentResearchResult] = {}

    for i, comment in enumerate(comments):
        comment_text = comment.get("comment", "")
        logger.info(f"Comment {i+1}: researching...")
        logger.info(f"  Comment text: {comment_text[:100]}...")

        result = research_comment_with_architecture(
            comment=comment,
            components=components,
            data_flows=data_flows,
            search_count=max_per_comment,
        )

        # Only include if we got meaningful results
        if result["research_context"] or result["relevant_components"] or result["relevant_data_flows"]:
            research[i] = result
            logger.info(f"  Result: {len(result['research_context'])} chars research, "
                       f"{len(result['relevant_components'])} components, "
                       f"{len(result['relevant_data_flows'])} flows")
        else:
            logger.info(f"  No results for comment {i+1}")

    logger.info(f"Research completed for {len(research)}/{len(comments)} comments")
    return research


def research_hipaa_regulations(
    selection: str,
    components: Optional[List[Dict[str, Any]]] = None,
    data_flows: Optional[List[Dict[str, Any]]] = None,
    max_regulations: int = 5,
) -> RegulationResearchResult:
    """
    Research HIPAA regulations relevant to the selected text using You.com.

    Instead of looking up regulations from a static database, this searches the web
    for relevant HIPAA requirements, real-world consequences, and enforcement examples.

    Returns structured regulation info including:
    - Which regulation applies
    - What consequences/penalties have occurred for violations
    - What actions to take

    Args:
        selection: The selected text to analyze
        components: Technical components in the system (for context)
        data_flows: Data flows in the system (for context)
        max_regulations: Maximum number of regulations to return

    Returns:
        RegulationResearchResult with regulations list and raw research text
    """
    ydc_key = _get_api_key()
    openai_key = os.getenv("OPENAI_API_KEY")

    if not ydc_key:
        logger.warning("YDC_API_KEY not set — skipping regulation research")
        return RegulationResearchResult(regulations=[], raw_research="")

    if not openai_key:
        logger.warning("OPENAI_API_KEY not set — skipping regulation research")
        return RegulationResearchResult(regulations=[], raw_research="")

    logger.info(f"Researching HIPAA regulations for selection ({len(selection)} chars)")

    # Step 1: Extract key concepts and generate search queries
    # Format DETAILED component/flow context for the prompt
    context_str = ""

    if components:
        context_str += "TECHNICAL COMPONENTS:\n"
        for comp in components[:5]:
            name = comp.get("name", "Unknown")
            ctype = comp.get("componentType", comp.get("component_type", ""))

            # Check for PHI/PII handling
            data_handled = comp.get("dataHandled", [])
            phi_data = [d.get("dataType", "") for d in data_handled if isinstance(d, dict) and d.get("isPHI")]
            pii_data = [d.get("dataType", "") for d in data_handled if isinstance(d, dict) and d.get("isPII")]

            line = f"- {name}"
            if ctype:
                line += f" ({ctype})"
            if phi_data:
                line += f" [HANDLES PHI: {', '.join(phi_data[:3])}]"
            if pii_data:
                line += f" [HANDLES PII: {', '.join(pii_data[:3])}]"
            context_str += line + "\n"

    if data_flows:
        context_str += "\nDATA FLOWS:\n"
        for flow in data_flows[:5]:
            name = flow.get("name", "")
            source = flow.get("source", "")
            target = flow.get("target", "")

            # Get data types
            data_types = flow.get("dataTypes", [])
            dt_names = [d.get("dataType", str(d)) if isinstance(d, dict) else str(d) for d in data_types[:3]]

            # Check encryption
            encryption = flow.get("encryption", {})
            encrypted = encryption.get("inTransit", False) if isinstance(encryption, dict) else False

            if source and target:
                line = f"- {source} → {target}"
            else:
                line = f"- {name}"
            if dt_names:
                line += f" (data: {', '.join(dt_names)})"
            if not encrypted:
                line += " [NO ENCRYPTION MENTIONED]"
            context_str += line + "\n"

    query_prompt = f"""Analyze this healthcare/AI system design and its technical components to generate 3-4 specific HIPAA search queries.

SELECTED TEXT:
{selection[:1500]}

{f"SYSTEM ARCHITECTURE:{chr(10)}{context_str}" if context_str else ""}

Based on the components above (especially those handling PHI/PII and unencrypted data flows), generate search queries that will find:
1. HIPAA regulations specific to the component types (e.g., databases, APIs, AI engines)
2. Requirements for the specific data types being handled (e.g., patient vitals, medical records)
3. Technical safeguards required for the data flows (e.g., encryption, access controls)
4. Healthcare-specific technologies and techniques for compliance

EXAMPLE QUERIES:
- "HIPAA 164.312 database PHI encryption requirements healthcare"
- "HIPAA AI machine learning PHI compliance safeguards"
- "HIPAA data flow encryption in transit requirements penalties"
- "healthcare API PHI access control audit logging HITRUST"

Return JSON:
{{
  "queries": ["query targeting specific component types and data handling", "query2", "query3", "query4"],
  "key_activities": ["specific PHI-related activities that trigger HIPAA requirements"]
}}

Return ONLY the JSON."""

    try:
        client = OpenAI(api_key=openai_key)
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.0,
            max_tokens=500,
            messages=[{"role": "user", "content": query_prompt}],
        )
        query_text = (resp.choices[0].message.content or "").strip()

        # Strip code fences
        if query_text.startswith("```"):
            query_text = query_text.strip("`")
            if query_text.startswith("json\n"):
                query_text = query_text[len("json\n"):]
            query_text = query_text.strip()

        query_result = json.loads(query_text)
        search_queries = query_result.get("queries", [])[:4]
        key_activities = query_result.get("key_activities", [])

        logger.info(f"Generated {len(search_queries)} regulation search queries")
        for q in search_queries:
            logger.info(f"  Query: {q}")

    except Exception as e:
        logger.warning(f"Failed to generate regulation queries: {e}")
        # Fallback queries
        search_queries = [
            "HIPAA compliance requirements healthcare data",
            "HIPAA violation penalties enforcement cases",
            "HIPAA PHI protection requirements"
        ]
        key_activities = []

    # Step 2: Run the searches
    all_research: List[str] = []
    for query in search_queries:
        logger.info(f"  Searching: {query}")
        results = _ydc_search(query, count=3)
        text = _format_snippets(results, max_results=2)
        if text:
            all_research.append(f"--- {query} ---\n{text}")

    raw_research = "\n\n".join(all_research)

    if not raw_research:
        logger.warning("No web research results found for regulations")
        return RegulationResearchResult(regulations=[], raw_research="")

    logger.info(f"Collected {len(raw_research)} chars of regulation research")

    # Step 3: Extract structured regulation info from research
    extract_prompt = f"""Based on this web research about HIPAA regulations, extract specific regulations that apply to this system design.

SYSTEM DESIGN TEXT:
{selection[:1000]}

{f"KEY ACTIVITIES IDENTIFIED:{chr(10)}{chr(10).join('- ' + a for a in key_activities)}" if key_activities else ""}

WEB RESEARCH RESULTS:
{raw_research[:4000]}

For each relevant regulation found, extract:
1. regulation: The specific HIPAA section or rule (e.g., "§ 164.312(a)(1) - Access Control")
2. what_youre_doing: What activity in the system triggers this regulation
3. description: What the regulation requires in plain language
4. fine_range: The potential penalty range (e.g., "up to $50,000 per violation" or "$100 to $50,000 per violation")
5. action: Specific technical action to comply (from the research)

Return JSON array (max {max_regulations} regulations, ordered by relevance):
[
  {{
    "regulation": "§ 164.xxx - Rule Name",
    "what_youre_doing": "storing patient vitals in a database",
    "description": "requires unique user identification and access controls for all systems containing PHI",
    "fine_range": "up to $50,000 per violation, with annual maximum of $1.5M",
    "action": "Implement role-based access control with unique user IDs and automatic session timeouts"
  }}
]

IMPORTANT:
- Focus on what the regulation REQUIRES, not specific enforcement cases
- Provide fine RANGES, not specific company fines or case anecdotes
- Be specific about what the system is doing that triggers each regulation
- Include specific technical actions to comply

Return ONLY the JSON array."""

    try:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.0,
            max_tokens=2000,
            messages=[{"role": "user", "content": extract_prompt}],
        )
        extract_text = (resp.choices[0].message.content or "").strip()

        # Strip code fences
        if extract_text.startswith("```"):
            extract_text = extract_text.strip("`")
            if extract_text.startswith("json\n"):
                extract_text = extract_text[len("json\n"):]
            extract_text = extract_text.strip()

        regulations = json.loads(extract_text)

        if not isinstance(regulations, list):
            regulations = []

        logger.info(f"Extracted {len(regulations)} regulations from research")
        for reg in regulations:
            logger.info(f"  - {reg.get('regulation', 'Unknown')}: {reg.get('description', '')[:80]}...")

        return RegulationResearchResult(
            regulations=regulations[:max_regulations],
            raw_research=raw_research,
        )

    except Exception as e:
        logger.warning(f"Failed to extract regulations from research: {e}")
        return RegulationResearchResult(regulations=[], raw_research=raw_research)


def format_regulations_for_review_prompt(research_result: RegulationResearchResult) -> str:
    """
    Format researched regulations into a prompt-ready string.

    Formats each regulation with its description, fine range, and recommended action.
    """
    regulations = research_result.get("regulations", [])

    if not regulations:
        return "No specific HIPAA regulations found for this context. Generate general privacy best-practice comments only."

    formatted = []
    for i, reg in enumerate(regulations, 1):
        section = reg.get("regulation", "Unknown regulation")
        what = reg.get("what_youre_doing", "")
        description = reg.get("description", "")
        fine_range = reg.get("fine_range", "significant fines")
        action = reg.get("action", "")

        entry = f"""### Regulation {i}: {section}

**What triggers this**: {what}

**What it requires**: {description}

**Potential fines**: {fine_range}

**Recommended action**: {action}
"""
        formatted.append(entry)

    return "\n\n".join(formatted)
