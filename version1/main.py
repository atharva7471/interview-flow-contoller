"""
main.py
-------
FastAPI Application — Interview Flow Controller
Intern  : Atharva Dilip Bhosale
Module  : Interview Flow Controller
Project : Domain-Based Intelligent Voice AI Interviewer

Run:
    uvicorn main:app --reload --port 8000

Swagger docs:
    http://localhost:8000/docs
"""

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from models import (
    StartInterviewRequest,  StartInterviewResponse,
    SubmitAnswerRequest,    SubmitAnswerResponse,
    AbortInterviewRequest,  AbortResponse,
    ProgressResponse,       SummaryResponse,
    QAPairResponse,         HealthResponse,
    DifficultyEnum,         InterviewStateEnum,
)

import controller as ctrl
from mock_modules import (
    question_generator,
    tts_speaker,
    summary_generator,
    detect_language,
)


# ─────────────────────────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "Interview Flow Controller API",
    description = (
        "**Module: Interview Flow Controller** | Intern: Atharva Dilip Bhosale\n\n"
        "Drives the structured 5-question AI interview loop with difficulty "
        "progression (Easy → Medium → Hard). Coordinates TTS, STT, GPT and Summary modules."
    ),
    version     = "1.0.0",
    contact     = {"name": "Atharva Dilip Bhosale"},
)

# Allow frontend (Shweta's UI) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["*"],
    allow_methods  = ["*"],
    allow_headers  = ["*"],
)


# ─────────────────────────────────────────────────────────────────
# HELPER — convert internal session summary → Pydantic response
# ─────────────────────────────────────────────────────────────────

def _build_summary_response(summary: dict, session) -> SummaryResponse:
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
# ROUTES
# ─────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model = HealthResponse,
    tags           = ["System"],
    summary        = "Health check",
)
async def health_check():
    """Returns API health status. Use this to confirm the server is running."""
    return HealthResponse(
        status  = "ok",
        version = "1.0.0",
        author  = "Atharva Dilip Bhosale",
    )


# ── 1. START INTERVIEW ────────────────────────────────────────────

@app.post(
    "/interview/start",
    response_model = StartInterviewResponse,
    status_code    = status.HTTP_201_CREATED,
    tags           = ["Interview Flow"],
    summary        = "Start a new interview session",
)
async def start_interview(req: StartInterviewRequest):
    """
    Creates a new interview session and returns the **first question**
    ('Please introduce yourself.') along with the session ID.

    - **domain**: Technical domain (AI/ML, Deep Learning, Web Development, etc.)
    - **language**: Interview language (default: English)
    """
    # Create session (Dipak's session manager would extend this)
    session = ctrl.create_session(domain=req.domain, language=req.language)

    # Q1 is always the fixed intro question
    first_question = ctrl.get_next_question(session, question_generator)

    # Speak question via TTS (Fahima's module)
    tts_speaker(first_question, session.language)

    # Cache so submit_answer always has the pending question text
    session._pending_question = first_question  # type: ignore

    return StartInterviewResponse(
        session_id      = session.session_id,
        first_question  = first_question,
        difficulty      = DifficultyEnum(ctrl.get_difficulty(1).value),
        question_number = 1,
        total_questions = ctrl.TOTAL_QUESTIONS,
        message         = "Interview started. Please answer the question.",
    )


# ── 2. SUBMIT ANSWER & GET NEXT QUESTION ─────────────────────────

@app.post(
    "/interview/answer",
    response_model = SubmitAnswerResponse,
    tags           = ["Interview Flow"],
    summary        = "Submit answer and receive the next question",
)
async def submit_answer(req: SubmitAnswerRequest):
    """
    Records the candidate's answer for the current question and returns
    the **next question** (if any remain) or the **final summary** when
    all 5 questions are complete.

    - **session_id**: Returned from `/interview/start`
    - **answer**: Candidate's spoken/typed answer (STT transcript or raw text)

    The interview **automatically ends** after the 5th answer is submitted.
    """
    # ── Validate session ──────────────────────────────────────────
    session = ctrl.get_session(req.session_id)
    if not session:
        raise HTTPException(
            status_code = status.HTTP_404_NOT_FOUND,
            detail      = f"Session '{req.session_id}' not found.",
        )
    if session.state == ctrl.InterviewState.COMPLETED:
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = "Interview already completed. Fetch /interview/summary.",
        )
    if session.state == ctrl.InterviewState.ABORTED:
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = "Interview was aborted.",
        )

    # ── Language detection (Mohd Aas Khan's module) ───────────────
    detected_lang = detect_language(req.answer)
    if detected_lang != session.language:
        # Update session language to match candidate
        session.language = detected_lang

    # ── Track which question was just answered ─────────────────────
    answered_q_number = session.current_question_number

    # ── Retrieve the question text that was asked ──────────────────
    # _pending_question is always set: at /start for Q1, and after each
    # /answer for Q2-Q5. This is the single source of truth.
    question_text = getattr(session, "_pending_question", ctrl.FIRST_QUESTION)

    # ── Record Q&A + advance counter ─────────────────────────────
    ctrl.record_answer(
        session           = session,
        question_text     = question_text,
        answer_text       = req.answer,
        summary_generator = summary_generator,
    )

    questions_remaining = session.questions_remaining
    interview_complete  = session.is_complete

    # ── Build response ─────────────────────────────────────────────
    if interview_complete:
        # Interview done — attach summary
        summary_data    = session.summary or {}
        summary_resp    = _build_summary_response(summary_data, session)

        return SubmitAnswerResponse(
            session_id           = session.session_id,
            answer_recorded      = True,
            question_number      = answered_q_number,
            questions_remaining  = 0,
            interview_complete   = True,
            next_question        = None,
            next_difficulty      = None,
            next_question_number = None,
            summary              = summary_resp,
            message              = "Interview complete! Summary generated.",
        )
    else:
        # Generate next question
        next_q_num  = session.current_question_number
        next_diff   = ctrl.get_difficulty(next_q_num)
        next_q_text = ctrl.get_next_question(session, question_generator)

        # Cache pending question on session so the next /answer call can store it
        session._pending_question = next_q_text  # type: ignore

        # Speak next question (Fahima's TTS)
        tts_speaker(next_q_text, session.language)

        return SubmitAnswerResponse(
            session_id           = session.session_id,
            answer_recorded      = True,
            question_number      = answered_q_number,
            questions_remaining  = questions_remaining,
            interview_complete   = False,
            next_question        = next_q_text,
            next_difficulty      = DifficultyEnum(next_diff.value),
            next_question_number = next_q_num,
            summary              = None,
            message              = f"Answer recorded. Question {next_q_num}/5 ready.",
        )


# ── 3. GET PROGRESS ───────────────────────────────────────────────
@app.get(
    "/interview/progress/{session_id}",
    response_model = ProgressResponse,
    tags           = ["Interview Flow"],
    summary        = "Get live interview progress",
)
async def get_progress(session_id: str):
    """
    Returns the current state of the interview session.
    Useful for Shweta's frontend UI to render a progress bar.
    """
    session = ctrl.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code = status.HTTP_404_NOT_FOUND,
            detail      = f"Session '{session_id}' not found.",
        )

    prog = ctrl.get_progress_dict(session)
    return ProgressResponse(
        session_id          = prog["session_id"],
        domain              = prog["domain"],
        language            = prog["language"],
        state               = InterviewStateEnum(prog["state"]),
        questions_asked     = prog["questions_asked"],
        questions_remaining = prog["questions_remaining"],
        total_questions     = prog["total_questions"],
        current_difficulty  = (
            DifficultyEnum(prog["current_difficulty"])
            if prog["current_difficulty"] else None
        ),
    )


# ── 4. GET SUMMARY ────────────────────────────────────────────────

@app.get(
    "/interview/summary/{session_id}",
    response_model = SummaryResponse,
    tags           = ["Interview Flow"],
    summary        = "Retrieve the final interview summary",
)
async def get_summary(session_id: str):
    """
    Returns the structured interview summary after the session is complete.
    Vasudha's Storage module stores this in the database.
    """
    session = ctrl.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code = status.HTTP_404_NOT_FOUND,
            detail      = f"Session '{session_id}' not found.",
        )
    if session.state != ctrl.InterviewState.COMPLETED:
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = f"Interview not yet complete (state: {session.state.value}).",
        )
    if not session.summary:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = "Summary not generated. Contact Aleeza's module.",
        )

    return _build_summary_response(session.summary, session)


# ── 5. ABORT INTERVIEW ────────────────────────────────────────────

@app.post(
    "/interview/abort",
    response_model = AbortResponse,
    tags           = ["Interview Flow"],
    summary        = "Abort an in-progress interview",
)
async def abort_interview(req: AbortInterviewRequest):
    """
    Cleanly aborts a session (e.g. candidate disconnects or network error).
    Handled by V Jaya Pradha's Error & Exception Handling module.
    """
    session = ctrl.get_session(req.session_id)
    if not session:
        raise HTTPException(
            status_code = status.HTTP_404_NOT_FOUND,
            detail      = f"Session '{req.session_id}' not found.",
        )
    if session.state in (ctrl.InterviewState.COMPLETED, ctrl.InterviewState.ABORTED):
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = f"Session already in terminal state: {session.state.value}",
        )

    ctrl.abort_session(session, reason=req.reason)

    return AbortResponse(
        session_id = session.session_id,
        aborted    = True,
        message    = f"Interview aborted. Reason: {req.reason}",
    )


# ── 6. LIST ALL SESSIONS  (debug / admin) ─────────────────────────
@app.get(
    "/interview/sessions",
    tags    = ["Debug"],
    summary = "List all active sessions (debug only)",
)
async def list_sessions():
    """
    Returns a summary of all sessions currently in memory.
    For Panga's Logging & Debug Monitoring module.
    """
    sessions = ctrl.all_sessions()
    return {
        "total": len(sessions),
        "sessions": [
            {
                "session_id":      s.session_id,
                "domain":          s.domain,
                "state":           s.state.value,
                "questions_asked": s.questions_asked,
            }
            for s in sessions
        ],
    }