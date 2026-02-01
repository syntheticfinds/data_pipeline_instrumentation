import os
from dotenv import load_dotenv

from google_docs_client import GoogleDocsClient
from chunking import chunk_document
from ai_gdoc_reviewer.backend.review_llm import review_chunks_eu_ai_act
from ui_commenter import UIComment, add_anchored_comments_headful


def main() -> None:
    load_dotenv()

    doc_id = os.getenv("GOOGLE_DOC_ID")
    if not doc_id:
        raise ValueError("Missing GOOGLE_DOC_ID")

    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

    # Read doc for LLM review (API)
    gclient = GoogleDocsClient.from_env()
    doc = gclient.get_document(doc_id)
    doc_text, paragraphs = gclient.extract_paragraphs(doc)

    chunks = chunk_document(paragraphs, max_chars=3500, overlap_paragraphs=1)
    review = review_chunks_eu_ai_act(
        doc_title=doc.get("title", ""),
        doc_text_preview=doc_text[:4000],
        chunks=chunks,
    )

    # Convert to UI comments
    ui_comments = []
    for c in review.inline_comments:
        body = f"[{c.type.upper()} | {c.severity.upper()}] {c.comment}"
        if c.rewrite_suggestion:
            body += f"\n\nSuggested rewrite:\n{c.rewrite_suggestion}"

        ui_comments.append(UIComment(target_quote=c.target_quote, comment_text=body))

    add_anchored_comments_headful(
        doc_url=doc_url,
        comments=ui_comments,
        user_data_dir=os.getenv("PLAYWRIGHT_PROFILE_DIR", ".pw_google_profile"),
        slow_mo_ms=int(os.getenv("PLAYWRIGHT_SLOW_MO_MS", "50")),
        max_comments=None,
        retries=2,
    )


if __name__ == "__main__":
    main()
