import os
import logging
import sys
import uuid
import json
from typing import Optional, Literal, Dict, Any, List

from dotenv import load_dotenv
load_dotenv()  # MUST be called before importing modules that use env vars

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from fastapi.middleware.cors import CORSMiddleware

from review_llm import run_review_with_status
from schemas import ReviewResponse
from status_stream import create_session, get_session

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Set log levels for our modules
logging.getLogger("review_llm").setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
logging.getLogger("web_research").setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
logging.getLogger("document_orchestrator").setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# Reduce noise from third-party libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger("app")

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    logger.info("AI GDoc Reviewer Backend Starting")
    logger.info(f"Log level: {LOG_LEVEL}")
    logger.info(f"OpenAI model: {os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}")
    logger.info("=" * 60)

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

    # Google Doc ID for Sanity persistence
    google_doc_id: Optional[str] = None

    # Session ID for status streaming
    session_id: Optional[str] = None


@app.post("/review", response_model=ReviewResponse)
def review(req: ReviewRequest, x_api_key: str = Header(default="")):
    logger.info("=" * 60)
    logger.info("Received /review request")

    expected = os.getenv("REVIEWER_API_KEY", "")
    if not expected or x_api_key != expected:
        logger.warning("Unauthorized request - invalid API key")
        raise HTTPException(status_code=401, detail="Unauthorized")

    selection = (req.selection or "").strip()
    if len(selection) < 30:
        logger.warning(f"Selection too short: {len(selection)} chars")
        raise HTTPException(status_code=400, detail="Selection too short")

    mode = req.mode or "general"
    logger.info(f"Request mode: {mode}")
    logger.info(f"Selection length: {len(selection)} chars")
    logger.info(f"Doc title: {req.doc_title or '(not provided)'}")
    logger.info(f"Doc text provided: {'yes' if req.doc_text else 'no'}")
    logger.info(f"Google Doc ID: {req.google_doc_id or '(not provided)'}")

    doc_title = (req.doc_title or "").strip()
    doc_text = (req.doc_text or "").strip()

    # Get or create status emitter for this session
    session_id = req.session_id or str(uuid.uuid4())
    status = get_session(session_id) or create_session(session_id)

    # In privacy mode, pass the full document text so the reviewer can
    # understand the complete architecture (sections, components, data flows)
    # This eliminates the need for manual "Set AI Context"
    if mode == "privacy" and doc_text:
        logger.info(f"Full document provided ({len(doc_text)} chars) - will parse for architectural context")

    result = run_review_with_status(
        selection=selection,
        mode=mode,
        doc_title=doc_title,
        doc_text=doc_text if mode == "privacy" else None,
        google_doc_id=req.google_doc_id,
        status=status,
    )

    logger.info(f"Review complete - returning {len(result.inline_comments)} comments")
    logger.info("=" * 60)

    return result


# ---------- Status Streaming Endpoints ----------

@app.get("/status/{session_id}")
async def stream_status(session_id: str):
    """
    SSE endpoint for streaming status updates.
    Connect to this before starting a review/apply operation.
    """
    def generate():
        emitter = get_session(session_id)
        if not emitter:
            # Create a new session if it doesn't exist
            emitter = create_session(session_id)

        last_index = 0
        empty_count = 0

        while True:
            updates = emitter.get_since(last_index)
            if updates:
                empty_count = 0
                for update in updates:
                    yield f"data: {json.dumps(update)}\n\n"
                last_index += len(updates)

                # Check if we got a complete message
                for update in updates:
                    if update.get("type") == "complete":
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return
            else:
                empty_count += 1
                # Heartbeat every 2 seconds of inactivity
                if empty_count % 20 == 0:
                    yield f": heartbeat\n\n"
                # Timeout after 5 minutes of no activity
                if empty_count > 3000:
                    yield f"data: {json.dumps({'type': 'timeout'})}\n\n"
                    return

            import time
            time.sleep(0.1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )


# ---------- Modification Generation ----------

from pydantic import Field

class ComponentTarget(BaseModel):
    """Target component or data flow for a modification."""
    name: str = Field(..., description="Name of the component or data flow")
    target_type: str = Field(..., description="'component' or 'data_flow'")


class SimpleModification(BaseModel):
    """A modification targeting a specific component or data flow."""
    index: int = Field(..., description="Index of this modification")
    target: ComponentTarget = Field(..., description="The component or data flow to modify")
    modification: str = Field(..., description="Description of what changes are needed")
    issue_reference: str = Field(..., description="The compliance issue this addresses")
    severity: str = Field("medium", description="Severity: low, medium, high")


class GenerateModificationsRequest(BaseModel):
    """Request for generating modifications without Sanity."""
    review_comments: List[Dict[str, Any]] = Field(
        ..., description="Privacy review comments"
    )
    parsed_components: List[Dict[str, Any]] = Field(
        ..., description="Parsed technical components from the document"
    )
    parsed_data_flows: List[Dict[str, Any]] = Field(
        default_factory=list, description="Parsed data flows from the document"
    )
    session_id: Optional[str] = Field(None, description="Session ID for status streaming")


class GenerateModificationsResponse(BaseModel):
    """Response with generated modifications."""
    modifications: List[SimpleModification] = Field(
        default_factory=list, description="Generated modifications"
    )
    error: Optional[str] = Field(None, description="Error message if generation failed")


@app.post("/generate-modifications", response_model=GenerateModificationsResponse)
def generate_modifications(req: GenerateModificationsRequest, x_api_key: str = Header(default="")):
    """
    Generate modification suggestions based on review comments and parsed components/data flows.

    This is a simplified flow that doesn't use Sanity - it directly generates
    modifications targeting specific components or data flows.
    """
    logger.info("=" * 60)
    logger.info("Received /generate-modifications request")

    expected = os.getenv("REVIEWER_API_KEY", "")
    if not expected or x_api_key != expected:
        logger.warning("Unauthorized request - invalid API key")
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not req.review_comments:
        raise HTTPException(status_code=400, detail="No review comments provided")

    if not req.parsed_components and not req.parsed_data_flows:
        raise HTTPException(status_code=400, detail="No components or data flows provided")

    logger.info(f"Review comments: {len(req.review_comments)}")
    logger.info(f"Components: {len(req.parsed_components)}")
    logger.info(f"Data flows: {len(req.parsed_data_flows)}")

    # Get or create status emitter for this session
    session_id = req.session_id or str(uuid.uuid4())
    status = get_session(session_id) or create_session(session_id)

    try:
        from modification_generator import generate_component_modifications

        status.step("Analyzing compliance issues")

        modifications = generate_component_modifications(
            review_comments=req.review_comments,
            components=req.parsed_components,
            data_flows=req.parsed_data_flows,
            status=status,
        )

        logger.info(f"Generated {len(modifications)} modifications")
        status.complete(f"Generated {len(modifications)} modifications to review")

        # Convert to response models
        result_modifications = [
            SimpleModification(
                index=i,
                target=ComponentTarget(
                    name=mod.get("target_name", "Unknown"),
                    target_type=mod.get("target_type", "component"),
                ),
                modification=mod.get("modification", ""),
                issue_reference=mod.get("issue_reference", ""),
                severity=mod.get("severity", "medium"),
            )
            for i, mod in enumerate(modifications)
        ]

        return GenerateModificationsResponse(modifications=result_modifications)

    except Exception as e:
        logger.exception(f"Modification generation failed: {e}")
        status.error(f"Failed: {str(e)}")
        return GenerateModificationsResponse(error=str(e))
