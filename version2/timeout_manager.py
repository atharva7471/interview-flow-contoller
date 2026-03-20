"""
timeout_manager.py
------------------
Timeout Management Logic for the Interview Flow Controller.

Manages per-question deadlines and session-level timeouts.
Tracks how long a candidate has been waiting to answer,
and triggers the state machine's TIMEOUT event when exceeded.

Intern : Atharva Dilip Bhosale
"""

from dataclasses import dataclass, field
from typing import Optional, Dict
import time
import logging

logger = logging.getLogger("timeout_manager")

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────

DEFAULT_QUESTION_TIMEOUT_S = 120     # 2 minutes per question
DEFAULT_SESSION_TIMEOUT_S  = 1800    # 30 minutes total session
MAX_TIMEOUT_EXTENSIONS     = 2       # Candidate can request up to 2 extensions
EXTENSION_DURATION_S       = 60      # Each extension adds 60 seconds


# ─────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────
@dataclass
class QuestionTimer:
    """Tracks the deadline for one question."""
    question_number: int
    started_at:      float = field(default_factory=time.time)
    deadline_s:      float = DEFAULT_QUESTION_TIMEOUT_S
    extensions_used: int   = 0
    answered_at:     Optional[float] = None

    @property
    def elapsed(self) -> float:
        end = self.answered_at or time.time()
        return round(end - self.started_at, 2)

    @property
    def remaining(self) -> float:
        if self.answered_at:
            return 0.0
        return max(0.0, round(self.deadline_s - self.elapsed, 2))

    @property
    def is_expired(self) -> bool:
        return not self.answered_at and self.elapsed > self.deadline_s

    @property
    def can_extend(self) -> bool:
        return self.extensions_used < MAX_TIMEOUT_EXTENSIONS

    def extend(self) -> bool:
        """Add an extension. Returns True if granted, False if limit reached."""
        if not self.can_extend:
            return False
        self.deadline_s      += EXTENSION_DURATION_S
        self.extensions_used += 1
        logger.info("Q%d timer extended (%d/%d). New deadline: %.0fs",
                    self.question_number, self.extensions_used,
                    MAX_TIMEOUT_EXTENSIONS, self.deadline_s)
        return True

    def mark_answered(self) -> None:
        self.answered_at = time.time()

    def to_dict(self) -> dict:
        return {
            "question_number": self.question_number,
            "started_at":      self.started_at,
            "deadline_s":      self.deadline_s,
            "elapsed":         self.elapsed,
            "remaining":       self.remaining,
            "is_expired":      self.is_expired,
            "extensions_used": self.extensions_used,
        }


@dataclass
class SessionTimeoutTracker:
    """Tracks the overall session-level deadline."""
    session_id:       str
    started_at:       float = field(default_factory=time.time)
    deadline_s:       float = DEFAULT_SESSION_TIMEOUT_S
    question_timers:  Dict[int, QuestionTimer] = field(default_factory=dict)

    @property
    def total_elapsed(self) -> float:
        return round(time.time() - self.started_at, 2)

    @property
    def session_remaining(self) -> float:
        return max(0.0, round(self.deadline_s - self.total_elapsed, 2))

    @property
    def is_session_expired(self) -> bool:
        return self.total_elapsed > self.deadline_s

    @property
    def current_timer(self) -> Optional[QuestionTimer]:
        if not self.question_timers:
            return None
        return self.question_timers[max(self.question_timers)]


# ─────────────────────────────────────────────────────────────────
# TIMEOUT MANAGER
# ─────────────────────────────────────────────────────────────────

class TimeoutManager:
    """
    Central manager for all session and question-level timeouts.
    Designed to be polled by the /interview/status endpoint.
    """

    def __init__(
        self,
        question_timeout_s: float = DEFAULT_QUESTION_TIMEOUT_S,
        session_timeout_s:  float = DEFAULT_SESSION_TIMEOUT_S,
    ):
        self.question_timeout_s = question_timeout_s
        self.session_timeout_s  = session_timeout_s
        self._trackers: Dict[str, SessionTimeoutTracker] = {}

    # ── Session lifecycle ────────────────────────────────────────

    def start_session(self, session_id: str) -> SessionTimeoutTracker:
        tracker = SessionTimeoutTracker(
            session_id = session_id,
            deadline_s = self.session_timeout_s,
        )
        self._trackers[session_id] = tracker
        logger.info("Session timeout started: %s (%.0fs)", session_id, self.session_timeout_s)
        return tracker

    def end_session(self, session_id: str) -> None:
        self._trackers.pop(session_id, None)
        logger.info("Session timeout cleared: %s", session_id)

    # ── Question timers ──────────────────────────────────────────

    def start_question_timer(self, session_id: str, question_number: int) -> QuestionTimer:
        tracker = self._get_tracker(session_id)
        timer   = QuestionTimer(
            question_number = question_number,
            deadline_s      = self.question_timeout_s,
        )
        tracker.question_timers[question_number] = timer
        logger.info("Q%d timer started for %s (%.0fs)",
                    question_number, session_id, self.question_timeout_s)
        return timer

    def record_answer(self, session_id: str, question_number: int) -> Optional[QuestionTimer]:
        tracker = self._get_tracker(session_id)
        if tracker is None:
            return None
        timer = tracker.question_timers.get(question_number)
        if timer:
            timer.mark_answered()
            logger.info("Q%d answered in %.2fs for session %s",
                        question_number, timer.elapsed, session_id)
        return timer

    def request_extension(self, session_id: str, question_number: int) -> dict:
        """
        Candidate requests more time on the current question.
        Returns a result dict indicating if extension was granted.
        """
        tracker = self._get_tracker(session_id)
        if tracker is None:
            return {"granted": False, "reason": "Session not found"}

        timer = tracker.question_timers.get(question_number)
        if timer is None:
            return {"granted": False, "reason": "Timer not found for this question"}
        if timer.is_expired:
            return {"granted": False, "reason": "Question already timed out"}
        if not timer.can_extend:
            return {"granted": False, "reason": f"Maximum {MAX_TIMEOUT_EXTENSIONS} extensions already used"}

        granted = timer.extend()
        return {
            "granted":         granted,
            "extensions_used": timer.extensions_used,
            "extensions_max":  MAX_TIMEOUT_EXTENSIONS,
            "new_remaining_s": timer.remaining,
            "reason":          "Extension granted" if granted else "Could not extend",
        }

    # ── Timeout checks ───────────────────────────────────────────

    def check_question_timeout(self, session_id: str, question_number: int) -> bool:
        """Returns True if the current question timer has expired."""
        tracker = self._get_tracker(session_id)
        if tracker is None:
            return False
        timer = tracker.question_timers.get(question_number)
        return timer.is_expired if timer else False

    def check_session_timeout(self, session_id: str) -> bool:
        """Returns True if the overall session has expired."""
        tracker = self._get_tracker(session_id)
        return tracker.is_session_expired if tracker else False

    # ── Status snapshot ──────────────────────────────────────────
    def get_status(self, session_id: str) -> dict:
        tracker = self._get_tracker(session_id)
        if tracker is None:
            return {"error": "Session not tracked"}

        current = tracker.current_timer
        return {
            "session_id":             session_id,
            "session_elapsed_s":      tracker.total_elapsed,
            "session_remaining_s":    tracker.session_remaining,
            "session_expired":        tracker.is_session_expired,
            "current_question_timer": current.to_dict() if current else None,
            "question_history":       [t.to_dict() for t in tracker.question_timers.values()],
        }

    def get_average_response_time(self, session_id: str) -> Optional[float]:
        """Average time taken per answered question (seconds)."""
        tracker = self._get_tracker(session_id)
        if tracker is None:
            return None
        answered = [t for t in tracker.question_timers.values() if t.answered_at]
        if not answered:
            return None
        return round(sum(t.elapsed for t in answered) / len(answered), 2)

    # ── Internal ─────────────────────────────────────────────────

    def _get_tracker(self, session_id: str) -> Optional[SessionTimeoutTracker]:
        return self._trackers.get(session_id)


# ── Module-level singleton (shared across all sessions) ──────────
timeout_manager = TimeoutManager()
