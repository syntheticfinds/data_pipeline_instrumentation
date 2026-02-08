from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Dict, Any

Severity = Literal["low", "medium", "high"]

class InlineComment(BaseModel):
    target_quote: str = Field(..., description="Exact substring from input text.")
    severity: Severity
    comment: str
    related_components: List[str] = Field(
        default_factory=list,
        description="Names of components or data flows this comment applies to"
    )

class ReviewResponse(BaseModel):
    inline_comments: List[InlineComment]
    # Parsed document structure - returned from review phase to avoid re-parsing during apply
    parsed_components: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Parsed technical components from the document (pass back during apply)"
    )
    parsed_data_flows: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Parsed data flows from the document (pass back during apply)"
    )
