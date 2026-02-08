"""
Status streaming module for real-time thought process updates.

Provides a simple way to emit status updates during review and orchestration
that can be streamed to the frontend via SSE.
"""

import asyncio
import json
import time
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
from contextlib import contextmanager
import threading

class StatusType(str, Enum):
    """Types of status updates."""
    INFO = "info"
    STEP = "step"
    DETAIL = "detail"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    COMPLETE = "complete"


@dataclass
class StatusUpdate:
    """A single status update."""
    type: StatusType
    message: str
    timestamp: float = field(default_factory=time.time)
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "details": self.details,
        }

    def to_sse(self) -> str:
        """Format as SSE event."""
        return f"data: {json.dumps(self.to_dict())}\n\n"


class StatusEmitter:
    """
    Thread-safe status emitter that collects updates during processing.

    Usage:
        emitter = StatusEmitter()
        emitter.emit("Starting review...", StatusType.STEP)
        emitter.emit("Found 5 components", StatusType.INFO)
        updates = emitter.get_all()
    """

    def __init__(self):
        self._updates: List[StatusUpdate] = []
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[StatusUpdate], None]] = []

    def emit(
        self,
        message: str,
        status_type: StatusType = StatusType.INFO,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit a status update."""
        update = StatusUpdate(
            type=status_type,
            message=message,
            details=details,
        )
        with self._lock:
            self._updates.append(update)
            for callback in self._callbacks:
                try:
                    callback(update)
                except Exception:
                    pass

    def step(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Emit a step update (major progress indicator)."""
        self.emit(message, StatusType.STEP, details)

    def info(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Emit an info update."""
        self.emit(message, StatusType.INFO, details)

    def detail(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Emit a detail update (minor info)."""
        self.emit(message, StatusType.DETAIL, details)

    def success(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Emit a success update."""
        self.emit(message, StatusType.SUCCESS, details)

    def warning(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Emit a warning update."""
        self.emit(message, StatusType.WARNING, details)

    def error(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Emit an error update."""
        self.emit(message, StatusType.ERROR, details)

    def complete(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Emit a completion update."""
        self.emit(message, StatusType.COMPLETE, details)

    def add_callback(self, callback: Callable[[StatusUpdate], None]) -> None:
        """Add a callback to be notified of new updates."""
        with self._lock:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[StatusUpdate], None]) -> None:
        """Remove a callback."""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def get_all(self) -> List[Dict[str, Any]]:
        """Get all updates as a list of dicts."""
        with self._lock:
            return [u.to_dict() for u in self._updates]

    def get_since(self, index: int) -> List[Dict[str, Any]]:
        """Get updates since a given index."""
        with self._lock:
            return [u.to_dict() for u in self._updates[index:]]

    def clear(self) -> None:
        """Clear all updates."""
        with self._lock:
            self._updates.clear()


# Global registry of active sessions
_active_sessions: Dict[str, StatusEmitter] = {}
_sessions_lock = threading.Lock()


def create_session(session_id: str) -> StatusEmitter:
    """Create a new status session."""
    emitter = StatusEmitter()
    with _sessions_lock:
        _active_sessions[session_id] = emitter
    return emitter


def get_session(session_id: str) -> Optional[StatusEmitter]:
    """Get an existing status session."""
    with _sessions_lock:
        return _active_sessions.get(session_id)


def remove_session(session_id: str) -> None:
    """Remove a status session."""
    with _sessions_lock:
        _active_sessions.pop(session_id, None)


@contextmanager
def status_session(session_id: str):
    """Context manager for a status session."""
    emitter = create_session(session_id)
    try:
        yield emitter
    finally:
        # Keep session around for a bit so client can get final updates
        pass  # Don't remove immediately
