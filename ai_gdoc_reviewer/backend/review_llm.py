import os
import json
import logging
import time
from typing import Optional, Literal, Dict, Any, List

from openai import OpenAI
from schemas import ReviewResponse
from web_research import research_hipaa_regulations, format_regulations_for_review_prompt
import re

# Configure logging
logger = logging.getLogger("review_llm")

ReviewMode = Literal["general", "privacy"]

SYSTEM_PRIVACY = """You are a HIPAA compliance reviewer for AI systems. You write precise, consequence-aware review comments.

COMMENT FORMAT - Every comment MUST follow this structure:
"Since you're doing [X], you should be aware of [regulation Y] which [description]. Violations can result in [fine range]. [Action to take]."

Where:
- X = What the system is doing (from the selected text)
- Y = The specific HIPAA regulation section (e.g., § 164.312)
- Description = What the regulation requires (in plain language)
- Fine range = How severe the penalties can be (e.g., "fines up to $1.5M per violation")
- Action = Specific technical action to comply

CRITICAL RULES:
1. Describe what the regulation REQUIRES, not specific enforcement cases.
2. Mention the potential fine RANGE (e.g., "up to $50K per violation" or "fines ranging from $100 to $50K").
3. Be specific about what the system is doing that triggers each regulation.
4. Recommend specific technical actions from the research.

OUTPUT QUALITY RULES:
5. Every comment MUST be a complete, self-contained thought. Never leave a sentence or point unfinished.
6. Keep comments concise (2-4 sentences). Finish every sentence.
7. Write in plain, professional language as if advising a colleague.

You must:
- Anchor every comment to an EXACT substring from the Selected Text.
- Follow the "Since you're doing X... regulation Y which [requires]... fines up to [amount]... Do [action]" format.
- Do NOT include specific company names or enforcement case anecdotes.
- Output JSON only.
"""

USER_TMPL_PRIVACY = """============================================================
FULL DOCUMENT ARCHITECTURE
============================================================
Title: {doc_title}

{document_structure}

============================================================
HIPAA REGULATIONS (from web research)
============================================================
{hipaa_regulations}

============================================================
SELECTED TEXT (user-highlighted)
============================================================
{selection}

============================================================
INSTRUCTIONS
============================================================

You have FULL CONTEXT of the document architecture above. Use this to understand where the selected text fits in the overall system design.

For each comment, you MUST follow this format:
"Since you're doing [X], you should be aware of [regulation Y] which [description]. Violations can result in [fine range]. [Action to take]."

REQUIRED ELEMENTS IN EACH COMMENT:

1. WHAT THEY'RE DOING (X)
   - Be specific about what activity in the selected text triggers the regulation
   - Reference the document architecture to explain the context
   - Example: "storing patient vitals in the Analytics Database"

2. THE REGULATION (Y) + DESCRIPTION
   - Cite the specific HIPAA section from the research above
   - Describe what it requires in plain language
   - Example: "§ 164.312(a)(1) which requires unique user identification for PHI access"

3. THE FINE RANGE
   - State how severe the penalties can be
   - Use ranges, not specific cases
   - Example: "fines up to $1.5M per violation category"

4. THE ACTION
   - Specific technical action to comply (from the research)
   - Example: "Implement role-based access with automatic session timeouts"

EXAMPLE COMMENT:
"Since you're storing patient vitals in your Analytics Database without mentioning access controls, you should be aware of § 164.312(a)(1) which requires unique user identification for all PHI access. Violations can result in fines up to $50,000 per incident. Implement role-based access control with automatic session timeouts and audit logging."

============================================================
OUTPUT FORMAT
============================================================
Return JSON only:

{{
  "inline_comments": [
    {{
      "target_quote": "EXACT substring from SELECTED TEXT",
      "severity": "low|medium|high",
      "comment": "Since you're doing [X], you should be aware of [regulation Y] which [description]. Violations can result in [fine range]. [Action to take]."
    }}
  ]
}}

Constraints:
- Produce 3 to 8 comments
- Every comment MUST follow the "Since you're doing X... regulation Y which [requires]... fines [range]... Action" format
- Do NOT include specific company names or enforcement case anecdotes
- Every target_quote must appear VERBATIM in SELECTED TEXT
- Reference specific components or data flows from the architecture
- If no regulations were found, return empty list
"""

def _strip_code_fences(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json\n"):
            s = s[len("json\n") :]
    return s.strip()

def _extract_citations_from_comment(comment: str) -> List[str]:
    """Extract regulation citations (e.g., § 160.102, 160.504) from a comment."""
    # Match patterns like § 160.102, §160.102, 160.102, § 160.102(a), etc.
    patterns = [
        r'§\s*(\d{3}\.\d{3}(?:\([a-z0-9]+\))?)',  # § 160.102 or § 160.102(a)
        r'(?<![0-9])(\d{3}\.\d{3})(?:\([a-z0-9]+\))?(?![0-9])',  # 160.102 standalone
    ]
    citations = []
    for pattern in patterns:
        matches = re.findall(pattern, comment, re.IGNORECASE)
        citations.extend(matches)
    # Normalize to just the section number (e.g., 160.102)
    normalized = []
    for c in citations:
        # Extract just the base section number
        match = re.match(r'(\d{3}\.\d{3})', c)
        if match:
            normalized.append(match.group(1))
    return list(set(normalized))


def _validate_citations(comments: List[Dict[str, Any]], provided_sections: List[str]) -> None:
    """
    Validate that all citations in comments reference regulations that were provided.
    Logs warnings for any ungrounded citations.
    """
    provided_set = set(provided_sections)

    for i, comment in enumerate(comments):
        comment_text = comment.get("comment", "")
        cited_sections = _extract_citations_from_comment(comment_text)

        for section in cited_sections:
            if section not in provided_set:
                logger.warning(
                    f"GROUNDING ISSUE: Comment {i+1} cites § {section} which was NOT in provided regulations. "
                    f"Provided sections: {provided_sections}"
                )
            else:
                logger.debug(f"Citation validated: § {section} is in provided regulations")


def _format_sanity_structure(
    components: List[Dict[str, Any]],
    data_flows: List[Dict[str, Any]],
) -> str:
    """
    Format Sanity component and data flow documents into a readable string for the LLM prompt.
    """
    parts = []

    # Format components
    if components:
        parts.append("### Technical Components")
        for comp in components:
            name = comp.get("name", "Unknown")
            ctype = comp.get("componentType", comp.get("component_type", ""))
            desc = comp.get("description", "")[:150]  # Tech stack is now in description

            # Check for PHI/PII in dataHandled
            data_handled = comp.get("dataHandled", [])
            has_phi = any(d.get("isPHI") for d in data_handled if isinstance(d, dict))
            has_pii = any(d.get("isPII") for d in data_handled if isinstance(d, dict))
            phi = "⚠️ Handles PHI" if has_phi else ""
            pii = "⚠️ Handles PII" if has_pii else ""
            flags = " ".join(filter(None, [phi, pii]))

            line = f"- **{name}** ({ctype})"
            if flags:
                line += f" [{flags}]"
            parts.append(line)
            if desc:
                parts.append(f"  {desc}")

    # Format data flows
    if data_flows:
        parts.append("\n### Data Flows")
        for flow in data_flows:
            # Handle both Sanity reference format and direct name format
            name = flow.get("name", "")
            if " -> " in name:
                source, target = name.split(" -> ", 1)
            else:
                source = flow.get("source", "?")
                target = flow.get("target", "?")

            data_types = flow.get("dataTypes", [])
            dt_names = [d.get("dataType", d) if isinstance(d, dict) else str(d) for d in data_types[:3]]

            # Check encryption status
            encryption = flow.get("encryption", {})
            encrypted = encryption.get("inTransit", False) if isinstance(encryption, dict) else False
            enc_flag = "🔒 Encrypted" if encrypted else ""

            line = f"- {source} → {target}"
            if dt_names:
                line += f": {', '.join(dt_names)}"
            if enc_flag:
                line += f" [{enc_flag}]"
            parts.append(line)

    if not parts:
        return "No document structure available."

    # Add summary
    summary_parts = []
    if components:
        phi_components = [c.get("name") for c in components
                        if any(d.get("isPHI") for d in c.get("dataHandled", []) if isinstance(d, dict))]
        if phi_components:
            summary_parts.append(f"PHI handling: {', '.join(phi_components[:3])}")

    if summary_parts:
        parts.append(f"\n### Summary\n{'; '.join(summary_parts)}")

    return "\n".join(parts)

def run_review(
    selection: str,
    mode: ReviewMode = "general",
    doc_title: str = "",
    doc_text: Optional[str] = None,
    google_doc_id: Optional[str] = None,
) -> ReviewResponse:
    """
    Runs an LLM review on the highlighted selection.

    mode="general": your original behavior
    mode="privacy": privacy-only review that uses full document structure for context

    Args:
        selection: The highlighted text to review
        mode: Review mode ("general" or "privacy")
        doc_title: Document title
        doc_text: Full document text - if provided, the document structure will be
                  parsed to give the reviewer full architectural context
        google_doc_id: Google Doc ID - used to persist/reuse document graph in Sanity
    """
    start_time = time.time()
    selection = (selection or "").strip()

    logger.info(f"=== Starting review request ===")
    logger.info(f"Mode: {mode}")
    logger.info(f"Selection length: {len(selection)} chars")
    logger.info(f"Full document provided: {'yes' if doc_text else 'no'}")
    logger.info(f"Google Doc ID: {google_doc_id or '(not provided)'}")
    logger.debug(f"Selection preview: {selection[:200]}..." if len(selection) > 200 else f"Selection: {selection}")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    logger.info(f"Using model: {model}")

    # Track provided regulation sections for validation
    provided_regulation_sections: List[str] = []

    # Track parsed structure to return to caller (for passing to apply phase)
    parsed_components: Optional[List[Dict[str, Any]]] = None
    parsed_data_flows: Optional[List[Dict[str, Any]]] = None

    if mode == "privacy":
        # Parse document structure for LLM context (no Sanity persistence during review)
        document_structure_str = ""

        if doc_text and len(doc_text.strip()) > 100:
            logger.info("--- Parsing Document Structure (no Sanity persistence) ---")
            parse_start = time.time()
            try:
                # Import here to avoid circular imports
                from document_orchestrator import DocumentGraphOrchestrator

                orchestrator = DocumentGraphOrchestrator()
                # Use parse_document_structure instead of get_or_create_design_document
                # This avoids creating orphaned documents in Sanity during review phase
                doc_result = orchestrator.parse_document_structure(doc_text)

                components = doc_result.get("components", [])
                data_flows = doc_result.get("data_flows", [])

                # Store for returning to caller (Chrome extension will pass back during apply)
                parsed_components = components
                parsed_data_flows = data_flows

                document_structure_str = _format_sanity_structure(components, data_flows)
                parse_elapsed = (time.time() - parse_start) * 1000
                logger.info(f"Document structure parsed in {parse_elapsed:.1f}ms")
                logger.info(f"  Components: {len(components)}")
                logger.info(f"  Data flows: {len(data_flows)}")
            except Exception as e:
                logger.warning(f"Failed to parse document structure: {e}")
                document_structure_str = "Document structure could not be parsed. Review based on selected text only."
        else:
            document_structure_str = "Full document not provided. Review based on selected text only."
            logger.info("No full document provided - reviewing selection only")

        # Research HIPAA regulations using You.com web search
        logger.info(f"--- Researching HIPAA Regulations via Web ---")
        reg_start = time.time()
        regulation_research = research_hipaa_regulations(
            selection=selection,
            components=parsed_components,
            data_flows=parsed_data_flows,
            max_regulations=5,
        )
        reg_elapsed = (time.time() - reg_start) * 1000
        logger.info(f"Regulation research completed in {reg_elapsed:.1f}ms")

        # Track which sections we're providing to the LLM
        regulations = regulation_research.get("regulations", [])
        provided_regulation_sections = [reg.get("regulation", "") for reg in regulations]

        logger.info(f"Found {len(regulations)} relevant regulations")
        for reg in regulations:
            logger.info(f"  - {reg.get('regulation', 'Unknown')}")
            logger.info(f"    Requires: {reg.get('description', '')[:100]}...")

        hipaa_context = format_regulations_for_review_prompt(regulation_research)
        logger.debug(f"HIPAA context for prompt ({len(hipaa_context)} chars):\n{hipaa_context[:500]}...")

        system = SYSTEM_PRIVACY
        user = USER_TMPL_PRIVACY.format(
            doc_title=doc_title or "Untitled Document",
            document_structure=document_structure_str,
            hipaa_regulations=hipaa_context,
            selection=selection,
        )

    # Log prompt sizes
    logger.info(f"--- LLM Request ---")
    logger.info(f"System prompt: {len(system)} chars")
    logger.info(f"User prompt: {len(user)} chars")
    logger.info(f"Total prompt size: {len(system) + len(user)} chars")

    llm_start = time.time()
    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    llm_elapsed = (time.time() - llm_start) * 1000

    text = resp.choices[0].message.content or ""
    logger.info(f"--- LLM Response ---")
    logger.info(f"LLM call completed in {llm_elapsed:.1f}ms")
    logger.info(f"Response length: {len(text)} chars")
    if hasattr(resp, 'usage') and resp.usage:
        logger.info(f"Token usage - prompt: {resp.usage.prompt_tokens}, completion: {resp.usage.completion_tokens}, total: {resp.usage.total_tokens}")

    text = _strip_code_fences(text)
    logger.debug(f"Parsed response: {text[:500]}..." if len(text) > 500 else f"Parsed response: {text}")

    data = json.loads(text)

    # Extra guard (optional but useful): ensure privacy mode returns privacy-only types
    if mode == "privacy":
        for c in data.get("inline_comments", []):
            c["type"] = "privacy"

    comments = data.get("inline_comments", [])
    total_elapsed = (time.time() - start_time) * 1000

    logger.info(f"--- Review Complete ---")
    logger.info(f"Generated {len(comments)} comments")
    for i, c in enumerate(comments):
        comment_preview = c.get('comment', '')[:100]
        logger.info(f"  Comment {i+1}: severity={c.get('severity')}")
        logger.info(f"    quote: '{c.get('target_quote', '')[:50]}...'")
        logger.info(f"    comment: '{comment_preview}...'")

    # Validate citations against provided regulations
    if mode == "privacy" and provided_regulation_sections:
        logger.info(f"--- Citation Validation ---")
        _validate_citations(comments, provided_regulation_sections)

    logger.info(f"Total review time: {total_elapsed:.1f}ms")

    # Add parsed structure to response (for passing to apply phase)
    if parsed_components is not None:
        data["parsed_components"] = parsed_components
    if parsed_data_flows is not None:
        data["parsed_data_flows"] = parsed_data_flows

    return ReviewResponse.model_validate(data)


def run_review_with_status(
    selection: str,
    mode: ReviewMode = "general",
    doc_title: str = "",
    doc_text: Optional[str] = None,
    google_doc_id: Optional[str] = None,
    status: Optional["StatusEmitter"] = None,
) -> ReviewResponse:
    """
    Runs an LLM review with status updates for the frontend.

    Same as run_review but emits status updates to the StatusEmitter
    for real-time progress display.
    """
    from status_stream import StatusEmitter

    # Create a no-op emitter if none provided
    if status is None:
        status = StatusEmitter()

    start_time = time.time()
    selection = (selection or "").strip()

    status.step("Starting privacy review")

    logger.info(f"=== Starting review request ===")
    logger.info(f"Mode: {mode}")
    logger.info(f"Selection length: {len(selection)} chars")
    logger.info(f"Full document provided: {'yes' if doc_text else 'no'}")
    logger.info(f"Google Doc ID: {google_doc_id or '(not provided)'}")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Track provided regulation sections for validation
    provided_regulation_sections: List[str] = []

    # Track parsed structure to return to caller (for passing to apply phase)
    parsed_components: Optional[List[Dict[str, Any]]] = None
    parsed_data_flows: Optional[List[Dict[str, Any]]] = None

    if mode == "privacy":
        # Parse document structure for LLM context (no Sanity persistence during review)
        document_structure_str = ""

        if doc_text and len(doc_text.strip()) > 100:
            status.step("Synthesizing where selected sections fit into overall design")

            parse_start = time.time()
            try:
                from document_orchestrator import DocumentGraphOrchestrator

                orchestrator = DocumentGraphOrchestrator()
                doc_result = orchestrator.parse_document_structure(doc_text)

                components = doc_result.get("components", [])
                data_flows = doc_result.get("data_flows", [])

                # Store for returning to caller
                parsed_components = components
                parsed_data_flows = data_flows

                document_structure_str = _format_sanity_structure(components, data_flows)
                parse_elapsed = (time.time() - parse_start) * 1000

                # Emit component and data flow details
                if components:
                    comp_names = [c.get("name", "Unknown") for c in components[:5]]
                    status.info(
                        f"Found {len(components)} technical components",
                        {"components": comp_names}
                    )
                    status.detail(f"Components: {', '.join(comp_names)}")

                if data_flows:
                    flow_names = [f.get("name", "Unknown") for f in data_flows[:3]]
                    status.info(
                        f"Found {len(data_flows)} data flows",
                        {"data_flows": flow_names}
                    )

            except Exception as e:
                logger.warning(f"Failed to parse document structure: {e}")
                status.warning("Could not parse document structure")
                document_structure_str = "Document structure could not be parsed. Review based on selected text only."
        else:
            document_structure_str = "Full document not provided. Review based on selected text only."
            status.info("Reviewing selection without full document context")

        # Research HIPAA regulations using You.com web search
        status.step("Researching relevant HIPAA regulations")

        reg_start = time.time()
        regulation_research = research_hipaa_regulations(
            selection=selection,
            components=parsed_components,
            data_flows=parsed_data_flows,
            max_regulations=5,
        )
        reg_elapsed = (time.time() - reg_start) * 1000

        # Track which sections we're providing to the LLM
        regulations = regulation_research.get("regulations", [])
        provided_regulation_sections = [reg.get("regulation", "") for reg in regulations]

        if regulations:
            status.info(
                f"Found {len(regulations)} relevant regulations",
                {"regulations": provided_regulation_sections}
            )
            # Show a regulation preview
            for reg in regulations[:2]:
                description = reg.get("description", "")[:60]
                status.detail(f"{reg.get('regulation', '')}: {description}...")
        else:
            status.warning("No relevant regulations found")

        hipaa_context = format_regulations_for_review_prompt(regulation_research)

        system = SYSTEM_PRIVACY
        user = USER_TMPL_PRIVACY.format(
            doc_title=doc_title or "Untitled Document",
            document_structure=document_structure_str,
            hipaa_regulations=hipaa_context,
            selection=selection,
        )

    # Generate review comments
    status.step("Generating compliance review comments")

    llm_start = time.time()
    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    llm_elapsed = (time.time() - llm_start) * 1000

    text = resp.choices[0].message.content or ""
    text = _strip_code_fences(text)

    data = json.loads(text)

    # Extra guard: ensure privacy mode returns privacy-only types
    if mode == "privacy":
        for c in data.get("inline_comments", []):
            c["type"] = "privacy"

    comments = data.get("inline_comments", [])
    total_elapsed = (time.time() - start_time) * 1000

    # Emit comment summary
    if comments:
        high_count = sum(1 for c in comments if c.get("severity") == "high")
        medium_count = sum(1 for c in comments if c.get("severity") == "medium")
        low_count = sum(1 for c in comments if c.get("severity") == "low")

        status.success(
            f"Generated {len(comments)} review comments",
            {
                "total": len(comments),
                "high": high_count,
                "medium": medium_count,
                "low": low_count,
            }
        )

        # Show preview of first comment
        if comments[0].get("comment"):
            preview = comments[0]["comment"][:80] + "..." if len(comments[0]["comment"]) > 80 else comments[0]["comment"]
            status.detail(f"First comment: {preview}")
    else:
        status.info("No privacy issues found in selection")

    # Validate citations against provided regulations
    if mode == "privacy" and provided_regulation_sections:
        _validate_citations(comments, provided_regulation_sections)

    status.complete(f"Review complete in {total_elapsed/1000:.1f}s")

    # Add parsed structure to response
    if parsed_components is not None:
        data["parsed_components"] = parsed_components
    if parsed_data_flows is not None:
        data["parsed_data_flows"] = parsed_data_flows

    return ReviewResponse.model_validate(data)
