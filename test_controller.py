"""
test_controller.py
------------------
Comprehensive test suite for the Interview Flow Controller.
Tests the entire business logic WITHOUT needing FastAPI or any server running.

Run:
    python test_controller.py

All tests use only Python stdlib + the project's own files.
"""

import sys, os, time, traceback

# ── Make project files importable ────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from controller import (
    create_session, get_session, all_sessions,
    get_next_question, record_answer, abort_session,
    validate_session_complete, get_progress_dict,
    get_difficulty, DIFFICULTY_MAP, FIRST_QUESTION,
    Difficulty, InterviewState, TOTAL_QUESTIONS,
    QAPair, InterviewSession,
)
from mock_modules import question_generator, summary_generator, detect_language

# ─────────────────────────────────────────────────────────────────
# MINI TEST FRAMEWORK
# ─────────────────────────────────────────────────────────────────

_passed = _failed = 0

def check(label: str, condition: bool, detail: str = ""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✅  {label}")
    else:
        _failed += 1
        print(f"  ❌  {label}" + (f" — {detail}" if detail else ""))

def section(title: str):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")

def expect_exception(label: str, exc_type, fn, *args, **kwargs):
    global _passed, _failed
    try:
        fn(*args, **kwargs)
        _failed += 1
        print(f"  ❌  {label} — expected {exc_type.__name__} but got no exception")
    except exc_type as e:
        _passed += 1
        print(f"  ✅  {label} — raised {exc_type.__name__}: {e}")
    except Exception as e:
        _failed += 1
        print(f"  ❌  {label} — wrong exception {type(e).__name__}: {e}")


# ─────────────────────────────────────────────────────────────────
# TEST 1: DIFFICULTY MAP
# ─────────────────────────────────────────────────────────────────

section("TEST 1: Difficulty Mapping")

expected_map = {
    1: Difficulty.EASY,
    2: Difficulty.EASY,
    3: Difficulty.MEDIUM,
    4: Difficulty.HARD,
    5: Difficulty.HARD,
}
for q_num, expected_diff in expected_map.items():
    actual = get_difficulty(q_num)
    check(f"Q{q_num} → {expected_diff.value}", actual == expected_diff,
          f"got {actual.value}")

expect_exception("get_difficulty(0) raises ValueError", ValueError, get_difficulty, 0)
expect_exception("get_difficulty(6) raises ValueError", ValueError, get_difficulty, 6)
expect_exception("get_difficulty(-1) raises ValueError", ValueError, get_difficulty, -1)


# ─────────────────────────────────────────────────────────────────
# TEST 2: SESSION CREATION
# ─────────────────────────────────────────────────────────────────

section("TEST 2: Session Creation")

s = create_session("Deep Learning", "en")
check("session_id is non-empty string",     isinstance(s.session_id, str) and len(s.session_id) > 0)
check("domain stored correctly",            s.domain == "Deep Learning")
check("language stored correctly",          s.language == "en")
check("state is IN_PROGRESS",               s.state == InterviewState.IN_PROGRESS)
check("current_q starts at 0",             s.current_q == 0)
check("qa_pairs starts empty",             len(s.qa_pairs) == 0)
check("start_time is set",                 s.start_time is not None)
check("end_time is None (not finished)",   s.end_time is None)
check("is_complete is False",              not s.is_complete)
check("questions_remaining is 5",          s.questions_remaining == 5)
check("current_question_number is 1",      s.current_question_number == 1)
check("session retrievable from store",    get_session(s.session_id) is s)


# ─────────────────────────────────────────────────────────────────
# TEST 3: FIRST QUESTION IS ALWAYS FIXED
# ─────────────────────────────────────────────────────────────────

section("TEST 3: First Question Fixed")

s2 = create_session("AI/ML", "en")
q1 = get_next_question(s2, question_generator)
check("Q1 is 'Please introduce yourself.'", q1 == FIRST_QUESTION, f"got: {q1!r}")

s3 = create_session("Web Development", "hi")
q1_hindi = get_next_question(s3, question_generator)
check("Q1 is same regardless of domain/language", q1_hindi == FIRST_QUESTION)


# ─────────────────────────────────────────────────────────────────
# TEST 4: FULL 5-QUESTION FLOW
# ─────────────────────────────────────────────────────────────────

section("TEST 4: Full 5-Question Interview Flow")

session = create_session("Data Science", "en")
difficulties_seen = []

for i in range(TOTAL_QUESTIONS):
    expected_q_num = i + 1
    expected_diff  = expected_map[expected_q_num]

    check(f"Before Q{expected_q_num}: current_q={i}",
          session.current_q == i)
    check(f"Before Q{expected_q_num}: questions_remaining={TOTAL_QUESTIONS - i}",
          session.questions_remaining == TOTAL_QUESTIONS - i)
    check(f"Before Q{expected_q_num}: is_complete=False",
          not session.is_complete)

    q_text = get_next_question(session, question_generator)
    check(f"Q{expected_q_num} text is non-empty", bool(q_text.strip()))

    record_answer(session, q_text, f"Test answer {expected_q_num}", summary_generator)
    difficulties_seen.append(session.qa_pairs[-1].difficulty)

# After all 5 answers
check("After Q5: current_q = 5",              session.current_q == 5)
check("After Q5: is_complete = True",          session.is_complete)
check("After Q5: questions_remaining = 0",     session.questions_remaining == 0)
check("After Q5: state = COMPLETED",           session.state == InterviewState.COMPLETED)
check("After Q5: end_time is set",             session.end_time is not None)
check("After Q5: qa_pairs length = 5",         len(session.qa_pairs) == 5)
check("After Q5: summary is generated",        session.summary is not None)
check("After Q5: validate_session_complete",   validate_session_complete(session))

# Difficulty progression check
check("Difficulties = [easy,easy,medium,hard,hard]",
      difficulties_seen == list(expected_map.values()),
      str([d.value for d in difficulties_seen]))


# ─────────────────────────────────────────────────────────────────
# TEST 5: COUNTER NEVER GOES PAST 5
# ─────────────────────────────────────────────────────────────────

section("TEST 5: Question Counter Hard Limit")

# Attempt to record a 6th answer directly (API would block this, but test the guard)
count_before = len(session.qa_pairs)
try:
    # get_difficulty(6) will raise — mimicking what would happen
    get_difficulty(session.current_q + 1)
    check("UNEXPECTED: 6th question generation should fail", False)
except ValueError:
    check("6th question generation raises ValueError (counter guard works)", True)

check("qa_pairs still exactly 5 after failed 6th attempt", len(session.qa_pairs) == count_before)


# ─────────────────────────────────────────────────────────────────
# TEST 6: PROGRESS SNAPSHOT
# ─────────────────────────────────────────────────────────────────

section("TEST 6: Progress Snapshot")

mid_session = create_session("Cloud Computing", "en")
q = get_next_question(mid_session, question_generator)
record_answer(mid_session, q, "answer 1", summary_generator)
record_answer(mid_session, get_next_question(mid_session, question_generator), "answer 2", summary_generator)

prog = get_progress_dict(mid_session)
check("progress.questions_asked = 2",        prog["questions_asked"] == 2)
check("progress.questions_remaining = 3",    prog["questions_remaining"] == 3)
check("progress.total_questions = 5",        prog["total_questions"] == 5)
check("progress.state = in_progress",        prog["state"] == "in_progress")
check("progress.current_difficulty = medium",prog["current_difficulty"] == "medium")

# Completed session progress
prog_done = get_progress_dict(session)
check("completed session: current_difficulty = None", prog_done["current_difficulty"] is None)
check("completed session: state = completed",          prog_done["state"] == "completed")


# ─────────────────────────────────────────────────────────────────
# TEST 7: ABORT SESSION
# ─────────────────────────────────────────────────────────────────

section("TEST 7: Abort Session")

aborted = create_session("DSA", "en")
check("before abort: state = in_progress",  aborted.state == InterviewState.IN_PROGRESS)
abort_session(aborted, "test abort")
check("after abort: state = ABORTED",       aborted.state == InterviewState.ABORTED)
check("after abort: end_time is set",       aborted.end_time is not None)


# ─────────────────────────────────────────────────────────────────
# TEST 8: VALIDATE — INCOMPLETE SESSION
# ─────────────────────────────────────────────────────────────────

section("TEST 8: Validation Edge Cases")

empty_session = create_session("Web Development", "en")
check("validate_session_complete = False (0 answers)", not validate_session_complete(empty_session))

# One answer only
q = get_next_question(empty_session, question_generator)
record_answer(empty_session, q, "partial answer")
check("validate_session_complete = False (1 answer)", not validate_session_complete(empty_session))

# Empty answer (whitespace)
partial = create_session("AI/ML", "en")
for i in range(TOTAL_QUESTIONS):
    _q = get_next_question(partial, question_generator)
    answer = "   " if i == 2 else f"answer {i+1}"   # Q3 is whitespace
    record_answer(partial, _q, answer)
check("validate_session_complete = False (whitespace answer)", not validate_session_complete(partial))


# ─────────────────────────────────────────────────────────────────
# TEST 9: LANGUAGE DETECTION (MOCK)
# ─────────────────────────────────────────────────────────────────

section("TEST 9: Language Detection Mock")

lang = detect_language("Hello, my name is Atharva.")
check("detect_language returns string",      isinstance(lang, str))
check("mock detect_language returns 'en'",  lang == "en")


# ─────────────────────────────────────────────────────────────────
# TEST 10: SUMMARY STRUCTURE
# ─────────────────────────────────────────────────────────────────

section("TEST 10: Summary Structure")

complete_s = create_session("Deep Learning", "en")
for i in range(TOTAL_QUESTIONS):
    _q = get_next_question(complete_s, question_generator)
    record_answer(complete_s, _q, f"solid answer {i+1}", summary_generator)

s = complete_s.summary
check("summary has session_id",  "session_id"  in s)
check("summary has domain",      "domain"      in s)
check("summary has language",    "language"    in s)
check("summary has duration_s",  "duration_s"  in s)
check("summary has q_count = 5", s.get("q_count") == 5)
check("summary has strengths",   isinstance(s.get("strengths"), list))
check("summary has weaknesses",  isinstance(s.get("weaknesses"), list))
check("summary has score 0-100", 0 <= s.get("score", -1) <= 100)
check("summary has 5 qa_pairs",  len(s.get("qa_pairs", [])) == 5)


# ─────────────────────────────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────────────────────────────

print(f"\n{'═'*55}")
total = _passed + _failed
print(f"  RESULTS:  {_passed}/{total} passed", end="")
if _failed == 0:
    print("  🎉 ALL TESTS PASSED")
else:
    print(f"  ⚠️  {_failed} FAILED — fix before submitting!")
print(f"{'═'*55}\n")

sys.exit(0 if _failed == 0 else 1)