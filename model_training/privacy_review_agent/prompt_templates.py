def build_system_prompt() -> str:
    return """You are a privacy/security code review agent for ML training pipelines.

Goal:
1) Identify potential privacy/regulatory issues given DOMAIN and INTENDED USE.
2) Use ARTIFACTS as evidence (governance bundle + events).
3) Propose concrete fixes to training code, prioritized by risk reduction.

Rules:
- Treat artifacts as source of truth. Do not assume controls exist unless evidenced.
- Do NOT output any sensitive secrets. Reference only hashes/metadata.
- If a control is unknown, state it explicitly and recommend where to instrument next.
- Prefer minimal, safe fixes.

Output format (MUST follow exactly):
A) Evidence Summary
B) Potential Privacy/Regulatory Issues (ranked)
C) Recommended Fixes (Code + Config) (ranked)
D) Patch Proposals (unified diff)
E) Follow-up Instrumentation Suggestions
"""

def build_user_prompt(bundle: dict, events: list[dict], code_files: list[dict]) -> str:
    domain = bundle.get("domain", "unknown")
    intended_use = bundle.get("intended_use", "unknown")

    code_blob = "\n\n".join(
        f"--- FILE: {c['path']} ---\n{c['contents']}\n"
        for c in code_files
    ) if code_files else "(no code files provided)"

    return f"""DOMAIN: {domain}
INTENDED USE: {intended_use}

ARTIFACTS: governance_context_bundle.json
{json_dumps(bundle)}

ARTIFACTS: events.jsonl (parsed)
{json_dumps(events)}

CODE CONTEXT:
{code_blob}

CONSTRAINTS:
- No external logging/telemetry (no MLflow/Splunk).
- Prefer minimal code changes and import-only instrumentation when possible.

TASK:
(1) Determine privacy/regulatory issues in the context of the domain & intended use, grounded in evidence.
(2) Propose fixes to the model training code and instrumentation, with a unified diff patch.
"""

def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, indent=2, sort_keys=True)
