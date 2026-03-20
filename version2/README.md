# 🎙️ Interview Flow Controller — v2 (Optimized)

> **Intern:** Atharva Dilip Bhosale
> **Module:** Interview & Assessment Flow Controller Optimization
> **Project:** Domain-Based Intelligent Voice AI Interviewer
> **Built on top of:** v1 (10-question FastAPI controller)

---

## 📌 What's New in v2

v1 built the working 10-question interview loop. v2 makes it **production-ready** by adding:

- ✅ **State-machine architecture** — every session transition is validated, no silent state corruption
- ✅ **Timeout management** — per-question (2 min) and session-level (30 min) deadlines
- ✅ **Structured error handling** — every error has a `retryable` flag so clients know what to do
- ✅ **Idempotent endpoints** — network retries never process the same answer twice
- ✅ **3 new endpoints** — timeout countdown, time extension requests, FSM debug log

---

## 📁 File Structure

```
interview_controller_v2/
├── main_v2.py            # FastAPI app v2 — 9 endpoints, FSM + timeout integrated
├── state_machine.py      # Finite State Machine — 8 states, 8 events, 16 transitions
├── timeout_manager.py    # Per-question & session timers, extension requests
├── error_handler.py      # 20 error codes, retryable flags, safe_call wrapper
├── test_v2.py            # Full test suite — 105 tests, no server needed
│
│   (reused from v1)
├── controller.py         # Core 10-question loop logic
├── models.py             # Pydantic v2 request/response schemas
├── mock_modules.py       # Pluggable mocks for TTS, GPT, Summary, LangDetect
├── requirements.txt      # Python dependencies
└── README_v2.md          # This file
```

---

## 🚀 How to Run

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run v2 Tests (no server needed)
```bash
python test_v2.py
```
Expected output:
```
============================================================
  RESULTS:  105/105 passed  🎉 ALL TESTS PASSED
============================================================
```

### 3. Start the v2 Server
```bash
uvicorn main_v2:app --reload --port 8000
```

### 4. Open Interactive API Docs (Swagger UI)
```
http://localhost:8000/docs
```

---

## 🔗 API Endpoints

| Method | Endpoint | Description | New in v2 |
|--------|----------|-------------|:---------:|
| `GET`  | `/health` | Server health check | — |
| `POST` | `/interview/start` | Start session + FSM + timers | ✅ |
| `POST` | `/interview/answer` | Submit answer — idempotency-key supported | ✅ |
| `GET`  | `/interview/progress/{session_id}` | Live progress + FSM state | ✅ |
| `GET`  | `/interview/summary/{session_id}` | Final structured summary | — |
| `POST` | `/interview/abort` | Abort → FSM INTERRUPTED state | ✅ |
| `POST` | `/interview/extend` | Request 60s time extension on current question | 🆕 |
| `GET`  | `/interview/timeout/{session_id}` | Live countdown for frontend timer | 🆕 |
| `GET`  | `/interview/transitions/{session_id}` | Full FSM history for debugging | 🆕 |
| `GET`  | `/interview/sessions` | Debug: list all active sessions | — |

---

## 📋 API Usage Examples

### ▶️ Start an Interview
```bash
curl -X POST http://localhost:8000/interview/start \
     -H "Content-Type: application/json" \
     -d '{"domain": "Deep Learning", "language": "en"}'
```
**Response (201 Created):**
```json
{
  "session_id": "a3f9c2d1-...",
  "first_question": "Please introduce yourself.",
  "difficulty": "easy",
  "question_number": 1,
  "total_questions": 10,
  "message": "Interview started. State: introducing"
}
```

---

### 📝 Submit an Answer (with Idempotency Key)
```bash
curl -X POST http://localhost:8000/interview/answer \
     -H "Content-Type: application/json" \
     -H "X-Idempotency-Key: unique-request-id-001" \
     -d '{"session_id": "a3f9c2d1-...", "answer": "Hi, I am Atharva..."}'
```
> Sending the **same `X-Idempotency-Key` again** (e.g. on network retry) returns the cached
> response instantly — the answer is **never processed twice**.

**Response:**
```json
{
  "answer_recorded": true,
  "question_number": 1,
  "questions_remaining": 9,
  "interview_complete": false,
  "next_question": "Can you explain a core concept in Deep Learning?",
  "next_difficulty": "easy",
  "message": "Answer recorded. Q2/10 ready. State: questioning"
}
```

---

### ⏱️ Request a Time Extension
```bash
curl -X POST http://localhost:8000/interview/extend \
     -H "Content-Type: application/json" \
     -d '{"session_id": "a3f9c2d1-...", "question_number": 3}'
```
```json
{
  "granted": true,
  "extensions_used": 1,
  "extensions_max": 2,
  "new_remaining_s": 155.4,
  "reason": "Extension granted"
}
```

---

### ⏰ Check Timeout Status
```bash
curl http://localhost:8000/interview/timeout/a3f9c2d1-...
```
```json
{
  "session_elapsed_s": 142.3,
  "session_remaining_s": 1657.7,
  "session_expired": false,
  "current_question_timer": {
    "question_number": 3,
    "remaining": 87.2,
    "is_expired": false,
    "extensions_used": 0
  }
}
```

---

### 🔍 Get FSM Transition Log
```bash
curl http://localhost:8000/interview/transitions/a3f9c2d1-...
```
```json
{
  "session_id": "a3f9c2d1-...",
  "current_state": "questioning",
  "valid_events": ["answer_received", "last_answered", "timeout", "abort", "system_error"],
  "history": [
    { "from_state": "idle",        "to_state": "introducing", "event": "start",           "success": true },
    { "from_state": "introducing", "to_state": "questioning", "event": "answer_received", "success": true }
  ]
}
```

---

### ❌ Structured Error Response
Every error from v2 follows this consistent shape:
```json
{
  "error_code":    "GPT_FAILURE",
  "message":       "External module 'GPT question generator' failed: ConnectionError",
  "detail":        { "module": "GPT question generator", "exception": "ConnectionError" },
  "retryable":     true,
  "retry_after_s": 5,
  "timestamp":     1740000000.0
}
```
> `retryable: true` → client should retry after `retry_after_s` seconds
> `retryable: false` → fix the request, retrying won't help

---

## 🔄 Session State Machine

```
                    ┌─────────────────────────────────┐
                    │                                 ▼
IDLE ──► INTRODUCING ──► QUESTIONING ──► COMPLETING ──► DONE
                              │   ▲
                         TIMEOUT  RECOVER
                              │   │
                           TIMED_OUT (recoverable)
                              │
                         INTERRUPTED  (terminal — abort)
                              │
                           ERROR       (terminal — system)
```

| State | Type | Description |
|-------|------|-------------|
| `idle` | Active | Session created, not yet started |
| `introducing` | Active | Q1 spoken, waiting for answer |
| `questioning` | Active | Q2–Q10 in progress |
| `completing` | Active | 10th answer received, generating summary |
| `done` | **Terminal** | Interview finished cleanly |
| `timed_out` | **Recoverable** | No answer in time — RECOVER returns to questioning |
| `interrupted` | **Terminal** | Aborted by user or system |
| `error` | **Terminal** | Unrecoverable system error |

> **Key rule:** Terminal states block all further transitions and return a structured error.
> `timed_out` is the only non-terminal "stop" state — the session can be recovered.

---

## ⏱️ Timeout Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Question timeout | **120 seconds** | Time allowed per question |
| Session timeout | **1800 seconds** | Total interview time limit |
| Max extensions | **2 per question** | Candidate can request more time |
| Extension duration | **60 seconds** | Added per extension |

---

## 🛡️ Error Codes & Retryability

| Error Code | Retryable | HTTP | When |
|------------|:---------:|------|------|
| `SESSION_NOT_FOUND` | ❌ | 404 | Wrong session ID |
| `SESSION_ALREADY_DONE` | ❌ | 400 | Interview already finished |
| `SESSION_ABORTED` | ❌ | 400 | Session was aborted |
| `SESSION_TIMED_OUT` | ❌ | 400 | Session expired |
| `ILLEGAL_TRANSITION` | ❌ | 409 | FSM blocked the move |
| `ANSWER_EMPTY` | ❌ | 422 | Empty or whitespace answer |
| `ANSWER_TOO_SHORT` | ❌ | 422 | Answer under 3 characters |
| `QUESTION_TIMED_OUT` | ❌ | 408 | Question deadline passed |
| `NO_EXTENSION_REMAINING` | ❌ | 400 | Both extensions already used |
| `GPT_FAILURE` | ✅ | 503 | Retry after 5s |
| `TTS_FAILURE` | ✅ | 503 | Retry after 3s |
| `STT_FAILURE` | ✅ | 503 | Retry after 3s |
| `RATE_LIMITED` | ✅ | 429 | Retry after 10s |
| `UPSTREAM_TIMEOUT` | ✅ | 504 | Retry after 5s |
| `INTERNAL_ERROR` | ✅ | 500 | Retry after 3s |

---

## 🤝 Integration with Other Modules

Same as v1 — swap one import line in `main_v2.py`. Now additionally wrapped with `safe_call()` so any failure is caught and returned as a structured error automatically.

| My Call | Teammate | When |
|---------|----------|------|
| `tts_speaker(question, lang)` | Fahima — TTS | After each question generated |
| `detect_language(answer)` | Mohd Aas Khan — Lang Detect | On every answer |
| `question_generator(...)` | Sarmin — GPT Generator | Q2 through Q10 |
| `summary_generator(session)` | Aleeza — Summary | After Q10 answered |
| `GET /timeout/{id}` | Shweta — Frontend UI | Countdown timer widget |
| `GET /transitions/{id}` | Panga — Logging | Debug monitoring |

```python
# In main_v2.py — just change one import:
from mock_modules import question_generator        # before
from sarmin_gpt_module import question_generator   # after
```

---

## 🧪 Test Suite — `test_v2.py`

Runs **105 tests across 10 scenarios** — no server, no external services.

```bash
python test_v2.py
```

| # | Scenario | What It Checks |
|---|----------|----------------|
| 1 | State Machine — Normal Flow | Full path IDLE → DONE, blocked transitions from DONE |
| 2 | State Machine — Fail-Safe | TIMEOUT, ABORT, SYSTEM_ERROR, RECOVER, illegal moves |
| 3 | State Machine — Hooks | on_enter/on_exit callbacks, transition log structure |
| 4 | Timeout Manager — Timer Basics | Creation, expiry simulation, record_answer |
| 5 | Timeout Manager — Extensions | Grant, max limit (2), status snapshot, unknown session |
| 6 | Error Handler — Structure | All required fields, retryable flag, retry_after_s |
| 7 | Error Handler — InterviewAPIError | Code, message, detail, str() |
| 8 | Error Handler — safe_call | Good fn passes through, bad fn wrapped as structured error |
| 9 | Idempotency Cache | Miss, hit, expiry, purge |
| 10 | Transition Table Completeness | All 16 transitions valid, correct terminal states |

---

## 🐛 Issues Fixed in v2

| # | Issue | Fix |
|---|-------|-----|
| 1 | `TIMED_OUT` was incorrectly marked terminal | Made it recoverable with `RECOVER` event → `QUESTIONING` |
| 2 | `error_handler.py` required FastAPI at import time (broke standalone tests) | Used `TYPE_CHECKING` guard + lazy imports inside handler functions |
| 3 | Idempotency cache grew unbounded in memory | `purge_expired_idempotency_keys()` called on FastAPI lifespan startup |

---

## 📦 Dependencies

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
pydantic==2.7.1
httpx==0.27.0
pytest==8.2.0
```

---

## 📄 Deliverables Checklist

- [x] `state_machine.py` — FSM with 8 states, 8 events, 16 transitions, hooks
- [x] `timeout_manager.py` — per-question + session timers, up to 2 extensions
- [x] `error_handler.py` — 20 error codes, retryable map, safe_call, idempotency cache
- [x] `main_v2.py` — FastAPI v2 with 9 endpoints and structured error handlers
- [x] `test_v2.py` — 105 tests, 10 scenarios, 100% pass rate ✅
- [x] `README_v2.md` — This documentation
- [x] `Atharva_Bhosale_Task_Report_v2.docx` — Full task report

---

*Module: Interview & Assessment Flow Controller Optimization | Intern: Atharva Dilip Bhosale | Project: Domain-Based Intelligent Voice AI Interviewer*