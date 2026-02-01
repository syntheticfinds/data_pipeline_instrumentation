# privacy_review_agent/run_agent.py
from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from dotenv import load_dotenv
from typing import Dict, List

from privacy_review_agent.artifact_loader import load_bundle, load_events

load_dotenv()

# ----------------------------
# Prompt builders
# ----------------------------

def build_system_prompt() -> str:
    return """You are a privacy/security reviewer for ML training code.

You will receive:
- Evidence artifacts from a training run (governance bundle + events)
- Editable training code file(s)

CRITICAL RULES:
- You MUST ONLY modify files listed under EDITABLE_FILES.
- Do NOT propose or modify instrumentation code or any non-editable files.
- Make minimal, safe changes focused on training-time privacy risks.

REGULATORY ANCHOR:
- Anchor your reasoning primarily to GDPR.
- Prefer citing GDPR principles and specific articles when relevant:
  - Art. 5(1)(f) integrity and confidentiality
  - Art. 25 data protection by design and by default
  - Art. 32 security of processing (technical/organizational measures)
- If the domain indicates healthcare, you MAY additionally mention HIPAA concepts,
  but GDPR should remain the main anchor.

REQUIRED OUTPUT BEHAVIOR:
- You MUST use the text editor tool to edit the training file(s).
- For every fix you make, you MUST add an inline code comment near the change that explains:
  (a) what privacy risk it mitigates and
  (b) what GDPR principle/article it maps to.

After edits, output:
1) A short evidence-based review in markdown
2) A bullet list of changes you made
"""


def build_user_prompt(bundle: dict, events: list, editable_rel_paths: List[str]) -> str:
    domain = bundle.get("domain", "unknown")
    intended_use = bundle.get("intended_use", "unknown")

    return f"""DOMAIN: {domain}
INTENDED USE: {intended_use}

EDITABLE_FILES (ONLY files you may modify):
{json.dumps(editable_rel_paths, indent=2)}

ARTIFACTS: governance_context_bundle.json
{json.dumps(bundle, indent=2, sort_keys=True)}

ARTIFACTS: events.jsonl (parsed)
{json.dumps(events, indent=2, sort_keys=True)}

TASK:
1) Identify privacy/regulatory issues grounded in the artifacts and intended use.
2) Apply fixes ONLY to EDITABLE_FILES using the text editor tool.
3) IMPORTANT: For every code change, add an inline comment that:
   - explains the privacy/security reason, AND
   - explicitly references GDPR (e.g., Art. 5(1)(f), Art. 25, Art. 32).
4) Keep fixes minimal and safe.
"""


# ----------------------------
# Path helpers
# ----------------------------

def require_abs_path(p: str, arg_name: str) -> str:
    if not os.path.isabs(p):
        raise ValueError(f"{arg_name} must be an absolute path: got {p}")
    return p


def find_git_root(start_path: str) -> str:
    """
    Find git root by running: git rev-parse --show-toplevel
    Starting from the directory of start_path.
    """
    start_dir = start_path if os.path.isdir(start_path) else os.path.dirname(start_path)
    try:
        proc = subprocess.run(
            ["git", "-C", start_dir, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()
    except Exception as e:
        raise RuntimeError(
            f"Could not determine git repo root from: {start_dir}\n"
            f"Make sure you're running inside a git repo.\n"
            f"Error: {e}"
        )


def relpath_from_git_root(abs_path: str, git_root: str) -> str:
    abs_path = os.path.abspath(abs_path)
    git_root = os.path.abspath(git_root)
    try:
        return os.path.relpath(abs_path, git_root)
    except Exception:
        return abs_path


# ----------------------------
# File IO
# ----------------------------

def read_text_file(abs_path: str) -> str:
    with open(abs_path, "r", encoding="utf-8") as f:
        return f.read()


def write_text_file(abs_path: str, contents: str) -> None:
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(contents)


def load_editable_files_abs(editable_abs_paths: List[str]) -> Dict[str, str]:
    """
    returns abs_path -> file_contents
    """
    out = {}
    for p in editable_abs_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Editable file not found: {p}")
        out[p] = read_text_file(p)
    return out


# ----------------------------
# Diff generation (git apply friendly)
# ----------------------------

def compute_repo_relative_diff(
    *,
    git_root: str,
    abs_original: str,
    new_text: str,
) -> str:
    """
    Produces a git-style patch that targets repo-relative paths so `git apply` works.
    """
    import tempfile

    abs_original = os.path.abspath(abs_original)
    rel = relpath_from_git_root(abs_original, git_root)

    with tempfile.TemporaryDirectory() as td:
        abs_tmp_new = os.path.join(td, rel)
        os.makedirs(os.path.dirname(abs_tmp_new), exist_ok=True)

        with open(abs_tmp_new, "w", encoding="utf-8") as f:
            f.write(new_text)

        cmd = ["git", "diff", "--no-index", "--", abs_original, abs_tmp_new]
        proc = subprocess.run(cmd, capture_output=True, text=True)

        diff_out = proc.stdout
        if not diff_out.strip():
            return ""

        # Rewrite the paths so they refer to the repo file, not the temp file
        # Goal headers:
        # diff --git a/<rel> b/<rel>
        diff_out = diff_out.replace(abs_original, f"a/{rel}")
        diff_out = diff_out.replace(abs_tmp_new, f"b/{rel}")
        diff_out = diff_out.replace(
            f"diff --git {abs_original} {abs_tmp_new}",
            f"diff --git a/{rel} b/{rel}",
        )

        # Also fix ---/+++ lines if needed
        diff_out = diff_out.replace(f"--- a/{rel}", f"--- a/{rel}")
        diff_out = diff_out.replace(f"+++ b/{rel}", f"+++ b/{rel}")

        return diff_out.strip() + "\n"


def combine_diffs(diffs: List[str]) -> str:
    return "\n".join([d.strip() for d in diffs if d.strip()]).strip() + "\n"


# ----------------------------
# Claude tool-use: text editor tool
# ----------------------------

@dataclass
class ClaudeEditResult:
    edited_files: Dict[str, str]  # abs_path -> new content


def run_claude_text_editor(
    *,
    system_prompt: str,
    user_prompt: str,
    editable_abs_to_rel: Dict[str, str],
    editable_abs_to_contents: Dict[str, str],
    model: str,
    max_tokens: int,
    temperature: float,
) -> ClaudeEditResult:
    """
    Use Anthropic tool-use with a minimal text editor tool.
    We expose editable files to the model as repo-relative paths (friendly),
    but map them back to absolute paths in memory.
    """
    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing ANTHROPIC_API_KEY. Set it in your environment.\n"
            "Example:\n"
            "  export ANTHROPIC_API_KEY='...'\n"
        )

    client = Anthropic(api_key=api_key)

    # In-memory FS keyed by "rel path" (what the model sees)
    fs: Dict[str, str] = {}
    rel_to_abs: Dict[str, str] = {}

    for abs_path, rel_path in editable_abs_to_rel.items():
        rel_to_abs[rel_path] = abs_path
        fs[rel_path] = editable_abs_to_contents[abs_path]

    tools = [
        {
            "name": "text_editor",
            "description": (
                "Edit provided training code files. "
                "Allowed operations: open, replace."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["open", "replace"]},
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["operation", "path"],
            },
        }
    ]

    def tool_handler(tool_name: str, tool_input: dict) -> str:
        if tool_name != "text_editor":
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        op = tool_input.get("operation")
        path = tool_input.get("path")

        if path not in fs:
            return json.dumps({"error": f"Path not editable: {path}. Allowed: {sorted(fs.keys())}"})

        if op == "open":
            return fs[path]

        if op == "replace":
            old_text = tool_input.get("old_text", "")
            new_text = tool_input.get("new_text", "")

            if not old_text:
                return json.dumps({"error": "replace requires old_text"})
            if old_text not in fs[path]:
                return json.dumps({"error": "old_text not found in file"})
            fs[path] = fs[path].replace(old_text, new_text)
            return json.dumps({"ok": True})

        return json.dumps({"error": f"Unknown operation: {op}"})

    messages = [
        {"role": "user", "content": user_prompt},
        {
            "role": "user",
            "content": (
                "Use the text_editor tool to update ONLY the files listed in EDITABLE_FILES. "
                "First open each file, then apply minimal fixes using replace operations. "
                "CRITICAL: For every change you make in code, add an inline comment explaining the reason "
                "and referencing GDPR (Art. 5(1)(f), Art. 25, Art. 32). "
                "When finished, respond with markdown review summary and bullet list of changes."
            ),
        },
    ]

    for _ in range(12):
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
            tools=tools,
        )

        # ✅ Append assistant content (including tool_use) so tool_results can reference it
        messages.append({"role": "assistant", "content": resp.content})

        tool_calls = []
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                tool_calls.append(block)

        if not tool_calls:
            break

        for tc in tool_calls:
            tool_result = tool_handler(tc.name, tc.input)
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": tool_result,
                        }
                    ],
                }
            )

    # Convert rel-path edited files back to abs-path edited files
    edited_abs: Dict[str, str] = {}
    for rel_path, contents in fs.items():
        edited_abs[rel_to_abs[rel_path]] = contents

    return ClaudeEditResult(edited_files=edited_abs)


# ----------------------------
# Main
# ----------------------------

def main():
    ap = argparse.ArgumentParser(description="Privacy review agent (absolute paths only).")
    ap.add_argument("--run_dir_abs", required=True, help="Absolute path to governance_out/<run_id>/")
    ap.add_argument("--out_dir_abs", required=True, help="Absolute output directory for review artifacts")
    ap.add_argument(
        "--editable_abs",
        nargs="+",
        required=True,
        help="Absolute path(s) to editable training code files (ONLY these will be edited)",
    )
    args = ap.parse_args()

    run_dir = require_abs_path(args.run_dir_abs, "--run_dir_abs")
    out_dir = require_abs_path(args.out_dir_abs, "--out_dir_abs")
    editable_abs_paths = [require_abs_path(p, "--editable_abs") for p in args.editable_abs]

    os.makedirs(out_dir, exist_ok=True)

    # Load artifacts
    bundle = load_bundle(run_dir)
    events = load_events(run_dir)

    # Load editable files (abs paths)
    editable_abs_to_contents = load_editable_files_abs(editable_abs_paths)

    # Determine git root from first editable file
    git_root = find_git_root(editable_abs_paths[0])

    # Map abs->rel for readability in the prompt + tool paths
    editable_abs_to_rel = {p: relpath_from_git_root(p, git_root) for p in editable_abs_paths}
    editable_rel_paths = list(editable_abs_to_rel.values())

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(bundle, events, editable_rel_paths)

    model = os.getenv("CLAUDE_MODEL", "claude-opus-4-5-20251101")
    max_tokens = int(os.getenv("CLAUDE_MAX_TOKENS", "3000"))
    temperature = float(os.getenv("CLAUDE_TEMPERATURE", "0"))

    result = run_claude_text_editor(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        editable_abs_to_rel=editable_abs_to_rel,
        editable_abs_to_contents=editable_abs_to_contents,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    # Build patch
    diffs: List[str] = []
    for abs_path, new_text in result.edited_files.items():
        old_text = editable_abs_to_contents[abs_path]
        if new_text != old_text:
            diffs.append(
                compute_repo_relative_diff(
                    git_root=git_root,
                    abs_original=abs_path,
                    new_text=new_text,
                )
            )

    proposed_diff_path = os.path.join(out_dir, "proposed_fixes.diff")
    if diffs:
        patch = combine_diffs(diffs)
        write_text_file(proposed_diff_path, patch)
        print("Wrote:", proposed_diff_path)
    else:
        print("No code changes proposed; no diff written.")

    print("\nVS Code-first workflow:")
    if diffs:
        print(f"1) git apply {proposed_diff_path}")
        print("2) Open Source Control in VS Code to accept/reject hunks.")
    else:
        print("1) No patch generated (no code changes).")


if __name__ == "__main__":
    main()
