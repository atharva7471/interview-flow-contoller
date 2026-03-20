"""
main_v2.py
----------
FastAPI Application v2 — Interview Flow Controller (Optimized)
Intern  : Atharva Dilip Bhosale
Module  : Interview & Assessment Flow Controller Optimization

New in v2:
  - State-machine-driven session flow (state_machine.py)
  - Per-question and session-level timeout management (timeout_manager.py)
  - Structured error handling with retryable flags (error_handler.py)
  - Idempotency support on POST /interview/answer
  - Timeout extension endpoint
  - Transition log endpoint for debugging

Run:
    uvicorn main_v2:app --reload --port 8000
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager
from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from typing import Optional

import controller as ctrl
from state_machine import InterviewStateMachine, InterviewState, InterviewEvent
from timeout_manager import timeout_manager
from error_handler import (
    InterviewAPIError, ErrorCode,
    interview_api_error_handler, validation_error_handler, generic_error_handler,
    safe_call, get_idempotent_response, cache_idempotent_response,
    purge_expired_idempotency_keys,
)
from mock_modules import question_generator, tts_speaker, summary_generator, detect_language

# Pydantic models (reuse from v1, extend below)
from models import (
    StartInterviewRequest, StartInterviewResponse,
    SubmitAnswerRequest,   SubmitAnswerResponse,
    AbortInterviewRequest, AbortResponse,
    ProgressResponse,      SummaryResponse,
    QAPairResponse,        HealthResponse,
    DifficultyEnum,        InterviewStateEnum,
)
from pydantic import BaseModel, Field
from typing import List, Dict, Any


# ─────────────────────────────────────────────────────────────────
# NEW v2 MODELS
# ─────────────────────────────────────────────────────────────────

class TimeoutStatusResponse(BaseModel):
    session_id:             str
    session_elapsed_s:      float
    session_remaining_s:    float
    session_expired:        bool
    current_question_timer: Optional[Dict[str, Any]] = None
    question_history:       List[Dict[str, Any]]     = []


class ExtensionRequest(BaseModel):
    session_id:      str = Field(..., description="Session ID")
    question_number: int = Field(..., description="Question number to extend")


class ExtensionResponse(BaseModel):
    granted:         bool
    extensions_used: Optional[int]   = None
    extensions_max:  Optional[int]   = None
    new_remaining_s: Optional[float] = None
    reason:          str


class TransitionLogResponse(BaseModel):
    session_id: str
    current_state: str
    valid_events:  List[str]
    history:       List[Dict[str, Any]]


# ─────────────────────────────────────────────────────────────────
# IN-MEMORY STATE MACHINE STORE
# ─────────────────────────────────────────────────────────────────
_state_machines: Dict[str, InterviewStateMachine] = {}


def get_fsm(session_id: str) -> InterviewStateMachine:
    if session_id not in _state_machines:
        raise InterviewAPIError(
            code    = ErrorCode.SESSION_NOT_FOUND,
            message = f"Session '{session_id}' not found.",
            detail  = {"session_id": session_id},
        )
    return _state_machines[session_id]


# ─────────────────────────────────────────────────────────────────
# SUMMARY HELPER
# ─────────────────────────────────────────────────────────────────

def _build_summary_response(summary: dict) -> SummaryResponse:
    return SummaryResponse(
        session_id = summary["session_id"],
        domain     = summary["domain"],
        language   = summary["language"],
        duration_s = summary["duration_s"],
        q_count    = summary["q_count"],
        strengths  = summary["strengths"],
        weaknesses = summary["weaknesses"],
        score      = summary["score"],
        qa_pairs   = [
            QAPairResponse(
                question_number = p["question_number"],
                difficulty      = DifficultyEnum(p["difficulty"]),
                question        = p["question"],
                answer          = p["answer"],
                timestamp       = p["timestamp"],
            )
            for p in summary["qa_pairs"]
        ],
    )


# ─────────────────────────────────────────────────────────────────
# APP LIFESPAN
# ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    purge_expired_idempotency_keys()
    yield
    # Shutdown (cleanup if needed)


# ─────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "Interview Flow Controller API v2",
    description = (
        "**Module: Interview Flow Controller Optimization** | Intern: Atharva Dilip Bhosale\n\n"
        "v2 adds: state-machine architecture, timeout management, structured error handling, "
        "idempotent endpoints, and transition logging."
    ),
    version     = "2.0.0",
    lifespan    = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Register structured error handlers
app.add_exception_handler(InterviewAPIError,       interview_api_error_handler)
app.add_exception_handler(RequestValidationError,  validation_error_handler)
app.add_exception_handler(Exception,               generic_error_handler)


# ─────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health():
    return HealthResponse(status="ok", version="2.0.0", author="Atharva Dilip Bhosale")


# ── 1. START ─────────────────────────────────────────────────────

@app.post(
    "/interview/start",
    response_model = StartInterviewResponse,
    status_code    = 201,
    tags           = ["Interview Flow v2"],
    summary        = "Start interview (state-machine driven)",
)
async def start_interview(req: StartInterviewRequest):
    """
    Creates session + FSM. Fires START event → INTRODUCING state.
    Starts session and question timers.
    Error responses follow the structured format with retryable flags.
    """
    # Create session in controller
    session = ctrl.create_session(domain=req.domain, language=req.language)

    # Create and store FSM
    fsm = InterviewStateMachine(session.session_id)
    _state_machines[session.session_id] = fsm

    # Transition: IDLE → INTRODUCING
    result = fsm.trigger(InterviewEvent.START)
    if not result.success:
        raise InterviewAPIError(
            code    = ErrorCode.ILLEGAL_TRANSITION,
            message = result.message,
            detail  = {"session_id": session.session_id},
        )

    # Start timers
    timeout_manager.start_session(session.session_id)
    timeout_manager.start_question_timer(session.session_id, 1)

    # Generate Q1 (always fixed — no GPT call)
    first_question = ctrl.get_next_question(session, question_generator)
    session._pending_question = first_question  # type: ignore

    # Speak via TTS (wrapped safely)
    safe_call(tts_speaker, first_question, session.language,
              error_code=ErrorCode.TTS_FAILURE, label="TTS")

    return StartInterviewResponse(
        session_id      = session.session_id,
        first_question  = first_question,
        difficulty      = DifficultyEnum(ctrl.get_difficulty(1).value),
        question_number = 1,
        total_questions = ctrl.TOTAL_QUESTIONS,
        message         = f"Interview started. State: {fsm.state.value}",
    )


# ── 2. SUBMIT ANSWER (idempotent) ─────────────────────────────────

@app.post(
    "/interview/answer",
    response_model = SubmitAnswerResponse,
    tags           = ["Interview Flow v2"],
    summary        = "Submit answer — idempotency-key supported",
)
async def submit_answer(
    req: SubmitAnswerRequest,
    idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """
    Records answer and returns next question.
    Supports **X-Idempotency-Key** header — if the same key is sent twice
    (e.g. network retry), the cached response is returned instead of
    processing the answer again.

    Structured errors include **retryable: true/false** so the client
    knows whether to retry immediately.
    """
    # ── Idempotency check ─────────────────────────────────────────
    if idempotency_key:
        cached = get_idempotent_response(idempotency_key)
        if cached:
            return SubmitAnswerResponse(**cached["response"])

    # ── Session + FSM validation ─────────────────────────────────
    session = ctrl.get_session(req.session_id)
    if not session:
        raise InterviewAPIError(
            code    = ErrorCode.SESSION_NOT_FOUND,
            message = f"Session '{req.session_id}' not found.",
            detail  = {"session_id": req.session_id},
        )

    fsm = get_fsm(req.session_id)

    if fsm.state == InterviewState.INTERRUPTED:
        raise InterviewAPIError(
            code    = ErrorCode.SESSION_ABORTED,
            message = "This session was aborted.",
            detail  = {"current_state": fsm.state.value},
        )
    if fsm.state == InterviewState.TIMED_OUT:
        raise InterviewAPIError(
            code    = ErrorCode.SESSION_TIMED_OUT,
            message = "Session timed out. Please start a new interview.",
            detail  = {"current_state": fsm.state.value},
        )
    if fsm.state == InterviewState.DONE:
        raise InterviewAPIError(
            code    = ErrorCode.SESSION_ALREADY_DONE,
            message = "Interview already completed. Use GET /interview/summary.",
            detail  = {"current_state": fsm.state.value},
        )

    # ── Answer validation ─────────────────────────────────────────
    if not req.answer or not req.answer.strip():
        raise InterviewAPIError(
            code    = ErrorCode.ANSWER_EMPTY,
            message = "Answer cannot be empty.",
            detail  = {"session_id": req.session_id},
        )
    if len(req.answer.strip()) < 3:
        raise InterviewAPIError(
            code    = ErrorCode.ANSWER_TOO_SHORT,
            message = "Answer is too short to be meaningful.",
            detail  = {"min_length": 3, "received_length": len(req.answer.strip())},
        )

    # ── Timeout check ─────────────────────────────────────────────
    answered_q_number = session.current_question_number
    if timeout_manager.check_question_timeout(req.session_id, answered_q_number):
        fsm.trigger(InterviewEvent.TIMEOUT, context={"question": answered_q_number})
        raise InterviewAPIError(
            code    = ErrorCode.QUESTION_TIMED_OUT,
            message = f"Question {answered_q_number} timed out. No answer recorded.",
            detail  = {"question_number": answered_q_number},
        )
    if timeout_manager.check_session_timeout(req.session_id):
        fsm.trigger(InterviewEvent.TIMEOUT)
        raise InterviewAPIError(
            code    = ErrorCode.SESSION_EXPIRED,
            message = "Total session time limit exceeded.",
            detail  = {"session_id": req.session_id},
        )

    # ── Language detection ────────────────────────────────────────
    detected_lang = safe_call(
        detect_language, req.answer,
        error_code=ErrorCode.LANGUAGE_DETECT_FAIL, label="Language detection"
    )
    if detected_lang != session.language:
        session.language = detected_lang

    # ── Get current question text ─────────────────────────────────
    question_text = getattr(session, "_pending_question", ctrl.FIRST_QUESTION)

    # ── Determine event for FSM ───────────────────────────────────
    is_last      = (answered_q_number == ctrl.TOTAL_QUESTIONS)
    fsm_event    = InterviewEvent.LAST_ANSWERED if is_last else InterviewEvent.ANSWER_RECEIVED

    # ── Fire FSM transition ───────────────────────────────────────
    t = fsm.trigger(fsm_event, context={"question_number": answered_q_number})
    if not t.success:
        raise InterviewAPIError(
            code    = ErrorCode.ILLEGAL_TRANSITION,
            message = t.message,
            detail  = {"from_state": t.from_state.value, "event": fsm_event.value},
        )

    # ── Record answer + advance counter ──────────────────────────
    timeout_manager.record_answer(req.session_id, answered_q_number)
    ctrl.record_answer(
        session           = session,
        question_text     = question_text,
        answer_text       = req.answer,
        summary_generator = summary_generator,
    )

    questions_remaining = session.questions_remaining
    interview_complete  = session.is_complete

    # ── Build response ────────────────────────────────────────────
    if interview_complete:
        # COMPLETING → DONE
        fsm.trigger(InterviewEvent.SUMMARY_READY)
        timeout_manager.end_session(req.session_id)

        summary_data = session.summary or {}
        response_data = SubmitAnswerResponse(
            session_id           = session.session_id,
            answer_recorded      = True,
            question_number      = answered_q_number,
            questions_remaining  = 0,
            interview_complete   = True,
            next_question        = None,
            next_difficulty      = None,
            next_question_number = None,
            summary              = _build_summary_response(summary_data),
            message              = f"Interview complete! State: {fsm.state.value}",
        )
    else:
        # Generate next question safely
        next_q_num  = session.current_question_number
        next_diff   = ctrl.get_difficulty(next_q_num)
        next_q_text = safe_call(
            ctrl.get_next_question, session, question_generator,
            error_code=ErrorCode.GPT_FAILURE, label="GPT question generator"
        )
        session._pending_question = next_q_text  # type: ignore

        # Start next question timer
        timeout_manager.start_question_timer(req.session_id, next_q_num)

        safe_call(tts_speaker, next_q_text, session.language,
                  error_code=ErrorCode.TTS_FAILURE, label="TTS")

        response_data = SubmitAnswerResponse(
            session_id           = session.session_id,
            answer_recorded      = True,
            question_number      = answered_q_number,
            questions_remaining  = questions_remaining,
            interview_complete   = False,
            next_question        = next_q_text,
            next_difficulty      = DifficultyEnum(next_diff.value),
            next_question_number = next_q_num,
            summary              = None,
            message              = f"Answer recorded. Q{next_q_num}/10 ready. State: {fsm.state.value}",
        )

    # ── Cache for idempotency ─────────────────────────────────────
    if idempotency_key:
        cache_idempotent_response(idempotency_key, response_data.model_dump())

    return response_data


# ── 3. PROGRESS ───────────────────────────────────────────────────

@app.get(
    "/interview/progress/{session_id}",
    response_model = ProgressResponse,
    tags           = ["Interview Flow v2"],
)
async def get_progress(session_id: str):
    """Returns live progress. Now includes FSM state."""
    session = ctrl.get_session(session_id)
    if not session:
        raise InterviewAPIError(
            code=ErrorCode.SESSION_NOT_FOUND,
            message=f"Session '{session_id}' not found.",
        )
    fsm  = get_fsm(session_id)
    prog = ctrl.get_progress_dict(session)
    return ProgressResponse(
        session_id          = prog["session_id"],
        domain              = prog["domain"],
        language            = prog["language"],
        state               = InterviewStateEnum(fsm.state.value) if fsm.state.value in [s.value for s in InterviewStateEnum] else InterviewStateEnum.IN_PROGRESS,
        questions_asked     = prog["questions_asked"],
        questions_remaining = prog["questions_remaining"],
        total_questions     = prog["total_questions"],
        current_difficulty  = DifficultyEnum(prog["current_difficulty"]) if prog["current_difficulty"] else None,
    )


# ── 4. SUMMARY ────────────────────────────────────────────────────

@app.get(
    "/interview/summary/{session_id}",
    response_model = SummaryResponse,
    tags           = ["Interview Flow v2"],
)
async def get_summary(session_id: str):
    session = ctrl.get_session(session_id)
    if not session:
        raise InterviewAPIError(code=ErrorCode.SESSION_NOT_FOUND,
                                message=f"Session '{session_id}' not found.")
    fsm = get_fsm(session_id)
    if fsm.state != InterviewState.DONE:
        raise InterviewAPIError(
            code    = ErrorCode.INVALID_STATE,
            message = f"Summary only available when state=done. Current: {fsm.state.value}",
            detail  = {"current_state": fsm.state.value},
        )
    if not session.summary:
        raise InterviewAPIError(code=ErrorCode.SUMMARY_FAILURE,
                                message="Summary not yet generated.")
    return _build_summary_response(session.summary)


# ── 5. ABORT ─────────────────────────────────────────────────────

@app.post(
    "/interview/abort",
    response_model = AbortResponse,
    tags           = ["Interview Flow v2"],
)
async def abort_interview(req: AbortInterviewRequest):
    """Abort with FSM transition → INTERRUPTED."""
    session = ctrl.get_session(req.session_id)
    if not session:
        raise InterviewAPIError(code=ErrorCode.SESSION_NOT_FOUND,
                                message=f"Session '{req.session_id}' not found.")
    fsm = get_fsm(req.session_id)
    if fsm.is_terminal():
        raise InterviewAPIError(
            code    = ErrorCode.ILLEGAL_TRANSITION,
            message = f"Session already in terminal state: {fsm.state.value}",
            detail  = {"current_state": fsm.state.value},
        )
    fsm.trigger(InterviewEvent.ABORT, context={"reason": req.reason})
    ctrl.abort_session(session, reason=req.reason)
    timeout_manager.end_session(req.session_id)
    return AbortResponse(
        session_id = session.session_id,
        aborted    = True,
        message    = f"Session aborted. State: {fsm.state.value}. Reason: {req.reason}",
    )


# ── 6. TIMEOUT EXTENSION ─────────────────────────────────────────

@app.post(
    "/interview/extend",
    response_model = ExtensionResponse,
    tags           = ["Interview Flow v2"],
    summary        = "Request more time on current question",
)
async def extend_timeout(req: ExtensionRequest):
    """
    Candidate requests a time extension on the current question.
    Up to 2 extensions of 60 seconds each are allowed.
    """
    session = ctrl.get_session(req.session_id)
    if not session:
        raise InterviewAPIError(code=ErrorCode.SESSION_NOT_FOUND,
                                message=f"Session '{req.session_id}' not found.")

    result = timeout_manager.request_extension(req.session_id, req.question_number)

    if not result["granted"]:
        raise InterviewAPIError(
            code    = ErrorCode.NO_EXTENSION_REMAINING,
            message = result.get("reason", "Extension not granted."),
            detail  = result,
        )
    return ExtensionResponse(**result)


# ── 7. TIMEOUT STATUS ─────────────────────────────────────────────

@app.get(
    "/interview/timeout/{session_id}",
    response_model = TimeoutStatusResponse,
    tags           = ["Interview Flow v2"],
    summary        = "Get timeout status for session",
)
async def get_timeout_status(session_id: str):
    """Returns current timer status — useful for frontend countdown."""
    if not ctrl.get_session(session_id):
        raise InterviewAPIError(code=ErrorCode.SESSION_NOT_FOUND,
                                message=f"Session '{session_id}' not found.")
    status = timeout_manager.get_status(session_id)
    if "error" in status:
        raise InterviewAPIError(code=ErrorCode.SESSION_NOT_FOUND,
                                message=status["error"])
    return TimeoutStatusResponse(**status)


# ── 8. TRANSITION LOG ─────────────────────────────────────────────

@app.get(
    "/interview/transitions/{session_id}",
    response_model = TransitionLogResponse,
    tags           = ["Debug"],
    summary        = "FSM transition log for a session",
)
async def get_transition_log(session_id: str):
    """Returns full FSM history for debugging and monitoring."""
    if not ctrl.get_session(session_id):
        raise InterviewAPIError(code=ErrorCode.SESSION_NOT_FOUND,
                                message=f"Session '{session_id}' not found.")
    fsm = get_fsm(session_id)
    return TransitionLogResponse(
        session_id    = session_id,
        current_state = fsm.state.value,
        valid_events  = [e.value for e in fsm.get_valid_events()],
        history       = fsm.get_transition_log(),
    )


# ── 9. SESSIONS LIST (debug) ──────────────────────────────────────

@app.get("/interview/sessions", tags=["Debug"])
async def list_sessions():
    return {
        "total": len(ctrl.all_sessions()),
        "sessions": [
            {
                "session_id":      s.session_id,
                "domain":          s.domain,
                "fsm_state":       _state_machines.get(s.session_id, type("X", (), {"state": type("S", (), {"value": "unknown"})()})()).state.value,
                "questions_asked": s.questions_asked,
            }
            for s in ctrl.all_sessions()
        ],
    }
