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
    "regulatory",
    "legal",
]

class InlineComment(BaseModel):
    target_quote: str = Field(..., description="Exact substring from input text.")
    type: CommentType
    severity: Severity
    comment: str
    rewrite_suggestion: Optional[str] = None
    # Healthcare regulatory lens fields (populated in healthcare mode)
    trustworthiness_property: Optional[str] = Field(
        None, description="Trustworthiness property name(s) from the taxonomy."
    )
    compliance_label: Optional[str] = Field(
        None, description="Regulatory | Legal | Rights/Risk (can list multiple)."
    )
    regulatory_references: Optional[str] = Field(
        None, description="Citations from the Regulatory Reference Index."
    )
    action_evidence: Optional[str] = Field(
        None, description="What to add/change/test; what artifact proves it."
    )

class ReviewResponse(BaseModel):
    inline_comments: List[InlineComment]
