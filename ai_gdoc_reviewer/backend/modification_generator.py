"""
Modification generator module.

Generates compliance modifications by researching each (issue, component) pair
using You.com, then grouping similar modifications together.
"""

import os
import json
import logging
import re
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from openai import OpenAI
from status_stream import StatusEmitter

logger = logging.getLogger("modification_generator")


def _get_ydc_api_key() -> Optional[str]:
    return os.getenv("YDC_API_KEY")


def _ydc_search(query: str, count: int = 3) -> List[Dict[str, Any]]:
    """Call You.com Search API and return web results."""
    import requests

    api_key = _get_ydc_api_key()
    if not api_key:
        return []

    try:
        resp = requests.get(
            "https://ydc-index.io/v1/search",
            params={"query": query, "count": count},
            headers={"X-API-Key": api_key},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            # You.com API returns results in .results.web
            return (data.get("results") or {}).get("web") or []
    except Exception as e:
        logger.warning(f"YDC search failed: {e}")

    return []


def _format_search_results(results: List[Dict[str, Any]], max_chars: int = 1200) -> str:
    """Format search results into a string."""
    if not results:
        return ""

    snippets = []
    total_chars = 0
    for hit in results:
        title = hit.get("title", "")
        # You.com API returns snippets as a list
        hit_snippets = hit.get("snippets") or []
        snippet = hit_snippets[0] if hit_snippets else hit.get("description", "")
        if snippet:
            text = f"- {title}: {snippet}"
            if total_chars + len(text) > max_chars:
                break
            snippets.append(text)
            total_chars += len(text)

    return "\n".join(snippets)


def _extract_action_from_issue(issue_comment: str) -> str:
    """Extract the suggested action from an issue comment."""
    # Look for action-like phrases
    action_patterns = [
        r"(?:Implement|Add|Configure|Enable|Use|Apply|Set up|Establish|Create|Deploy)\s+[^.]+",
        r"(?:should|must|need to)\s+([^.]+)",
    ]

    for pattern in action_patterns:
        match = re.search(pattern, issue_comment, re.IGNORECASE)
        if match:
            return match.group(0).strip()

    # Fallback: return last sentence (often the action)
    sentences = issue_comment.split(". ")
    if sentences:
        return sentences[-1].strip()

    return ""


@dataclass
class ResearchResult:
    """Result of researching a (issue, component/flow) pair."""
    issue_index: int
    target_name: str
    target_type: str  # "component" or "data_flow"
    issue_comment: str
    research_text: str
    modification: str
    severity: str


def _research_issue_component_pair(
    issue_index: int,
    issue: Dict[str, Any],
    target_name: str,
    target_type: str,
) -> Optional[ResearchResult]:
    """
    Research what modifications are needed for a specific (issue, component/flow) pair.

    Uses You.com to find HIPAA-specific modifications for the component to address the issue.
    """
    issue_comment = issue.get("comment", "")
    severity = issue.get("severity", "medium")
    suggested_action = _extract_action_from_issue(issue_comment)

    # Build a specific research query
    query = f"HIPAA {target_type} {target_name} {suggested_action} healthcare compliance implementation"

    logger.debug(f"Researching: {target_name} for issue {issue_index + 1}")
    logger.debug(f"  Query: {query}")

    results = _ydc_search(query, count=3)
    research_text = _format_search_results(results, max_chars=800)

    if not research_text:
        # Fallback query with more generic terms
        fallback_query = f"HIPAA {target_name} security compliance requirements"
        results = _ydc_search(fallback_query, count=2)
        research_text = _format_search_results(results, max_chars=600)

    return ResearchResult(
        issue_index=issue_index,
        target_name=target_name,
        target_type=target_type,
        issue_comment=issue_comment,
        research_text=research_text,
        modification="",  # Will be filled by LLM
        severity=severity,
    )


def _generate_single_modification(
    research: ResearchResult,
    openai_key: str,
) -> Optional[Dict[str, Any]]:
    """
    Generate a modification for a single (issue, component/flow) pair using LLM.

    Uses the web research to inform the modification recommendation.
    """
    prompt = f"""Based on the web research below, generate a specific HIPAA-compliant modification for this component/data flow.

TARGET: {research.target_type.upper()} - {research.target_name}

COMPLIANCE ISSUE:
{research.issue_comment}

WEB RESEARCH:
{research.research_text if research.research_text else "(No specific research found - use your knowledge of HIPAA requirements)"}

Generate a specific, actionable modification that addresses the compliance issue.

INSTRUCTIONS:
1. Specify what EXACT changes are needed for this {research.target_type}
2. Reference specific technologies, standards, and techniques from the web research above
3. Be concrete and actionable - someone should be able to implement this

Return JSON:
{{
  "modification": "Specific modification with technologies and standards from the research",
  "issue_reference": "Brief quote from the compliance issue this addresses"
}}

CRITICAL:
- Use technologies and approaches mentioned in the web research
- Be specific to this {research.target_type} ({research.target_name})
- Keep the modification focused and actionable

Return ONLY the JSON object."""

    try:
        client = OpenAI(api_key=openai_key)
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.1,
            max_tokens=500,
            messages=[
                {"role": "system", "content": "You are a healthcare compliance expert. Generate specific, actionable HIPAA modifications based on web research."},
                {"role": "user", "content": prompt},
            ],
        )

        result_text = (response.choices[0].message.content or "").strip()

        # Strip code fences
        if result_text.startswith("```"):
            result_text = result_text.strip("`")
            if result_text.startswith("json\n"):
                result_text = result_text[len("json\n"):]
            result_text = result_text.strip()

        result = json.loads(result_text)

        if not isinstance(result, dict):
            return None

        # Add target info and severity
        return {
            "target_name": research.target_name,
            "target_type": research.target_type,
            "modification": result.get("modification", ""),
            "issue_reference": result.get("issue_reference", ""),
            "severity": research.severity,
            "issue_index": research.issue_index,
        }

    except Exception as e:
        logger.warning(f"Failed to generate modification for {research.target_name}: {e}")
        return None


def _group_similar_modifications(
    modifications: List[Dict[str, Any]],
    openai_key: str,
) -> List[Dict[str, Any]]:
    """
    Group modifications that are similar across components.

    Uses LLM to identify which modifications are essentially the same
    and should be grouped together.
    """
    if len(modifications) <= 1:
        return modifications

    # Format modifications for grouping analysis
    mod_summaries = []
    for i, mod in enumerate(modifications):
        summary = f"{i}: [{mod['target_type']}] {mod['target_name']} - {mod['modification'][:150]}..."
        mod_summaries.append(summary)

    prompt = f"""Analyze these modifications and identify which ones are essentially the SAME action that should be grouped together.

MODIFICATIONS:
{chr(10).join(mod_summaries)}

Return JSON array of groups. Each group contains indices of modifications that are essentially identical:
{{
  "groups": [[0, 3, 5], [1, 2], [4]]
}}

Rules:
- Only group modifications that require the SAME technical change
- Modifications for different components can be grouped if the change is identical
- If a modification is unique, put it in its own group

Return ONLY the JSON."""

    try:
        client = OpenAI(api_key=openai_key)
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.0,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        result_text = (response.choices[0].message.content or "").strip()

        # Strip code fences
        if result_text.startswith("```"):
            result_text = result_text.strip("`")
            if result_text.startswith("json\n"):
                result_text = result_text[len("json\n"):]
            result_text = result_text.strip()

        result = json.loads(result_text)
        groups = result.get("groups", [])

        if not groups:
            return modifications

        # Build grouped modifications
        grouped = []
        for group_indices in groups:
            if not group_indices:
                continue

            # Use first modification as the base
            base_mod = modifications[group_indices[0]]

            if len(group_indices) > 1:
                # Collect all target names in this group
                target_names = [modifications[i]["target_name"] for i in group_indices if i < len(modifications)]
                grouped_note = f"[Applies to: {', '.join(target_names)}]\n\n"

                # Create one entry per target but with the grouped note
                for idx in group_indices:
                    if idx < len(modifications):
                        mod = modifications[idx]
                        grouped.append({
                            **mod,
                            "modification": grouped_note + mod["modification"],
                        })
            else:
                grouped.append(base_mod)

        return grouped

    except Exception as e:
        logger.warning(f"Failed to group modifications: {e}")
        return modifications


def generate_component_modifications(
    review_comments: List[Dict[str, Any]],
    components: List[Dict[str, Any]],
    data_flows: List[Dict[str, Any]],
    status: Optional[StatusEmitter] = None,
) -> List[Dict[str, Any]]:
    """
    Generate modifications by researching each (issue, component/flow) pair.

    Workflow:
    1. For each issue:
       - For each component/data flow, research what modifications are needed
       - Use You.com with component details + issue action + HIPAA context
    2. Use LLM to synthesize research into specific modifications
    3. Group similar modifications across components

    Returns list of modifications with grouped targets.
    """
    openai_key = os.getenv("OPENAI_API_KEY")
    ydc_key = _get_ydc_api_key()

    if not openai_key:
        logger.error("OPENAI_API_KEY not set")
        if status:
            status.error("OpenAI API key not configured")
        return []

    if not review_comments:
        logger.warning("No review comments provided")
        return []

    if not components and not data_flows:
        logger.warning("No components or data flows provided")
        return []

    # Build lookup maps for components and data flows (case-insensitive)
    component_map = {}
    component_names_lower = {}
    for comp in components:
        name = comp.get("name", "")
        if name:
            component_map[name] = comp
            component_names_lower[name.lower()] = name

    flow_map = {}
    flow_names_lower = {}
    for flow in data_flows:
        flow_name = flow.get("name", "") or f"{flow.get('source', '?')} -> {flow.get('target', '?')}"
        flow_map[flow_name] = flow
        # Normalize to use -> for case-insensitive matching
        normalized_lower = flow_name.lower().replace("→", "->")
        flow_names_lower[normalized_lower] = flow_name

    logger.info(f"Available components: {list(component_map.keys())}")
    logger.info(f"Available data flows: {list(flow_map.keys())}")

    if status:
        status.step("Researching modifications for affected components")

    def find_matching_component(item_name: str) -> Optional[str]:
        """Find a matching component name (case-insensitive, with partial matching)."""
        # Exact match
        if item_name in component_map:
            return item_name
        # Case-insensitive match
        lower_name = item_name.lower()
        if lower_name in component_names_lower:
            return component_names_lower[lower_name]
        # Partial match (item_name is substring of component name or vice versa)
        for comp_lower, comp_original in component_names_lower.items():
            if lower_name in comp_lower or comp_lower in lower_name:
                return comp_original
        return None

    def find_matching_flow(item_name: str) -> Optional[str]:
        """Find a matching data flow name (case-insensitive, with partial matching)."""
        # Normalize arrows: convert → to -> for consistent matching
        normalized_name = item_name.replace("→", "->")

        # Exact match
        if item_name in flow_map:
            return item_name
        if normalized_name in flow_map:
            return normalized_name

        # Case-insensitive match
        lower_name = normalized_name.lower()
        if lower_name in flow_names_lower:
            return flow_names_lower[lower_name]

        # Partial match (check source and target separately)
        for flow_lower, flow_original in flow_names_lower.items():
            if lower_name in flow_lower or flow_lower in lower_name:
                return flow_original
            # Also try matching just the source or target parts
            if "->" in lower_name and "->" in flow_lower:
                item_parts = [p.strip() for p in lower_name.split("->")]
                flow_parts = [p.strip() for p in flow_lower.split("->")]
                if (item_parts[0] in flow_parts[0] or flow_parts[0] in item_parts[0]) and \
                   (item_parts[1] in flow_parts[1] or flow_parts[1] in item_parts[1]):
                    return flow_original
        return None

    # Step 1: Build research tasks ONLY for components/flows mentioned in related_components
    research_tasks = []
    unmatched_items = []

    for i, issue in enumerate(review_comments[:8]):  # Cap at 8 issues
        related = issue.get("related_components", [])
        if not related:
            logger.debug(f"Issue {i} has no related_components, skipping")
            continue

        logger.info(f"Issue {i} related_components: {related}")

        for item_name in related:
            # Check if it's a data flow (contains → or ->) or a component
            is_data_flow = "→" in item_name or "->" in item_name
            if is_data_flow:
                matched_flow = find_matching_flow(item_name)
                if matched_flow:
                    research_tasks.append((i, issue, matched_flow, "data_flow"))
                else:
                    unmatched_items.append(item_name)
            else:
                matched_comp = find_matching_component(item_name)
                if matched_comp:
                    research_tasks.append((i, issue, matched_comp, "component"))
                else:
                    unmatched_items.append(item_name)

    if unmatched_items:
        logger.warning(f"Could not match these items to components/flows: {unmatched_items}")

    if not research_tasks:
        logger.warning("No components/flows found in related_components")
        if status:
            status.warning("No specific components or data flows to modify")
        return []

    if status:
        status.info(f"Found {len(research_tasks)} (issue, component/flow) pairs to analyze")

    # Step 1: Research each (issue, component/flow) pair
    research_results: List[ResearchResult] = []

    if ydc_key:

        if status:
            status.info(f"Running {len(research_tasks)} research queries...")

        # Execute research in parallel
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {}
            for task in research_tasks:
                issue_idx, issue, target_name, target_type = task
                future = executor.submit(
                    _research_issue_component_pair,
                    issue_idx, issue, target_name, target_type
                )
                futures[future] = (issue_idx, issue, target_name, target_type)

            completed = 0
            research_with_text = 0
            for future in as_completed(futures):
                issue_idx, issue, target_name, target_type = futures[future]
                try:
                    result = future.result()
                    if result:
                        research_results.append(result)
                        if result.research_text:
                            research_with_text += 1
                            if status and research_with_text <= 3:
                                status.detail(f"Found research for {target_name}")
                except Exception as e:
                    # YDC failed - still add result without research so LLM can use its knowledge
                    logger.warning(f"Research failed for {target_name}: {e}")
                    research_results.append(ResearchResult(
                        issue_index=issue_idx,
                        target_name=target_name,
                        target_type=target_type,
                        issue_comment=issue.get("comment", ""),
                        research_text="",
                        modification="",
                        severity=issue.get("severity", "medium"),
                    ))
                completed += 1

        if status:
            if research_with_text > 0:
                status.success(f"Found web research for {research_with_text}/{len(research_results)} pairs")
            else:
                status.warning("Web research unavailable - using LLM knowledge only")
    else:
        if status:
            status.warning("No YDC_API_KEY - using LLM knowledge only")

        # Build research results without web search using the filtered research_tasks
        for issue_idx, issue, target_name, target_type in research_tasks:
            research_results.append(ResearchResult(
                issue_index=issue_idx,
                target_name=target_name,
                target_type=target_type,
                issue_comment=issue.get("comment", ""),
                research_text="",
                modification="",
                severity=issue.get("severity", "medium"),
            ))

    # Step 2: Generate modifications individually per research result using LLM
    if status:
        status.step("Generating modifications for each component")
        status.info(f"Processing {len(research_results)} (issue, component) pairs...")

    raw_modifications: List[Dict[str, Any]] = []

    # Execute LLM calls in parallel for each research result
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}
        for research in research_results:
            future = executor.submit(_generate_single_modification, research, openai_key)
            futures[future] = research.target_name

        completed = 0
        for future in as_completed(futures):
            target_name = futures[future]
            try:
                result = future.result()
                if result and result.get("modification"):
                    raw_modifications.append(result)
                    if status and completed < 3:
                        status.detail(f"Generated modification for {target_name}")
            except Exception as e:
                logger.warning(f"Modification generation failed for {target_name}: {e}")
            completed += 1

    if not raw_modifications:
        logger.warning("No modifications generated")
        return []

    logger.info(f"Generated {len(raw_modifications)} raw modifications")

    if status:
        status.success(f"Generated {len(raw_modifications)} modifications")

    # Step 3: Group similar modifications across components
    if status:
        status.step("Grouping similar modifications")

    final_modifications = _group_similar_modifications(raw_modifications, openai_key)

    logger.info(f"After grouping: {len(final_modifications)} modifications")

    if status:
        status.detail(f"Created {len(final_modifications)} modification entries")
        for mod in final_modifications[:3]:
            status.detail(f"→ {mod['target_name']}: {mod['modification'][:50]}...")

    return final_modifications[:15]  # Cap at 15
