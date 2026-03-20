"""
test_v2.py
----------
Test suite for Interview Flow Controller v2 optimizations.
Covers: state machine, timeout manager, error handler.

Run:
    python test_v2.py
"""

import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from state_machine import (
    InterviewStateMachine, InterviewState, InterviewEvent,
    TRANSITIONS, TERMINAL_STATES
)
from timeout_manager import (
    TimeoutManager, QuestionTimer,
    DEFAULT_QUESTION_TIMEOUT_S, MAX_TIMEOUT_EXTENSIONS, EXTENSION_DURATION_S
)
from error_handler import (
    InterviewAPIError, ErrorCode, RETRYABLE, build_error_response,
    get_idempotent_response, cache_idempotent_response, purge_expired_idempotency_keys,
    safe_call
)

# ── Mini test framework ──────────────────────────────────────────
_passed = _failed = 0

def check(label, condition, detail=""):
    global _passed, _failed
    if condition:
        _passed += 1; print(f"  ✅  {label}")
    else:
        _failed += 1; print(f"  ❌  {label}" + (f" — {detail}" if detail else ""))

def section(title):
    print(f"\n{'─'*60}\n  {title}\n{'─'*60}")

def expect_err(label, exc_type, fn, *a, **kw):
    global _passed, _failed
    try:
        fn(*a, **kw)
        _failed += 1; print(f"  ❌  {label} — no exception raised")
    except exc_type as e:
        _passed += 1; print(f"  ✅  {label}")
    except Exception as e:
        _failed += 1; print(f"  ❌  {label} — wrong exception {type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════
# TEST 1 — STATE MACHINE: NORMAL FLOW
# ═════════════════════════════════════════════════════════════════
section("TEST 1: State Machine — Normal Flow")

fsm = InterviewStateMachine("sess-001")
check("Initial state is IDLE",       fsm.state == InterviewState.IDLE)
check("Not terminal at IDLE",        not fsm.is_terminal())

r = fsm.trigger(InterviewEvent.START)
check("START succeeds",              r.success)
check("State → INTRODUCING",        fsm.state == InterviewState.INTRODUCING)

r = fsm.trigger(InterviewEvent.ANSWER_RECEIVED)
check("ANSWER_RECEIVED succeeds",   r.success)
check("State → QUESTIONING",        fsm.state == InterviewState.QUESTIONING)

# Multiple answers during questioning
for i in range(7):
    r = fsm.trigger(InterviewEvent.ANSWER_RECEIVED)
check("7 more answers stay QUESTIONING", fsm.state == InterviewState.QUESTIONING)

r = fsm.trigger(InterviewEvent.LAST_ANSWERED)
check("LAST_ANSWERED succeeds",     r.success)
check("State → COMPLETING",        fsm.state == InterviewState.COMPLETING)

r = fsm.trigger(InterviewEvent.SUMMARY_READY)
check("SUMMARY_READY succeeds",    r.success)
check("State → DONE",              fsm.state == InterviewState.DONE)
check("DONE is terminal",          fsm.is_terminal())

r = fsm.trigger(InterviewEvent.ANSWER_RECEIVED)
check("No transition from DONE",   not r.success)
check("State stays DONE",          fsm.state == InterviewState.DONE)


# ═════════════════════════════════════════════════════════════════
# TEST 2 — STATE MACHINE: FAIL-SAFE TRANSITIONS
# ═════════════════════════════════════════════════════════════════
section("TEST 2: State Machine — Fail-Safe Transitions")

# Timeout
fsm2 = InterviewStateMachine("sess-002")
fsm2.trigger(InterviewEvent.START)
fsm2.trigger(InterviewEvent.ANSWER_RECEIVED)  # now QUESTIONING
r = fsm2.trigger(InterviewEvent.TIMEOUT)
check("TIMEOUT from QUESTIONING succeeds",   r.success)
check("State → TIMED_OUT",                   fsm2.state == InterviewState.TIMED_OUT)
check("TIMED_OUT not terminal (recoverable)",    not fsm2.is_terminal())

# Recover from TIMED_OUT
r = fsm2.trigger(InterviewEvent.RECOVER)
check("RECOVER from TIMED_OUT succeeds",     r.success)
check("State → QUESTIONING after recover",   fsm2.state == InterviewState.QUESTIONING)

# Abort
fsm3 = InterviewStateMachine("sess-003")
fsm3.trigger(InterviewEvent.START)
r = fsm3.trigger(InterviewEvent.ABORT)
check("ABORT from INTRODUCING succeeds",     r.success)
check("State → INTERRUPTED",                fsm3.state == InterviewState.INTERRUPTED)
check("INTERRUPTED is terminal",            fsm3.is_terminal())

r = fsm3.trigger(InterviewEvent.START)
check("No transition from INTERRUPTED",     not r.success)

# Error
fsm4 = InterviewStateMachine("sess-004")
fsm4.trigger(InterviewEvent.START)
fsm4.trigger(InterviewEvent.ANSWER_RECEIVED)
r = fsm4.trigger(InterviewEvent.SYSTEM_ERROR)
check("SYSTEM_ERROR from QUESTIONING",      r.success)
check("State → ERROR",                      fsm4.state == InterviewState.ERROR)

# Illegal transition
fsm5 = InterviewStateMachine("sess-005")
r = fsm5.trigger(InterviewEvent.ANSWER_RECEIVED)  # IDLE → can't answer
check("Illegal: ANSWER from IDLE fails",   not r.success)
check("State stays IDLE after illegal",    fsm5.state == InterviewState.IDLE)


# ═════════════════════════════════════════════════════════════════
# TEST 3 — STATE MACHINE: HOOKS
# ═════════════════════════════════════════════════════════════════
section("TEST 3: State Machine — on_enter / on_exit Hooks")

fsm6   = InterviewStateMachine("sess-006")
log    = []

@fsm6.on_enter(InterviewState.INTRODUCING)
def on_intro(**kwargs):
    log.append("entered_introducing")

@fsm6.on_exit(InterviewState.INTRODUCING)
def on_exit_intro(**kwargs):
    log.append("exited_introducing")

fsm6.trigger(InterviewEvent.START)
check("on_enter(INTRODUCING) fired",  "entered_introducing" in log)

fsm6.trigger(InterviewEvent.ANSWER_RECEIVED)
check("on_exit(INTRODUCING) fired",   "exited_introducing" in log)

# Transition log
tlog = fsm6.get_transition_log()
check("Transition log has 2 entries", len(tlog) == 2)
check("Log entries have required keys",
      all("from_state" in e and "to_state" in e and "success" in e for e in tlog))

# Valid events
valid = fsm6.get_valid_events()
check("QUESTIONING has valid events", len(valid) > 0)
check("ANSWER_RECEIVED is valid",     InterviewEvent.ANSWER_RECEIVED in valid)


# ═════════════════════════════════════════════════════════════════
# TEST 4 — TIMEOUT MANAGER: TIMER BASICS
# ═════════════════════════════════════════════════════════════════
section("TEST 4: Timeout Manager — Timer Basics")

tm = TimeoutManager(question_timeout_s=5, session_timeout_s=30)

tracker = tm.start_session("t-001")
check("Session tracker created",         tracker is not None)
check("Session not expired yet",         not tm.check_session_timeout("t-001"))

timer = tm.start_question_timer("t-001", 1)
check("Question timer created",          timer is not None)
check("Q1 timer not expired initially",  not tm.check_question_timeout("t-001", 1))
check("Q1 remaining > 0",               timer.remaining > 0)

tm.record_answer("t-001", 1)
check("Answered timer: remaining = 0",   timer.remaining == 0)
check("Answered timer not expired",      not timer.is_expired)
check("Elapsed recorded",               timer.elapsed >= 0)

# Expired timer simulation
timer2 = tm.start_question_timer("t-001", 2)
timer2.started_at = time.time() - 10   # simulate 10s elapsed on 5s deadline
check("Q2 expired after simulated time", timer2.is_expired)
check("check_question_timeout returns True", tm.check_question_timeout("t-001", 2))


# ═════════════════════════════════════════════════════════════════
# TEST 5 — TIMEOUT MANAGER: EXTENSIONS
# ═════════════════════════════════════════════════════════════════
section("TEST 5: Timeout Manager — Extensions")

tm2 = TimeoutManager(question_timeout_s=60, session_timeout_s=600)
tm2.start_session("t-002")
tm2.start_question_timer("t-002", 1)

# First extension
res1 = tm2.request_extension("t-002", 1)
check("First extension granted",          res1["granted"])
check("extensions_used = 1",             res1["extensions_used"] == 1)
check("new deadline extended",            res1["new_remaining_s"] > 60)

# Second extension
res2 = tm2.request_extension("t-002", 1)
check("Second extension granted",         res2["granted"])
check("extensions_used = 2",             res2["extensions_used"] == 2)

# Third extension (should fail)
res3 = tm2.request_extension("t-002", 1)
check("Third extension denied",           not res3["granted"])

# Status snapshot
status = tm2.get_status("t-002")
check("status has session_elapsed_s",     "session_elapsed_s"   in status)
check("status has session_remaining_s",   "session_remaining_s" in status)
check("status has current_question_timer","current_question_timer" in status)

# Unknown session
check("Unknown session returns error",
      "error" in tm2.get_status("no-such-id"))


# ═════════════════════════════════════════════════════════════════
# TEST 6 — ERROR HANDLER: STRUCTURE & RETRYABILITY
# ═════════════════════════════════════════════════════════════════
section("TEST 6: Error Handler — Structure & Retryability")

# build_error_response shape
body = build_error_response(ErrorCode.SESSION_NOT_FOUND, "not found", {"id": "x"})
check("error_code in response",    "error_code"  in body)
check("message in response",       "message"     in body)
check("detail in response",        "detail"      in body)
check("retryable in response",     "retryable"   in body)
check("timestamp in response",     "timestamp"   in body)

# SESSION_NOT_FOUND is not retryable
check("SESSION_NOT_FOUND not retryable",  not body["retryable"])
check("No retry_after on non-retryable",  "retry_after_s" not in body)

# GPT_FAILURE is retryable
body2 = build_error_response(ErrorCode.GPT_FAILURE, "gpt failed")
check("GPT_FAILURE is retryable",         body2["retryable"])
check("retry_after_s present",            "retry_after_s" in body2)

# Spot check retryability map
check("TTS_FAILURE retryable",       RETRYABLE[ErrorCode.TTS_FAILURE])
check("ANSWER_EMPTY not retryable",  not RETRYABLE[ErrorCode.ANSWER_EMPTY])
check("RATE_LIMITED retryable",      RETRYABLE[ErrorCode.RATE_LIMITED])
check("SESSION_ABORTED not retryable", not RETRYABLE[ErrorCode.SESSION_ABORTED])


# ═════════════════════════════════════════════════════════════════
# TEST 7 — ERROR HANDLER: InterviewAPIError
# ═════════════════════════════════════════════════════════════════
section("TEST 7: Error Handler — InterviewAPIError")

try:
    raise InterviewAPIError(
        code    = ErrorCode.SESSION_NOT_FOUND,
        message = "Session x not found",
        detail  = {"session_id": "x"},
    )
except InterviewAPIError as e:
    check("code is ErrorCode",              isinstance(e.code, ErrorCode))
    check("message is string",              isinstance(e.message, str))
    check("detail is dict",                 isinstance(e.detail, dict))
    check("detail has session_id",          "session_id" in e.detail)
    check("str(e) is message",              str(e) == "Session x not found")


# ═════════════════════════════════════════════════════════════════
# TEST 8 — ERROR HANDLER: safe_call
# ═════════════════════════════════════════════════════════════════
section("TEST 8: Error Handler — safe_call Wrapper")

def good_fn(x): return x * 2
def bad_fn(x):  raise RuntimeError("external failure")

result = safe_call(good_fn, 5, error_code=ErrorCode.GPT_FAILURE)
check("safe_call returns result for good fn", result == 10)

try:
    safe_call(bad_fn, 5, error_code=ErrorCode.GPT_FAILURE, label="GPT")
    check("safe_call should have raised", False)
except InterviewAPIError as e:
    check("safe_call wraps exception as InterviewAPIError", True)
    check("wrapped error code is GPT_FAILURE",              e.code == ErrorCode.GPT_FAILURE)
    check("detail has module key",                          "module" in e.detail)


# ═════════════════════════════════════════════════════════════════
# TEST 9 — IDEMPOTENCY
# ═════════════════════════════════════════════════════════════════
section("TEST 9: Idempotency Cache")

key = "idem-key-001"
check("Cache miss returns None",        get_idempotent_response(key) is None)

cache_idempotent_response(key, {"result": "ok"}, ttl_s=300)
cached = get_idempotent_response(key)
check("Cache hit returns dict",         cached is not None)
check("Cached response is correct",     cached["response"]["result"] == "ok")
check("Cached entry has expires_at",    "expires_at" in cached)

# Expired key
exp_key = "exp-key-001"
cache_idempotent_response(exp_key, {"x": 1}, ttl_s=0)
import time; time.sleep(0.05)
purged = purge_expired_idempotency_keys()
check("Expired key purged",             purged >= 1)
check("Purged key is gone",             get_idempotent_response(exp_key) is None)


# ═════════════════════════════════════════════════════════════════
# TEST 10 — TRANSITION TABLE COMPLETENESS
# ═════════════════════════════════════════════════════════════════
section("TEST 10: Transition Table Completeness")

check("TRANSITIONS dict is not empty",      len(TRANSITIONS) > 0)
check("TERMINAL_STATES has 3 states",       len(TERMINAL_STATES) == 3)
check("DONE is terminal",                   InterviewState.DONE         in TERMINAL_STATES)
check("INTERRUPTED is terminal",            InterviewState.INTERRUPTED  in TERMINAL_STATES)
check("TIMED_OUT is NOT terminal (recoverable)", InterviewState.TIMED_OUT not in TERMINAL_STATES)
check("ERROR is terminal",                  InterviewState.ERROR        in TERMINAL_STATES)
check("IDLE is NOT terminal",               InterviewState.IDLE         not in TERMINAL_STATES)
check("QUESTIONING is NOT terminal",        InterviewState.QUESTIONING  not in TERMINAL_STATES)

# All transitions reference valid states and events
for (state, event), next_state in TRANSITIONS.items():
    check(f"Transition ({state.value},{event.value}) → valid",
          isinstance(next_state, InterviewState))


# ═════════════════════════════════════════════════════════════════
# RESULTS
# ═════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
total = _passed + _failed
print(f"  RESULTS:  {_passed}/{total} passed", end="")
print("  🎉 ALL TESTS PASSED" if _failed == 0 else f"  ⚠️  {_failed} FAILED")
print(f"{'='*60}\n")

sys.exit(0 if _failed == 0 else 1)
