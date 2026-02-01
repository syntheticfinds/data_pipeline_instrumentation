import os
from typing import Optional, Literal, Dict, Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from fastapi.middleware.cors import CORSMiddleware

from review_llm import run_review
from schemas import ReviewResponse
from context_pack import build_context_pack

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://docs.google.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ReviewRequest(BaseModel):
    selection: str
    mode: Optional[Literal["general", "privacy"]] = "general"

    # Optional whole-doc metadata
    doc_title: Optional[str] = None
    doc_text: Optional[str] = None

    # Optional: if caller already built it
    context_pack: Optional[Dict[str, Any]] = None


@app.post("/review", response_model=ReviewResponse)
def review(req: ReviewRequest, x_api_key: str = Header(default="")):
    expected = os.getenv("REVIEWER_API_KEY", "")
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    selection = (req.selection or "").strip()
    if len(selection) < 30:
        raise HTTPException(status_code=400, detail="Selection too short")

    mode = req.mode or "general"

    # If privacy mode, we want doc-level context to inform frameworks/attributes
    context_pack = req.context_pack
    doc_title = (req.doc_title or "").strip()

    if mode == "privacy" and context_pack is None:
        doc_text = (req.doc_text or "").strip()

        # If doc_text isn't provided, we can still run privacy mode,
        # but it will be less context-aware.
        if doc_text:
            context_pack = build_context_pack(doc_text=doc_text, doc_title=doc_title)

    return run_review(
        selection=selection,
        mode=mode,
        context_pack=context_pack,
        doc_title=doc_title,
    )
