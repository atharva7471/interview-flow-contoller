"""
test_controller.py
------------------
Comprehensive test suite for the Interview Flow Controller (10 questions).
Tests the entire business logic WITHOUT needing FastAPI or any server running.

Run:
    python test_controller.py
"""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from controller import (
    create_session, get_session, all_sessions,
    get_next_question, record_answer, abort_session,
    validate_session_complete, get_progress_dict,
    get_difficulty, DIFFICULTY_MAP, FIRST_QUESTION,
    Difficulty, InterviewState, TOTAL_QUESTIONS,
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
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")

def expect_exception(label, exc_type, fn, *args, **kwargs):
    global _passed, _failed
    try:
        fn(*args, **kwargs)
        _failed += 1
        print(f"  ❌  {label} — expected {exc_type.__name__} but no exception raised")
    except exc_type as e:
        _passed += 1
        print(f"  ✅  {label} — raised {exc_type.__name__}: {e}")
    except Exception as e:
        _failed += 1
        print(f"  ❌  {label} — wrong exception {type(e).__name__}: {e}")


# ─────────────────────────────────────────────────────────────────
# EXPECTED DIFFICULTY MAP  (10 questions)
# ─────────────────────────────────────────────────────────────────

EXPECTED_MAP = {
    1:  Difficulty.EASY,
    2:  Difficulty.EASY,
    3:  Difficulty.EASY,
    4:  Difficulty.MEDIUM,
    5:  Difficulty.MEDIUM,
    6:  Difficulty.MEDIUM,
    7:  Difficulty.HARD,
    8:  Difficulty.HARD,
    9:  Difficulty.HARD,
    10: Difficulty.HARD,
}


# ─────────────────────────────────────────────────────────────────
# TEST 1 — DIFFICULTY MAP
# ─────────────────────────────────────────────────────────────────

section("TEST 1: Difficulty Mapping (10 Questions)")

check("TOTAL_QUESTIONS is 10", TOTAL_QUESTIONS == 10, f"got {TOTAL_QUESTIONS}")

for q_num, expected in EXPECTED_MAP.items():
    actual = get_difficulty(q_num)
    check(f"Q{q_num:>2} -> {expected.value}", actual == expected, f"got {actual.value}")

expect_exception("get_difficulty(0)  raises ValueError", ValueError, get_difficulty, 0)
expect_exception("get_difficulty(11) raises ValueError", ValueError, get_difficulty, 11)
expect_exception("get_difficulty(-1) raises ValueError", ValueError, get_difficulty, -1)


# ─────────────────────────────────────────────────────────────────
# TEST 2 — SESSION CREATION
# ─────────────────────────────────────────────────────────────────

section("TEST 2: Session Creation")

s = create_session("Deep Learning", "en")
check("session_id is non-empty string",   isinstance(s.session_id, str) and len(s.session_id) > 0)
check("domain stored correctly",          s.domain == "Deep Learning")
check("language stored correctly",        s.language == "en")
check("state is IN_PROGRESS",             s.state == InterviewState.IN_PROGRESS)
check("current_q starts at 0",           s.current_q == 0)
check("qa_pairs starts empty",           len(s.qa_pairs) == 0)
check("start_time is set",               s.start_time is not None)
check("end_time is None",                s.end_time is None)
check("is_complete is False",            not s.is_complete)
check("questions_remaining is 10",       s.questions_remaining == 10)
check("current_question_number is 1",    s.current_question_number == 1)
check("session retrievable from store",  get_session(s.session_id) is s)


# ─────────────────────────────────────────────────────────────────
# TEST 3 — FIRST QUESTION ALWAYS FIXED
# ─────────────────────────────────────────────────────────────────

section("TEST 3: First Question Is Always Fixed")

s2 = create_session("AI/ML", "en")
q1 = get_next_question(s2, question_generator)
check("Q1 is 'Please introduce yourself.'", q1 == FIRST_QUESTION, f"got: {q1!r}")

s3 = create_session("Web Development", "hi")
check("Q1 same for any domain/language", get_next_question(s3, question_generator) == FIRST_QUESTION)


# ─────────────────────────────────────────────────────────────────
# TEST 4 — FULL 10-QUESTION FLOW
# ─────────────────────────────────────────────────────────────────

section("TEST 4: Full 10-Question Interview Flow")

session = create_session("Data Science", "en")
difficulties_seen = []

for i in range(TOTAL_QUESTIONS):
    expected_q_num = i + 1
    expected_diff  = EXPECTED_MAP[expected_q_num]

    check(f"Before Q{expected_q_num:>2}: current_q = {i}",
          session.current_q == i)
    check(f"Before Q{expected_q_num:>2}: remaining = {TOTAL_QUESTIONS - i}",
          session.questions_remaining == TOTAL_QUESTIONS - i)
    check(f"Before Q{expected_q_num:>2}: is_complete = False",
          not session.is_complete)

    q_text = get_next_question(session, question_generator)
    check(f"Q{expected_q_num:>2} text is non-empty", bool(q_text.strip()))
    record_answer(session, q_text, f"Test answer {expected_q_num}", summary_generator)
    difficulties_seen.append(session.qa_pairs[-1].difficulty)

check("After Q10: current_q = 10",           session.current_q == 10)
check("After Q10: is_complete = True",        session.is_complete)
check("After Q10: questions_remaining = 0",   session.questions_remaining == 0)
check("After Q10: state = COMPLETED",         session.state == InterviewState.COMPLETED)
check("After Q10: end_time is set",           session.end_time is not None)
check("After Q10: qa_pairs length = 10",      len(session.qa_pairs) == 10)
check("After Q10: summary is generated",      session.summary is not None)
check("After Q10: validate_session_complete", validate_session_complete(session))
check("Difficulty sequence correct",
      difficulties_seen == list(EXPECTED_MAP.values()),
      str([d.value for d in difficulties_seen]))

easy_count   = difficulties_seen.count(Difficulty.EASY)
medium_count = difficulties_seen.count(Difficulty.MEDIUM)
hard_count   = difficulties_seen.count(Difficulty.HARD)
check("Easy questions = 3",   easy_count   == 3, f"got {easy_count}")
check("Medium questions = 3", medium_count == 3, f"got {medium_count}")
check("Hard questions = 4",   hard_count   == 4, f"got {hard_count}")


# ─────────────────────────────────────────────────────────────────
# TEST 5 — COUNTER HARD LIMIT (no Q11)
# ─────────────────────────────────────────────────────────────────

section("TEST 5: Counter Hard Limit (No Q11)")

count_before = len(session.qa_pairs)
try:
    get_difficulty(session.current_q + 1)
    check("UNEXPECTED: should have raised ValueError", False)
except ValueError:
    check("Q11 attempt raises ValueError (counter guard works)", True)

check("qa_pairs locked at 10 after failed Q11 attempt",
      len(session.qa_pairs) == count_before)


# ─────────────────────────────────────────────────────────────────
# TEST 6 — PROGRESS SNAPSHOT AT KEY STAGES
# ─────────────────────────────────────────────────────────────────

section("TEST 6: Progress Snapshot at Key Stages")

mid = create_session("Cloud Computing", "en")

# After Q1 — next should be easy (Q2)
record_answer(mid, get_next_question(mid, question_generator), "a1", summary_generator)
prog = get_progress_dict(mid)
check("After Q1: questions_asked = 1",      prog["questions_asked"] == 1)
check("After Q1: remaining = 9",            prog["questions_remaining"] == 9)
check("After Q1: next difficulty = easy",   prog["current_difficulty"] == "easy")

# After Q3 — next should be medium (Q4)
for i in range(2):
    record_answer(mid, get_next_question(mid, question_generator), f"a{i+2}", summary_generator)
prog = get_progress_dict(mid)
check("After Q3: questions_asked = 3",      prog["questions_asked"] == 3)
check("After Q3: next difficulty = medium", prog["current_difficulty"] == "medium")

# After Q6 — next should be hard (Q7)
for i in range(3):
    record_answer(mid, get_next_question(mid, question_generator), f"a{i+4}", summary_generator)
prog = get_progress_dict(mid)
check("After Q6: questions_asked = 6",      prog["questions_asked"] == 6)
check("After Q6: next difficulty = hard",   prog["current_difficulty"] == "hard")

# Finish remaining 4
for i in range(4):
    record_answer(mid, get_next_question(mid, question_generator), f"a{i+7}", summary_generator)
prog_done = get_progress_dict(mid)
check("Completed: state = completed",           prog_done["state"] == "completed")
check("Completed: current_difficulty = None",   prog_done["current_difficulty"] is None)
check("Completed: questions_remaining = 0",     prog_done["questions_remaining"] == 0)


# ─────────────────────────────────────────────────────────────────
# TEST 7 — ABORT SESSION
# ─────────────────────────────────────────────────────────────────

section("TEST 7: Abort Session")

aborted = create_session("DSA", "en")
check("Before abort: state = in_progress", aborted.state == InterviewState.IN_PROGRESS)
abort_session(aborted, "test abort")
check("After abort: state = ABORTED",      aborted.state == InterviewState.ABORTED)
check("After abort: end_time is set",      aborted.end_time is not None)


# ─────────────────────────────────────────────────────────────────
# TEST 8 — VALIDATION EDGE CASES
# ─────────────────────────────────────────────────────────────────

section("TEST 8: Validation Edge Cases")

empty = create_session("Web Development", "en")
check("0 answers -> validate = False", not validate_session_complete(empty))

record_answer(empty, get_next_question(empty, question_generator), "one answer")
check("1 answer  -> validate = False", not validate_session_complete(empty))

# Whitespace-only answer at Q6
ws = create_session("AI/ML", "en")
for i in range(TOTAL_QUESTIONS):
    _q = get_next_question(ws, question_generator)
    record_answer(ws, _q, "   " if i == 5 else f"answer {i+1}")
check("Whitespace answer at Q6 -> validate = False", not validate_session_complete(ws))


# ─────────────────────────────────────────────────────────────────
# TEST 9 — LANGUAGE DETECTION MOCK
# ─────────────────────────────────────────────────────────────────

section("TEST 9: Language Detection Mock")

lang = detect_language("Hello, my name is Atharva.")
check("detect_language returns a string", isinstance(lang, str))
check("mock returns 'en'",               lang == "en")


# ─────────────────────────────────────────────────────────────────
# TEST 10 — SUMMARY STRUCTURE
# ─────────────────────────────────────────────────────────────────

section("TEST 10: Summary Structure")

full = create_session("Deep Learning", "en")
for i in range(TOTAL_QUESTIONS):
    _q = get_next_question(full, question_generator)
    record_answer(full, _q, f"solid answer {i+1}", summary_generator)

s = full.summary
check("summary has session_id",  "session_id"  in s)
check("summary has domain",      "domain"      in s)
check("summary has language",    "language"    in s)
check("summary has duration_s",  "duration_s"  in s)
check("summary q_count = 10",    s.get("q_count") == 10)
check("summary has strengths",   isinstance(s.get("strengths"), list))
check("summary has weaknesses",  isinstance(s.get("weaknesses"), list))
check("summary score 0-100",     0 <= s.get("score", -1) <= 100)
check("summary has 10 qa_pairs", len(s.get("qa_pairs", [])) == 10)


# ─────────────────────────────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────────────────────────────

print(f"\n{'='*60}")
total = _passed + _failed
print(f"  RESULTS:  {_passed}/{total} passed", end="")
print("  ALL TESTS PASSED" if _failed == 0 else f"  {_failed} FAILED")
print(f"{'='*60}\n")

sys.exit(0 if _failed == 0 else 1)