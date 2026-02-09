
import os
import sys
from dotenv import load_dotenv

# Add backend/ to the path so we can import review_llm alongside schemas
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from google_docs_client import GoogleDocsClient
from chunking import chunk_document
from review_llm import run_review
from ui_commenter import UIComment, add_anchored_comments_headful


def main() -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

    doc_id = os.getenv("GOOGLE_DOC_ID")
    if not doc_id:
        raise ValueError("Missing GOOGLE_DOC_ID")

    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

    # Read doc for LLM review (API)
    gclient = GoogleDocsClient.from_env()
    doc = gclient.get_document(doc_id)
    doc_text, paragraphs = gclient.extract_paragraphs(doc)
    
    chunks = chunk_document(paragraphs, max_chars=3500, overlap_paragraphs=1)

    # run_review() reviews ONE selection at a time, so loop and aggregate
    all_inline_comments = []
    doc_title = doc.get("title", "")

    for i, chunk in enumerate(chunks, start=1):
        r = run_review(
            selection=chunk.text,
            mode="healthcare",
            context_pack=None,
            doc_title=doc_title,
        )
        all_inline_comments.extend(r.inline_comments)

    # simple container so downstream code still works
    class _Review:
        def __init__(self, inline_comments):
            self.inline_comments = inline_comments

    review = _Review(all_inline_comments)

    # Convert to UI comments                                             
    ui_comments = []
    for c in review.inline_comments:
        body = f"[{c.type.upper()} | {c.severity.upper()}] {c.comment}"
        if getattr(c, "compliance_label", None):
            body += f"\n\nCompliance label: {c.compliance_label}"
        if getattr(c, "trustworthiness_property", None):
            body += f"\nTrustworthiness property: {c.trustworthiness_property}"
        if getattr(c, "regulatory_references", None):
            body += f"\nRegulatory reference(s): {c.regulatory_references}"
        if getattr(c, "action_evidence", None):
            body += f"\nAction / evidence to add: {c.action_evidence}"
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
    
    

