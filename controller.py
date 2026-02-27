"""
controller.py
-------------
Pure domain logic for the Interview Flow Controller.
No FastAPI imports here — keeps business logic cleanly separated.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import time
import uuid


# ─────────────────────────────────────────────────────────────────
# DIFFICULTY MAPPING  (Q1–Q5)
# ─────────────────────────────────────────────────────────────────

class Difficulty(str, Enum):
    EASY   = "easy"
    MEDIUM = "medium"
    HARD   = "hard"


class InterviewState(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    ABORTED     = "aborted"


DIFFICULTY_MAP: Dict[int, Difficulty] = {
    1:  Difficulty.EASY,    # Fixed intro question
    2:  Difficulty.EASY,    # Warm-up
    3:  Difficulty.EASY,    # Basic domain knowledge
    4:  Difficulty.MEDIUM,  # Applied concept
    5:  Difficulty.MEDIUM,  # Real-world usage
    6:  Difficulty.MEDIUM,  # Project / experience
    7:  Difficulty.HARD,    # Deep technical
    8:  Difficulty.HARD,    # System design / trade-offs
    9:  Difficulty.HARD,    # Advanced optimisation
    10: Difficulty.HARD,    # Edge cases / architecture
}

TOTAL_QUESTIONS   = 10
FIRST_QUESTION    = "Please introduce yourself."


def get_difficulty(question_number: int) -> Difficulty:
    """Returns difficulty for question number 1–5. Raises ValueError otherwise."""
    if question_number < 1 or question_number > TOTAL_QUESTIONS:
        raise ValueError(
            f"question_number must be 1–{TOTAL_QUESTIONS}, got {question_number}"
        )
    return DIFFICULTY_MAP[question_number]


# ─────────────────────────────────────────────────────────────────
# DATA MODELS  (plain dataclasses — no Pydantic needed here)
# ─────────────────────────────────────────────────────────────────

@dataclass
class QAPair:
    question_number: int
    difficulty:      Difficulty
    question:        str
    answer:          str = ""
    timestamp:       float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "question_number": self.question_number,
            "difficulty":      self.difficulty.value,
            "question":        self.question,
            "answer":          self.answer,
            "timestamp":       self.timestamp,
        }


@dataclass
class InterviewSession:
    session_id:  str
    domain:      str
    language:    str            = "en"
    state:       InterviewState = InterviewState.NOT_STARTED
    qa_pairs:    List[QAPair]  = field(default_factory=list)
    current_q:   int            = 0        # 0-indexed: 0..4
    start_time:  Optional[float] = None
    end_time:    Optional[float] = None
    summary:     Optional[Dict[str, Any]] = None

    # ── Derived properties ────────────────────────────────────────
    @property
    def is_complete(self) -> bool:
        return self.current_q >= TOTAL_QUESTIONS

    @property
    def questions_asked(self) -> int:
        return self.current_q

    @property
    def questions_remaining(self) -> int:
        return TOTAL_QUESTIONS - self.current_q

    @property
    def current_question_number(self) -> int:
        """1-indexed number of the NEXT question to be asked."""
        return self.current_q + 1

    def get_history(self) -> List[dict]:
        """Serialised Q&A history — passed to GPT for context."""
        return [p.to_dict() for p in self.qa_pairs]


# ─────────────────────────────────────────────────────────────────
# IN-MEMORY SESSION STORE
# ─────────────────────────────────────────────────────────────────
# In production this would be Redis / a database (Dipak's module).
# For now we use a simple dict keyed by session_id.

_sessions: Dict[str, InterviewSession] = {}


def create_session(domain: str, language: str) -> InterviewSession:
    session = InterviewSession(
        session_id = str(uuid.uuid4()),
        domain     = domain,
        language   = language,
        state      = InterviewState.IN_PROGRESS,
        start_time = time.time(),
    )
    _sessions[session.session_id] = session
    return session


def get_session(session_id: str) -> Optional[InterviewSession]:
    return _sessions.get(session_id)


def all_sessions() -> List[InterviewSession]:
    return list(_sessions.values())


# ─────────────────────────────────────────────────────────────────
# CORE CONTROLLER FUNCTIONS
# ─────────────────────────────────────────────────────────────────

def get_next_question(
    session:            InterviewSession,
    question_generator,          # callable from Sarmin's GPT module
) -> str:
    """
    Determines and returns the next question text.
    Q1 is always the fixed intro. Q2-Q5 come from the GPT generator.
    """
    q_num = session.current_question_number

    if q_num == 1:
        return FIRST_QUESTION

    return question_generator(
        domain     = session.domain,
        difficulty = get_difficulty(q_num).value,
        history    = session.get_history(),
        language   = session.language,
    )


def record_answer(
    session:            InterviewSession,
    question_text:      str,
    answer_text:        str,
    summary_generator = None,      # callable from Aleeza's module
) -> None:
    """
    Records a Q&A pair on the session and advances the question counter.
    If this was the 5th answer, finalises the session.
    """
    q_num      = session.current_question_number
    difficulty = get_difficulty(q_num)

    pair = QAPair(
        question_number = q_num,
        difficulty      = difficulty,
        question        = question_text,
        answer          = answer_text,
    )
    session.qa_pairs.append(pair)
    session.current_q += 1                    # ← strict counter advance

    if session.is_complete:
        _finalise_session(session, summary_generator)


def _finalise_session(
    session:            InterviewSession,
    summary_generator = None,
) -> None:
    """Marks session as completed and generates the summary."""
    session.state    = InterviewState.COMPLETED
    session.end_time = time.time()

    if summary_generator:
        session.summary = summary_generator(session)
    else:
        # Default summary if Aleeza's module isn't connected yet
        session.summary = _default_summary(session)


def abort_session(session: InterviewSession, reason: str = "") -> None:
    session.state    = InterviewState.ABORTED
    session.end_time = time.time()


def validate_session_complete(session: InterviewSession) -> bool:
    """
    Returns True only when exactly 5 Q&A pairs exist with non-empty answers.
    Used by K. Srinithya's validation module.
    """
    if len(session.qa_pairs) != TOTAL_QUESTIONS:
        return False
    return all(p.answer.strip() for p in session.qa_pairs)


def get_progress_dict(session: InterviewSession) -> dict:
    """Snapshot of session progress — used by the GET /progress endpoint."""
    next_diff = None
    if not session.is_complete:
        next_diff = get_difficulty(session.current_question_number).value

    return {
        "session_id":          session.session_id,
        "domain":              session.domain,
        "language":            session.language,
        "state":               session.state.value,
        "questions_asked":     session.questions_asked,
        "questions_remaining": session.questions_remaining,
        "total_questions":     TOTAL_QUESTIONS,
        "current_difficulty":  next_diff,
    }


def _default_summary(session: InterviewSession) -> dict:
    return {
        "session_id":  session.session_id,
        "domain":      session.domain,
        "language":    session.language,
        "duration_s":  round((session.end_time or time.time()) - session.start_time, 2),
        "q_count":     len(session.qa_pairs),
        "strengths":   ["Plug in Aleeza's summary module for real analysis"],
        "weaknesses":  [],
        "score":       0,
        "qa_pairs":    session.get_history(),
    }