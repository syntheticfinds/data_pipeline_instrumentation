from typing import List
from ai_gdoc_reviewer.backend.review_llm import ReviewOutput


def _format_inline_comment(i: int, c) -> str:
    # Keep this readable inside Google Docs.
    lines: List[str] = []
    lines.append(f"- [{c.type.upper()} | {c.severity.upper()}] “{c.target_quote}”")
    lines.append(f"  - Comment: {c.comment}")
    if c.rewrite_suggestion:
        lines.append(f"  - Suggested rewrite: {c.rewrite_suggestion}")
    return "\n".join(lines)


def build_review_notes_markdown(review: ReviewOutput) -> str:
    """
    Produces plain-text “markdown-ish” bullets that display nicely in Google Docs.
    (We insert it as text; Docs will keep line breaks.)
    """
    out: List[str] = []
    out.append(f"Summary: {review.doc_summary}")
    out.append("")

    if review.global_comments:
        out.append("Global comments:")
        for gc in review.global_comments:
            out.append(f"- [{gc.type.upper()} | {gc.severity.upper()}] {gc.comment}")
        out.append("")

    if review.inline_comments:
        out.append("Inline comments:")
        for idx, ic in enumerate(review.inline_comments, start=1):
            out.append(_format_inline_comment(idx, ic))
        out.append("")

    # Final newline is nice for doc formatting
    return "\n".join(out).strip() + "\n"
