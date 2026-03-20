"""
error_handler.py
----------------
Structured API Error Handling for Interrupted Sessions.
Covers retry-safe patterns and idempotency.

Every error returned by the API follows the same JSON shape:
{
    "error_code":  "SESSION_NOT_FOUND",
    "message":     "Human-readable description",
    "detail":      { ...extra context... },
    "retryable":   true/false,
    "retry_after_s": 5          # only if retryable
}

Intern : Atharva Dilip Bhosale
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional, Dict, TYPE_CHECKING
if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from fastapi.exceptions import RequestValidationError
import time
import logging

logger = logging.getLogger("error_handler")


# ─────────────────────────────────────────────────────────────────
# ERROR CODES
# ─────────────────────────────────────────────────────────────────

class ErrorCode(str, Enum):
    # Session errors
    SESSION_NOT_FOUND      = "SESSION_NOT_FOUND"
    SESSION_ALREADY_DONE   = "SESSION_ALREADY_DONE"
    SESSION_ABORTED        = "SESSION_ABORTED"
    SESSION_TIMED_OUT      = "SESSION_TIMED_OUT"
    SESSION_EXPIRED        = "SESSION_EXPIRED"

    # State machine errors
    INVALID_STATE          = "INVALID_STATE"
    ILLEGAL_TRANSITION     = "ILLEGAL_TRANSITION"

    # Question / answer errors
    ANSWER_TOO_SHORT       = "ANSWER_TOO_SHORT"
    ANSWER_EMPTY           = "ANSWER_EMPTY"
    QUESTION_TIMED_OUT     = "QUESTION_TIMED_OUT"
    NO_EXTENSION_REMAINING = "NO_EXTENSION_REMAINING"

    # External module errors
    TTS_FAILURE            = "TTS_FAILURE"
    STT_FAILURE            = "STT_FAILURE"
    GPT_FAILURE            = "GPT_FAILURE"
    SUMMARY_FAILURE        = "SUMMARY_FAILURE"
    LANGUAGE_DETECT_FAIL   = "LANGUAGE_DETECT_FAIL"

    # Infrastructure errors
    RATE_LIMITED           = "RATE_LIMITED"
    UPSTREAM_TIMEOUT       = "UPSTREAM_TIMEOUT"
    INTERNAL_ERROR         = "INTERNAL_ERROR"
    VALIDATION_ERROR       = "VALIDATION_ERROR"


# ─────────────────────────────────────────────────────────────────
# RETRYABILITY MAP
# True = client should retry; False = retrying won't help
# ─────────────────────────────────────────────────────────────────

RETRYABLE: Dict[ErrorCode, bool] = {
    ErrorCode.SESSION_NOT_FOUND:      False,
    ErrorCode.SESSION_ALREADY_DONE:   False,
    ErrorCode.SESSION_ABORTED:        False,
    ErrorCode.SESSION_TIMED_OUT:      False,
    ErrorCode.SESSION_EXPIRED:        False,
    ErrorCode.INVALID_STATE:          False,
    ErrorCode.ILLEGAL_TRANSITION:     False,
    ErrorCode.ANSWER_TOO_SHORT:       False,   # Fix the answer first
    ErrorCode.ANSWER_EMPTY:           False,
    ErrorCode.QUESTION_TIMED_OUT:     False,
    ErrorCode.NO_EXTENSION_REMAINING: False,
    ErrorCode.TTS_FAILURE:            True,    # Transient — retry
    ErrorCode.STT_FAILURE:            True,
    ErrorCode.GPT_FAILURE:            True,
    ErrorCode.SUMMARY_FAILURE:        True,
    ErrorCode.LANGUAGE_DETECT_FAIL:   True,
    ErrorCode.RATE_LIMITED:           True,
    ErrorCode.UPSTREAM_TIMEOUT:       True,
    ErrorCode.INTERNAL_ERROR:         True,
    ErrorCode.VALIDATION_ERROR:       False,
}

RETRY_AFTER_S: Dict[ErrorCode, int] = {
    ErrorCode.TTS_FAILURE:       3,
    ErrorCode.STT_FAILURE:       3,
    ErrorCode.GPT_FAILURE:       5,
    ErrorCode.SUMMARY_FAILURE:   5,
    ErrorCode.RATE_LIMITED:      10,
    ErrorCode.UPSTREAM_TIMEOUT:  5,
    ErrorCode.INTERNAL_ERROR:    3,
}

HTTP_STATUS: Dict[ErrorCode, int] = {
    ErrorCode.SESSION_NOT_FOUND:      404,
    ErrorCode.SESSION_ALREADY_DONE:   400,
    ErrorCode.SESSION_ABORTED:        400,
    ErrorCode.SESSION_TIMED_OUT:      400,
    ErrorCode.SESSION_EXPIRED:        400,
    ErrorCode.INVALID_STATE:          409,
    ErrorCode.ILLEGAL_TRANSITION:     409,
    ErrorCode.ANSWER_TOO_SHORT:       422,
    ErrorCode.ANSWER_EMPTY:           422,
    ErrorCode.QUESTION_TIMED_OUT:     408,
    ErrorCode.NO_EXTENSION_REMAINING: 400,
    ErrorCode.TTS_FAILURE:            503,
    ErrorCode.STT_FAILURE:            503,
    ErrorCode.GPT_FAILURE:            503,
    ErrorCode.SUMMARY_FAILURE:        503,
    ErrorCode.LANGUAGE_DETECT_FAIL:   503,
    ErrorCode.RATE_LIMITED:           429,
    ErrorCode.UPSTREAM_TIMEOUT:       504,
    ErrorCode.INTERNAL_ERROR:         500,
    ErrorCode.VALIDATION_ERROR:       422,
}


# ─────────────────────────────────────────────────────────────────
# CUSTOM EXCEPTION
# ─────────────────────────────────────────────────────────────────

class InterviewAPIError(Exception):
    """
    Raise this anywhere in the app to return a structured error response.

    Example:
        raise InterviewAPIError(
            code    = ErrorCode.SESSION_NOT_FOUND,
            message = f"Session '{session_id}' does not exist.",
            detail  = {"session_id": session_id},
        )
    """
    def __init__(
        self,
        code:    ErrorCode,
        message: str,
        detail:  Optional[Dict[str, Any]] = None,
    ):
        self.code    = code
        self.message = message
        self.detail  = detail or {}
        super().__init__(message)


# ─────────────────────────────────────────────────────────────────
# RESPONSE BUILDER
# ─────────────────────────────────────────────────────────────────

def build_error_response(
    code:    ErrorCode,
    message: str,
    detail:  Optional[Dict[str, Any]] = None,
) -> dict:
    """Build the standard error JSON body."""
    retryable = RETRYABLE.get(code, False)
    body: Dict[str, Any] = {
        "error_code": code.value,
        "message":    message,
        "detail":     detail or {},
        "retryable":  retryable,
        "timestamp":  time.time(),
    }
    if retryable:
        body["retry_after_s"] = RETRY_AFTER_S.get(code, 3)
    return body


# ─────────────────────────────────────────────────────────────────
# FASTAPI EXCEPTION HANDLERS
# Register these in main_v2.py with app.add_exception_handler(...)
# ─────────────────────────────────────────────────────────────────

async def interview_api_error_handler(
    request,
    exc: InterviewAPIError,
):
    from fastapi.responses import JSONResponse
    """Handles all InterviewAPIError exceptions raised in route handlers."""
    status_code = HTTP_STATUS.get(exc.code, 500)
    body        = build_error_response(exc.code, exc.message, exc.detail)
    logger.warning("API error [%s] %s | %s %s",
                   exc.code.value, exc.message,
                   request.method, request.url.path)
    return JSONResponse(status_code=status_code, content=body)


async def validation_error_handler(
    request,
    exc,
):
    from fastapi.responses import JSONResponse
    """Handles Pydantic v2 request validation errors."""
    errors = [
        {"field": ".".join(str(loc) for loc in e["loc"]), "msg": e["msg"]}
        for e in exc.errors()
    ]
    body = build_error_response(
        code    = ErrorCode.VALIDATION_ERROR,
        message = "Request body failed validation.",
        detail  = {"errors": errors},
    )
    logger.warning("Validation error on %s %s: %s",
                   request.method, request.url.path, errors)
    return JSONResponse(status_code=422, content=body)


async def generic_error_handler(
    request,
    exc: Exception,
):
    from fastapi.responses import JSONResponse
    """Catch-all for unhandled exceptions."""
    body = build_error_response(
        code    = ErrorCode.INTERNAL_ERROR,
        message = "An unexpected internal error occurred.",
        detail  = {"exception": type(exc).__name__},
    )
    logger.exception("Unhandled exception on %s %s",
                     request.method, request.url.path)
    return JSONResponse(status_code=500, content=body)


# ─────────────────────────────────────────────────────────────────
# RETRY-SAFE WRAPPER
# Use this to call external modules (GPT, TTS, STT) safely
# ─────────────────────────────────────────────────────────────────

def safe_call(fn, *args, error_code: ErrorCode, label: str = "", **kwargs):
    """
    Wraps an external module call. On failure, raises InterviewAPIError
    with the given error_code so the client knows to retry.

    Example:
        question = safe_call(
            question_generator,
            domain="Deep Learning", difficulty="hard", history=[], language="en",
            error_code = ErrorCode.GPT_FAILURE,
            label      = "GPT question generator",
        )
    """
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.error("Module call failed [%s]: %s", label or fn.__name__, e)
        raise InterviewAPIError(
            code    = error_code,
            message = f"External module '{label or fn.__name__}' failed: {type(e).__name__}",
            detail  = {"module": label or fn.__name__, "exception": str(e)},
        )


# ─────────────────────────────────────────────────────────────────
# IDEMPOTENCY HELPERS
# ─────────────────────────────────────────────────────────────────

_idempotency_cache: Dict[str, dict] = {}

def get_idempotent_response(key: str) -> Optional[dict]:
    """
    Check if this request was already processed (retry-safe endpoints).
    Returns the cached response body if found, else None.
    """
    return _idempotency_cache.get(key)

def cache_idempotent_response(key: str, response: dict, ttl_s: int = 300) -> None:
    """Cache a response for an idempotency key (default 5-minute TTL)."""
    _idempotency_cache[key] = {
        "response":   response,
        "cached_at":  time.time(),
        "expires_at": time.time() + ttl_s,
    }

def purge_expired_idempotency_keys() -> int:
    """Remove expired keys. Call periodically (e.g. on startup lifespan)."""
    now     = time.time()
    expired = [k for k, v in _idempotency_cache.items() if v["expires_at"] < now]
    for k in expired:
        del _idempotency_cache[k]
    return len(expired)
