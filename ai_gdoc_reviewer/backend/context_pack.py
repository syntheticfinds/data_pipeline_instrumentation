import os
import json
from typing import Any, Dict, Optional

from openai import OpenAI


CONTEXT_PACK_SYSTEM = """You extract a compact context pack for privacy reviews of AI system design docs.

You will be given raw document text. Produce a concise, structured context pack that helps a downstream
privacy reviewer understand context of use and applicable privacy frameworks.

Rules:
- Do not invent facts not present in the document.
- If a field is unknown, set it to "Unknown".
- Keep doc_summary <= 400 words.
- Output JSON only.
"""


CONTEXT_PACK_USER_TMPL = """You are building a "Document Context Pack" for privacy review.

Document Title:
{doc_title}

Document Text:
--- START DOC ---
{doc_text}
--- END DOC ---

Return JSON only in this exact format:

{{
  "doc_title": "{doc_title}",
  "doc_summary": "<=400 words summary focusing on AI system purpose + data handling",
  "intended_use": "What the system is used for",
  "users_roles": "Primary users/roles",
  "environment": "Where it runs (hospital/consumer app/cloud/on-device/etc.)",
  "data_sources": "What data sources are used (EHR notes, logs, user profiles, etc.)",
  "data_types": "Sensitive data types present or implied (PII/PHI/biometrics/etc.)",
  "storage_retention": "Storage locations and retention duration (if stated)",
  "vendors": "External vendors/services mentioned (LLM provider, cloud services, etc.)",
  "compliance": "Mentioned compliance constraints (HIPAA/GDPR/EU AI Act/etc.)",
  "privacy_signals": "Explicit privacy controls already mentioned (RBAC, encryption, audit logs, minimization, etc.)",
  "threats": "Key privacy risks suggested by the text (re-identification, overexposure, retention, access creep, etc.)",
  "open_questions": "Privacy questions the doc fails to answer but should"
}}
"""


def _strip_code_fences(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json\n"):
            s = s[len("json\n") :]
    return s.strip()


def build_context_pack(
    doc_text: str,
    doc_title: str = "",
    model: Optional[str] = None,
    max_chars: int = 12000,
) -> Dict[str, Any]:
    """
    Build a lightweight context pack from the full document text.

    Notes:
    - max_chars prevents huge prompt payloads for MVP.
    - You can later upgrade to chunked summarization for very long docs.
    """
    doc_text = (doc_text or "").strip()
    doc_title = (doc_title or "").strip() or "Untitled document"

    # Trim for MVP to control cost/latency
    trimmed = doc_text[:max_chars]

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    resp = client.chat.completions.create(
        model=model,
        temperature=0.0,
        messages=[
            {"role": "system", "content": CONTEXT_PACK_SYSTEM},
            {"role": "user", "content": CONTEXT_PACK_USER_TMPL.format(doc_title=doc_title, doc_text=trimmed)},
        ],
    )

    text = resp.choices[0].message.content or ""
    text = _strip_code_fences(text)

    data = json.loads(text)

    # Minimal normalization for safety
    data.setdefault("doc_title", doc_title)
    return data
