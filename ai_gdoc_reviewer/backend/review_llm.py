import os
import json
from typing import Optional, Literal, Dict, Any

from openai import OpenAI
from schemas import ReviewResponse

ReviewMode = Literal["general", "privacy"]

SYSTEM_GENERAL = """You are an expert reviewer for AI governance and EU AI Act readiness.

Leave short, actionable Google Doc comments.

Rules:
- Do not invent facts not present in the text.
- target_quote MUST be copied exactly from the provided text (verbatim substring).
- Prefer 3–8 comments per selection.
- Focus on lineage, provenance, transformation intent, bias, privacy, monitoring, accountability.
- Output JSON only matching schema.
"""

SYSTEM_PRIVACY = """You are a privacy reviewer for AI systems.

You write concise, actionable review comments for Google Docs.

You will be given:
(1) a Document Context Pack (high-level context for the whole document)
(2) a Selected Text block (the text the user highlighted)

You must:
- Focus ONLY on privacy-related risks and mitigations.
- Anchor every comment to an EXACT substring from Selected Text via target_quote.
- Do not invent details that are not present in the Context Pack or Selected Text.
- Prefer comments that lead to concrete design/test/deployment/ops actions.
- Output JSON only matching schema.
"""

USER_TMPL_GENERAL = """Review the following selected text from a Google Doc:

--- START SELECTION ---
{selection}
--- END SELECTION ---

Return JSON only:

{{
  "inline_comments": [
    {{
      "target_quote": "EXACT substring from selection",
      "type": "governance|compliance|privacy|bias|risk|clarity|logic|missing_context|question|rewrite|structure",
      "severity": "low|medium|high",
      "comment": "Short actionable comment",
      "rewrite_suggestion": "Optional"
    }}
  ]
}}
"""

USER_TMPL_PRIVACY = """DOCUMENT CONTEXT PACK (whole-doc context)
Title: {doc_title}

Summary (<=400 words):
{doc_summary}

System & deployment context:
- Intended use: {intended_use}
- Users/roles: {users_roles}
- Environment: {environment}
- Data sources: {data_sources}
- Storage & retention: {storage_retention}
- Vendors/services: {vendors}
- Compliance constraints mentioned: {compliance}

Privacy signals already mentioned in the doc:
{privacy_signals}

---
SELECTED TEXT (user-highlighted)
{selection}

---
PRIVACY REVIEW RUBRIC (follow this)
Ask yourself:
How will privacy be built into the AI system design, testing, deployment, and operation?
If data includes sensitive or personally identifiable information including biometrics,
what extra precautions will be taken?

Use these actions to guide your comments:
1) Identify privacy-related values, frameworks, and attributes applicable to this context of use.
2) Quantify privacy-level data aspects where possible:
   - ability to identify individuals or groups
   - k-anonymity, l-diversity, t-closeness
   - if not measurable from this text, state what should be measured and where
3) Establish and document protocols and access controls:
   - authorization, duration, and data types
   - training vs production data handling
   - align to privacy/data governance policies
4) Use privacy-enhancing techniques when sharing dataset information:
   - differential privacy, aggregation, redaction
   - define the release policy and threat model

---
OUTPUT REQUIREMENTS
Return JSON only with this schema:

{{
  "inline_comments": [
    {{
      "target_quote": "EXACT substring from SELECTED TEXT",
      "type": "privacy",
      "severity": "low|medium|high",
      "comment": "Actionable privacy review comment",
      "rewrite_suggestion": "Optional suggested rewrite of the selected text"
    }}
  ]
}}

Constraints:
- Produce 3 to 8 comments.
- Every target_quote must appear verbatim in SELECTED TEXT.
- If the selected text contains no privacy-relevant content, return an empty list.
"""

def _strip_code_fences(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json\n"):
            s = s[len("json\n") :]
    return s.strip()

def _default_context_pack(doc_title: str = "") -> Dict[str, Any]:
    """
    Safe defaults so the caller can omit context_pack without breaking prompts.
    """
    return {
        "doc_title": doc_title or "Untitled document",
        "doc_summary": "Context not provided. Infer only from the selected text.",
        "intended_use": "Unknown",
        "users_roles": "Unknown",
        "environment": "Unknown",
        "data_sources": "Unknown",
        "storage_retention": "Unknown",
        "vendors": "Unknown",
        "compliance": "Unknown",
        "privacy_signals": "None explicitly mentioned in context pack.",
    }

def run_review(
    selection: str,
    mode: ReviewMode = "general",
    context_pack: Optional[Dict[str, Any]] = None,
    doc_title: str = "",
) -> ReviewResponse:
    """
    Runs an LLM review on the highlighted selection.

    mode="general": your original behavior
    mode="privacy": privacy-only review that follows the rubric and uses doc context
    """
    selection = (selection or "").strip()

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    if mode == "privacy":
        ctx = _default_context_pack(doc_title=doc_title)
        if context_pack:
            # merge user-provided context over defaults
            ctx.update({k: v for k, v in context_pack.items() if v is not None})

        system = SYSTEM_PRIVACY
        user = USER_TMPL_PRIVACY.format(
            doc_title=ctx["doc_title"],
            doc_summary=ctx["doc_summary"],
            intended_use=ctx["intended_use"],
            users_roles=ctx["users_roles"],
            environment=ctx["environment"],
            data_sources=ctx["data_sources"],
            storage_retention=ctx["storage_retention"],
            vendors=ctx["vendors"],
            compliance=ctx["compliance"],
            privacy_signals=ctx["privacy_signals"],
            selection=selection,
        )
    else:
        system = SYSTEM_GENERAL
        user = USER_TMPL_GENERAL.format(selection=selection)

    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    text = resp.choices[0].message.content or ""
    text = _strip_code_fences(text)

    data = json.loads(text)

    # Extra guard (optional but useful): ensure privacy mode returns privacy-only types
    if mode == "privacy":
        for c in data.get("inline_comments", []):
            c["type"] = "privacy"

    return ReviewResponse.model_validate(data)

