import os
import logging
import sys
import uuid
import json
import threading
from typing import Optional, Literal, Dict, Any, List

from dotenv import load_dotenv
load_dotenv()  # MUST be called before importing modules that use env vars

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from fastapi.middleware.cors import CORSMiddleware

from review_llm import run_review_with_status
from schemas import ReviewResponse
from document_orchestrator import process_document_with_review_status, DocumentGraphOrchestrator
from status_stream import StatusEmitter, create_session, get_session, remove_session

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
logging.getLogger("sanity_client").setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
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
    logger.info(f"Sanity project: {os.getenv('SANITY_PROJECT_ID', 'ukousf31')}")
    logger.info(f"Sanity dataset: {os.getenv('SANITY_DATASET', 'production')}")
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


@app.post("/session/create")
def create_status_session():
    """Create a new status session and return the session ID."""
    session_id = str(uuid.uuid4())
    create_session(session_id)
    return {"session_id": session_id}


@app.delete("/session/{session_id}")
def delete_status_session(session_id: str):
    """Delete a status session."""
    remove_session(session_id)
    return {"deleted": True}


# ---------- Document Graph Orchestrator Endpoints ----------

from typing import List
from pydantic import Field

class OrchestratorRequest(BaseModel):
    """Request for the document graph orchestrator."""
    doc_text: str = Field(..., description="Full text of the design document")
    doc_title: str = Field(..., description="Title of the document")
    google_doc_id: Optional[str] = Field(None, description="Google Doc ID for write-back")
    google_doc_url: Optional[str] = Field(None, description="Google Doc URL")
    review_comments: List[Dict[str, Any]] = Field(
        ..., description="Privacy review comments to process"
    )
    # Pre-parsed structure from review phase (avoids re-parsing)
    parsed_components: Optional[List[Dict[str, Any]]] = Field(
        None, description="Pre-parsed components from review phase"
    )
    parsed_data_flows: Optional[List[Dict[str, Any]]] = Field(
        None, description="Pre-parsed data flows from review phase"
    )
    # Session ID for status streaming
    session_id: Optional[str] = Field(None, description="Session ID for status streaming")


class ActionResult(BaseModel):
    """Result of a Sanity Agent Action execution."""
    action_type: str = Field(..., description="Type of action: generate, transform, image, replace")
    target: str = Field(..., description="Target document ID")
    success: bool = Field(..., description="Whether the action succeeded")
    error: Optional[str] = Field(None, description="Error message if action failed")


class TargetSection(BaseModel):
    """Target section for a guided modification."""
    title: str = Field(..., description="Section title or 'New Section' if adding new")
    is_new: bool = Field(False, description="Whether this should be a new section")


class GuidedModification(BaseModel):
    """A single modification for guided user walkthrough."""
    index: int = Field(..., description="Index of this modification in the list")
    suggestion_id: str = Field(..., description="Sanity suggestion document ID")
    modification_text: str = Field(..., description="The text/content to add to the document")
    target_section: TargetSection = Field(..., description="Which section to add this to")
    issue_reference: str = Field(..., description="The compliance issue this addresses")
    severity: str = Field("medium", description="Severity: low, medium, high")
    action_type: str = Field("generate", description="Type of modification action")


class OrchestratorResponse(BaseModel):
    """Response from the document graph orchestrator."""
    design_doc_id: Optional[str] = Field(None, description="Sanity document ID for the graph")
    issue_ids: List[str] = Field(default_factory=list, description="Created compliance issue IDs")
    suggestion_ids: List[str] = Field(default_factory=list, description="Created modification suggestion IDs")
    action_results: List[ActionResult] = Field(
        default_factory=list,
        description="Results from executing Sanity Agent Actions"
    )
    guided_modifications: List[GuidedModification] = Field(
        default_factory=list,
        description="Structured modifications for guided user walkthrough"
    )
    error: Optional[str] = Field(None, description="Error message if processing failed")


@app.post("/orchestrate-modifications", response_model=OrchestratorResponse)
def orchestrate_modifications(req: OrchestratorRequest, x_api_key: str = Header(default="")):
    """
    Full document graph pipeline:
    1. Parse document into graph structure in Sanity
    2. Create compliance issues from review comments
    3. Decide and create modification suggestions
    4. Return suggestions for Google Docs write-back
    """
    logger.info("=" * 60)
    logger.info("Received /orchestrate-modifications request")

    expected = os.getenv("REVIEWER_API_KEY", "")
    if not expected or x_api_key != expected:
        logger.warning("Unauthorized request - invalid API key")
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not req.doc_text or len(req.doc_text.strip()) < 100:
        raise HTTPException(status_code=400, detail="Document text too short")

    if not req.review_comments:
        raise HTTPException(status_code=400, detail="No review comments provided")

    logger.info(f"Document: {req.doc_title}")
    logger.info(f"Document length: {len(req.doc_text)} chars")
    logger.info(f"Review comments: {len(req.review_comments)}")
    logger.info(f"Google Doc ID: {req.google_doc_id or '(not provided)'}")
    logger.info(f"Pre-parsed structure: {'yes' if req.parsed_components else 'no'}")

    # Get or create status emitter for this session
    session_id = req.session_id or str(uuid.uuid4())
    status = get_session(session_id) or create_session(session_id)

    # Check for Sanity API token
    if not os.getenv("SANITY_API_TOKEN"):
        logger.error("SANITY_API_TOKEN not configured")
        status.error("Sanity API token not configured")
        raise HTTPException(
            status_code=500,
            detail="Sanity API token not configured. Set SANITY_API_TOKEN env var."
        )

    try:
        result = process_document_with_review_status(
            doc_text=req.doc_text,
            doc_title=req.doc_title,
            review_comments=req.review_comments,
            google_doc_id=req.google_doc_id,
            google_doc_url=req.google_doc_url,
            parsed_components=req.parsed_components,
            parsed_data_flows=req.parsed_data_flows,
            status=status,
        )

        if "error" in result:
            logger.error(f"Orchestrator error: {result['error']}")
            status.error(result["error"])
            return OrchestratorResponse(error=result["error"])

        logger.info(f"Created document graph: {result.get('design_doc_id')}")
        logger.info(f"Created {len(result.get('issue_ids', []))} compliance issues")
        logger.info(f"Executed {len(result.get('action_results', []))} agent actions")
        logger.info(f"Created {len(result.get('suggestion_ids', []))} modification suggestions")
        logger.info(f"Generated {len(result.get('guided_modifications', []))} guided modifications")
        logger.info("=" * 60)

        # Convert action_results to ActionResult models
        action_results = [
            ActionResult(
                action_type=ar.get("action_type", "unknown"),
                target=ar.get("target", "unknown"),
                success=ar.get("success", False),
                error=ar.get("error"),
            )
            for ar in result.get("action_results", [])
        ]

        # Convert guided_modifications to GuidedModification models
        guided_modifications = [
            GuidedModification(
                index=gm.get("index", i),
                suggestion_id=gm.get("suggestion_id", ""),
                modification_text=gm.get("modification_text", ""),
                target_section=TargetSection(
                    title=gm.get("target_section", {}).get("title", "Unknown Section"),
                    is_new=gm.get("target_section", {}).get("is_new", False),
                ),
                issue_reference=gm.get("issue_reference", ""),
                severity=gm.get("severity", "medium"),
                action_type=gm.get("action_type", "generate"),
            )
            for i, gm in enumerate(result.get("guided_modifications", []))
        ]

        status.complete(f"Ready to apply {len(guided_modifications)} modifications")

        return OrchestratorResponse(
            design_doc_id=result.get("design_doc_id"),
            issue_ids=result.get("issue_ids", []),
            suggestion_ids=result.get("suggestion_ids", []),
            action_results=action_results,
            guided_modifications=guided_modifications,
        )

    except Exception as e:
        logger.exception(f"Orchestrator failed: {e}")
        status.error(f"Orchestrator failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Cleanup Endpoint ----------

class CleanupRequest(BaseModel):
    """Request to cleanup design-related documents after modifications are applied."""
    design_doc_id: Optional[str] = Field(None, description="Specific designDocument ID to cleanup")
    google_doc_id: Optional[str] = Field(None, description="Google Doc ID to lookup and cleanup")


class CleanupResponse(BaseModel):
    """Response from cleanup operation."""
    success: bool = Field(..., description="Whether cleanup succeeded")
    deleted_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of deleted documents per type"
    )
    error: Optional[str] = Field(None, description="Error message if cleanup failed")


@app.post("/cleanup", response_model=CleanupResponse)
def cleanup_documents(req: CleanupRequest, x_api_key: str = Header(default="")):
    """
    Cleanup design-related documents from Sanity after modifications have been applied.

    Call this endpoint after successfully applying suggestions to Google Docs
    to remove the temporary graph structure from Sanity.
    """
    logger.info("=" * 60)
    logger.info("Received /cleanup request")

    expected = os.getenv("REVIEWER_API_KEY", "")
    if not expected or x_api_key != expected:
        logger.warning("Unauthorized request - invalid API key")
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not req.design_doc_id and not req.google_doc_id:
        raise HTTPException(
            status_code=400,
            detail="Must provide either design_doc_id or google_doc_id"
        )

    logger.info(f"Design doc ID: {req.design_doc_id or '(not provided)'}")
    logger.info(f"Google Doc ID: {req.google_doc_id or '(not provided)'}")

    try:
        orchestrator = DocumentGraphOrchestrator()
        deleted_counts = orchestrator.cleanup_design_documents(
            design_doc_id=req.design_doc_id,
            google_doc_id=req.google_doc_id,
        )

        total_deleted = sum(deleted_counts.values())
        logger.info(f"Cleanup complete - deleted {total_deleted} documents")
        logger.info("=" * 60)

        return CleanupResponse(
            success=True,
            deleted_counts=deleted_counts,
        )

    except Exception as e:
        logger.exception(f"Cleanup failed: {e}")
        return CleanupResponse(
            success=False,
            deleted_counts={},
            error=str(e),
        )
