# 🎙️ Interview Flow Controller — FastAPI Module

> **Intern:** Atharva Dilip Bhosale
> **Module:** Interview Flow Controller
> **Project:** Domain-Based Intelligent Voice AI Interviewer
> **Status:** Task completed 100%
---

## 📌 What This Module Does

The **Interview Flow Controller** is the central brain of the AI Interviewer system. Every other module — Text-to-Speech, Speech-to-Text, GPT Question Generator, Language Detector, and Summary Generator — is called and coordinated by this controller in the correct order.

### Core Responsibilities

- ✅ Enforces **exactly 5 questions** — no more, no less
- ✅ Fixes **Question 1** as *"Please introduce yourself."* (no GPT call needed)
- ✅ Manages **difficulty progression**: Easy → Easy → Medium → Hard → Hard
- ✅ Coordinates **TTS, STT, GPT, and Summary** calls at the right moment
- ✅ Maintains **session state** for each candidate
- ✅ Exposes a clean **REST API** via FastAPI for the frontend and other modules

---

## 📁 File Structure

```
interview_controller/
├── main.py               # FastAPI app — all 6 API endpoints
├── controller.py         # Pure business logic (no FastAPI imports)
├── models.py             # Pydantic v2 request/response schemas
├── mock_modules.py       # Pluggable mocks for all teammate modules
├── test_controller.py    # Full test suite — 77 tests, no server needed
├── requirements.txt      # Python dependencies
└── README.md             # This file
```

---

## 🚀 How to Run

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Tests First (no server needed)
```bash
python test_controller.py
```
Expected output:
```
═══════════════════════════════════════════════════════
  RESULTS:  77/77 passed  🎉 ALL TESTS PASSED
═══════════════════════════════════════════════════════
```

### 3. Start the Server
```bash
uvicorn main:app --reload --port 8000
```

### 4. Open Interactive API Docs (Swagger UI)
```
http://localhost:8000/docs
```

---

## 🔗 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/health` | Check if server is running |
| `POST` | `/interview/start` | Start a new session + get Q1 |
| `POST` | `/interview/answer` | Submit answer → receive next question |
| `GET`  | `/interview/progress/{session_id}` | Live interview progress |
| `GET`  | `/interview/summary/{session_id}` | Final structured summary |
| `POST` | `/interview/abort` | Cleanly abort a session |
| `GET`  | `/interview/sessions` | Debug: list all active sessions |

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
  "total_questions": 5,
  "message": "Interview started. Please answer the question."
}
```

---

### 📝 Submit an Answer
```bash
curl -X POST http://localhost:8000/interview/answer \
     -H "Content-Type: application/json" \
     -d '{"session_id": "a3f9c2d1-...", "answer": "Hi, I am Atharva..."}'
```

**Response — interview still in progress:**
```json
{
  "session_id": "a3f9c2d1-...",
  "answer_recorded": true,
  "question_number": 1,
  "questions_remaining": 4,
  "interview_complete": false,
  "next_question": "Can you explain a fundamental concept in Deep Learning?",
  "next_difficulty": "easy",
  "next_question_number": 2,
  "summary": null,
  "message": "Answer recorded. Question 2/5 ready."
}
```

**Response — after 5th answer (interview complete):**
```json
{
  "interview_complete": true,
  "next_question": null,
  "summary": {
    "domain": "Deep Learning",
    "score": 74,
    "strengths": ["Clear communication", "Good conceptual knowledge"],
    "weaknesses": ["Could give more real-world examples"],
    "qa_pairs": ["..."]
  },
  "message": "Interview complete! Summary generated."
}
```

---

### 📊 Check Progress
```bash
curl http://localhost:8000/interview/progress/a3f9c2d1-...
```
```json
{
  "questions_asked": 2,
  "questions_remaining": 3,
  "total_questions": 5,
  "state": "in_progress",
  "current_difficulty": "medium"
}
```

### 🛑 Abort an Interview
```bash
curl -X POST http://localhost:8000/interview/abort \
     -H "Content-Type: application/json" \
     -d '{"session_id": "a3f9c2d1-...", "reason": "Candidate disconnected"}'
```

---

## 🧠 Difficulty Progression

| Question # | Difficulty | Purpose |
|:-----------:|:----------:|---------|
| 1 | 🟢 Easy   | Fixed intro — *"Please introduce yourself."* |
| 2 | 🟢 Easy   | Warm-up — basic domain knowledge |
| 3 | 🟡 Medium | Applied — real-world or project experience |
| 4 | 🔴 Hard   | Deep technical — design, trade-offs |
| 5 | 🔴 Hard   | Advanced — edge cases, architecture |

---

## 🔄 Session State Machine

```
NOT_STARTED ──► IN_PROGRESS ──► COMPLETED
                     │
                     └──────────► ABORTED
```

- Returns `400 Bad Request` if you submit an answer to a completed or aborted session
- Returns `404 Not Found` if the session ID doesn't exist
- Sessions are stored **in-memory** — replace with Redis/DB via Dipak's module for production

---

## 🤝 Integration with Other Modules

This controller acts as a hub — it calls every teammate's module at the right moment. Swapping a mock for a real implementation is just **one import line** in `main.py`.

| My API Call | Calls Into | Teammate | When |
|---|---|---|---|
| `tts_speaker(question, lang)` | TTS Module | Fahima Fahmitha M | After each question is generated |
| `detect_language(answer)` | Language Detection | Mohd Aas Khan | On every answer received |
| `question_generator(...)` | GPT Generator | Sarmin Sultana | For Q2 through Q5 |
| `summary_generator(session)` | Summary Generator | Aleeza Majid | After the 5th answer |
| `GET /progress` | Frontend UI | Shweta Sonar | Progress bar polling |
| `POST /abort` | Error Handler | V Jaya Pradha | On network/audio failure |
| `GET /sessions` | Logging Module | Panga Brahmadevesh | Debug monitoring |

### How to Plug In a Real Module

```python
# In main.py — just change one import line:

# Before (mock):
from mock_modules import question_generator

# After (Sarmin's real GPT module):
from sarmin_gpt_module import question_generator

# Nothing else in the codebase needs to change.
```

---

## 🧪 Test Suite — `test_controller.py`

Runs **77 tests across 10 scenarios** with no server or external services needed.

```bash
python test_controller.py
```

| # | Test Scenario | What It Checks |
|---|---|---|
| 1 | Difficulty Mapping | Q1–Q5 map correctly, ValueError on 0 / 6 / -1 |
| 2 | Session Creation | All fields initialised correctly, session is retrievable |
| 3 | First Question Fixed | Q1 is always *"Please introduce yourself."* for any domain/language |
| 4 | Full 5-Question Flow | Counter, state, remaining count, completion flag, summary |
| 5 | Counter Hard Limit | 6th question attempt raises ValueError, qa_pairs locked at 5 |
| 6 | Progress Snapshot | Mid-interview progress dict is accurate at each step |
| 7 | Abort Session | State transitions to ABORTED, end_time is set |
| 8 | Validation Edge Cases | 0 answers, 1 answer, whitespace-only answers → False |
| 9 | Language Detection | Mock returns string, defaults to 'en' |
| 10 | Summary Structure | All required keys present with correct types |

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

- [x] `main.py` — FastAPI app with 6 endpoints, CORS middleware, Swagger docs
- [x] `controller.py` — Interview loop, question counter, difficulty map, session store
- [x] `models.py` — Pydantic v2 schemas for all request/response types
- [x] `mock_modules.py` — Pluggable mocks for TTS, GPT, Summary, Language Detection
- [x] `test_controller.py` — 77 tests, 10 scenarios, 100% pass rate ✅
- [x] `requirements.txt` — All dependencies pinned
- [x] `README.md` — Documentation

---

*Module: Interview Flow Controller | Intern: Atharva Dilip Bhosale | Project: Domain-Based Intelligent Voice AI Interviewer*