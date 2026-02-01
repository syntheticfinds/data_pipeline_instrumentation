from pydantic import BaseModel, Field
from typing import List, Literal, Optional

Severity = Literal["low", "medium", "high"]
CommentType = Literal[
    "structure",
    "clarity",
    "logic",
    "missing_context",
    "risk",
    "question",
    "rewrite",
    "compliance",
    "governance",
    "privacy",
    "bias",
]

class InlineComment(BaseModel):
    target_quote: str = Field(..., description="Exact substring from input text.")
    type: CommentType
    severity: Severity
    comment: str
    rewrite_suggestion: Optional[str] = None

class ReviewResponse(BaseModel):
    inline_comments: List[InlineComment]
