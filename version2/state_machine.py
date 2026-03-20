"""
state_machine.py
----------------
Modular State-Based Architecture for the Interview Flow Controller.

Each interview session is driven by a finite state machine (FSM).
Every transition is validated before it executes — invalid transitions
raise a clear error rather than silently corrupting state.

States:
    IDLE ──► INTRODUCING ──► QUESTIONING ──► COMPLETING ──► DONE
                                  │
                                  └──► TIMED_OUT
                                  └──► INTERRUPTED
                                  └──► ERROR

Focus Area: Interview & Assessment Flow Controller Optimization
Intern    : Atharva Dilip Bhosale
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, List, Set
import time
import logging

logger = logging.getLogger("state_machine")

# ─────────────────────────────────────────────────────────────────
# STATES
# ─────────────────────────────────────────────────────────────────

class InterviewState(str, Enum):
    IDLE         = "idle"           # Session created, not started
    INTRODUCING  = "introducing"    # Q1 (intro) in progress
    QUESTIONING  = "questioning"    # Q2–Q10 in progress
    COMPLETING   = "completing"     # Q10 answered, generating summary
    DONE         = "done"           # Interview finished cleanly
    TIMED_OUT    = "timed_out"      # Candidate did not respond in time
    INTERRUPTED  = "interrupted"    # Session aborted by user or system
    ERROR        = "error"          # Unrecoverable system error


# ─────────────────────────────────────────────────────────────────
# EVENTS  (triggers that cause state transitions)
# ─────────────────────────────────────────────────────────────────

class InterviewEvent(str, Enum):
    START           = "start"           # Interview begins
    ANSWER_RECEIVED = "answer_received" # Candidate answered
    LAST_ANSWERED   = "last_answered"   # 10th answer received
    SUMMARY_READY   = "summary_ready"   # Summary generation complete
    TIMEOUT         = "timeout"         # No response within deadline
    ABORT           = "abort"           # User/system aborted
    SYSTEM_ERROR    = "system_error"    # Unrecoverable error
    RECOVER         = "recover"         # Retry after transient error


# ─────────────────────────────────────────────────────────────────
# TRANSITION TABLE
# Legal: (current_state, event) → next_state
# ─────────────────────────────────────────────────────────────────

TRANSITIONS: Dict[tuple, InterviewState] = {
    # Normal forward flow
    (InterviewState.IDLE,        InterviewEvent.START):           InterviewState.INTRODUCING,
    (InterviewState.INTRODUCING, InterviewEvent.ANSWER_RECEIVED): InterviewState.QUESTIONING,
    (InterviewState.QUESTIONING, InterviewEvent.ANSWER_RECEIVED): InterviewState.QUESTIONING,
    (InterviewState.QUESTIONING, InterviewEvent.LAST_ANSWERED):   InterviewState.COMPLETING,
    (InterviewState.COMPLETING,  InterviewEvent.SUMMARY_READY):   InterviewState.DONE,

    # Timeout — from any active state
    (InterviewState.INTRODUCING, InterviewEvent.TIMEOUT):         InterviewState.TIMED_OUT,
    (InterviewState.QUESTIONING, InterviewEvent.TIMEOUT):         InterviewState.TIMED_OUT,
    (InterviewState.COMPLETING,  InterviewEvent.TIMEOUT):         InterviewState.TIMED_OUT,

    # Abort — from any active state
    (InterviewState.IDLE,        InterviewEvent.ABORT):           InterviewState.INTERRUPTED,
    (InterviewState.INTRODUCING, InterviewEvent.ABORT):           InterviewState.INTERRUPTED,
    (InterviewState.QUESTIONING, InterviewEvent.ABORT):           InterviewState.INTERRUPTED,
    (InterviewState.COMPLETING,  InterviewEvent.ABORT):           InterviewState.INTERRUPTED,

    # Error — from any active state
    (InterviewState.INTRODUCING, InterviewEvent.SYSTEM_ERROR):    InterviewState.ERROR,
    (InterviewState.QUESTIONING, InterviewEvent.SYSTEM_ERROR):    InterviewState.ERROR,
    (InterviewState.COMPLETING,  InterviewEvent.SYSTEM_ERROR):    InterviewState.ERROR,

    # Recovery — from timed_out back to questioning (if retries remain)
    (InterviewState.TIMED_OUT,   InterviewEvent.RECOVER):         InterviewState.QUESTIONING,
}

# States from which no further transitions are allowed
TERMINAL_STATES: Set[InterviewState] = {
    InterviewState.DONE,
    InterviewState.INTERRUPTED,
    InterviewState.ERROR,
}


# ─────────────────────────────────────────────────────────────────
# TRANSITION RESULT
# ─────────────────────────────────────────────────────────────────

@dataclass
class TransitionResult:
    success:    bool
    from_state: InterviewState
    to_state:   InterviewState
    event:      InterviewEvent
    timestamp:  float = field(default_factory=time.time)
    message:    str   = ""


# ─────────────────────────────────────────────────────────────────
# STATE MACHINE
# ─────────────────────────────────────────────────────────────────

class InterviewStateMachine:
    """
    Finite State Machine for one interview session.
    Thread-safe for single-session use (one FSM per session).
    """

    def __init__(self, session_id: str):
        self.session_id   = session_id
        self.state        = InterviewState.IDLE
        self.history:     List[TransitionResult] = []
        self._on_enter:   Dict[InterviewState, List[Callable]] = {}
        self._on_exit:    Dict[InterviewState, List[Callable]] = {}

    # ── Public API ───────────────────────────────────────────────

    def trigger(self, event: InterviewEvent, context: dict = None) -> TransitionResult:
        """
        Attempt to fire an event and transition to the next state.
        Returns a TransitionResult — always, even on failure.
        Never raises an exception; errors are surfaced in the result.
        """
        from_state = self.state
        key        = (self.state, event)

        # Guard: terminal state
        if self.state in TERMINAL_STATES:
            result = TransitionResult(
                success    = False,
                from_state = from_state,
                to_state   = from_state,
                event      = event,
                message    = f"Session is in terminal state '{self.state.value}'. No further transitions allowed.",
            )
            self.history.append(result)
            logger.warning("[%s] Blocked transition in terminal state: %s + %s",
                           self.session_id, self.state.value, event.value)
            return result

        # Guard: illegal transition
        if key not in TRANSITIONS:
            result = TransitionResult(
                success    = False,
                from_state = from_state,
                to_state   = from_state,
                event      = event,
                message    = f"Illegal transition: {self.state.value} + {event.value}",
            )
            self.history.append(result)
            logger.warning("[%s] Illegal transition: %s + %s",
                           self.session_id, self.state.value, event.value)
            return result

        to_state = TRANSITIONS[key]

        # Fire on_exit hooks
        self._fire_hooks(self._on_exit, self.state, event, context)

        # Transition
        self.state = to_state

        # Fire on_enter hooks
        self._fire_hooks(self._on_enter, self.state, event, context)

        result = TransitionResult(
            success    = True,
            from_state = from_state,
            to_state   = to_state,
            event      = event,
            message    = f"Transitioned: {from_state.value} → {to_state.value}",
        )
        self.history.append(result)
        logger.info("[%s] %s", self.session_id, result.message)
        return result

    def on_enter(self, state: InterviewState):
        """Decorator to register a hook that runs when entering a state."""
        def decorator(fn: Callable):
            self._on_enter.setdefault(state, []).append(fn)
            return fn
        return decorator

    def on_exit(self, state: InterviewState):
        """Decorator to register a hook that runs when leaving a state."""
        def decorator(fn: Callable):
            self._on_exit.setdefault(state, []).append(fn)
            return fn
        return decorator

    def can_trigger(self, event: InterviewEvent) -> bool:
        """Returns True if the event is valid from the current state."""
        return (self.state, event) in TRANSITIONS

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def get_valid_events(self) -> List[InterviewEvent]:
        return [event for (state, event) in TRANSITIONS if state == self.state]

    def get_transition_log(self) -> List[dict]:
        return [
            {
                "from_state": r.from_state.value,
                "to_state":   r.to_state.value,
                "event":      r.event.value,
                "success":    r.success,
                "message":    r.message,
                "timestamp":  r.timestamp,
            }
            for r in self.history
        ]

    # ── Internal ─────────────────────────────────────────────────

    def _fire_hooks(self, hook_map, state, event, context):
        for fn in hook_map.get(state, []):
            try:
                fn(state=state, event=event, context=context or {})
            except Exception as e:
                logger.error("[%s] Hook error on %s: %s", self.session_id, state.value, e)
