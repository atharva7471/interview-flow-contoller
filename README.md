# 🎙️ Interview Flow Controller — FastAPI Module

> **Intern:** Atharva Dilip Bhosale
> **Module:** Interview Flow Controller
> **Project:** Domain-Based Intelligent Voice AI Interviewer

---

## 📌 What This Module Does

The **Interview Flow Controller** is the central brain of the AI Interviewer system. Every other module — Text-to-Speech, Speech-to-Text, GPT Question Generator, Language Detector, and Summary Generator — is called and coordinated by this controller in the correct order.

It is responsible for:

- ✅ Enforcing **exactly 5 questions** — no more, no less
- ✅ Fixing **Question 1** as *"Please introduce yourself."* (no GPT call needed)
- ✅ Managing **difficulty progression**: Easy → Easy → Medium → Hard → Hard
- ✅ Coordinating **TTS, STT, GPT, and Summary** calls at the right time
- ✅ Maintaining **session state** for each candidate
- ✅ Exposing a clean **REST API** via FastAPI for the frontend and other modules to use

---

## 📁 File Structure

```
interview_controller/
├── main.py             # FastAPI app — all 6 API endpoints
├── controller.py       # Pure business logic (no FastAPI imports)
├── models.py           # Pydantic request/response schemas
├── mock_modules.py     # Placeholder functions for other interns' modules
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

---

## 🚀 How to Run

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the Server
```bash
uvicorn main:app --reload --port 8000
```

### 3. Open Swagger UI (Interactive API Docs)
```
http://localhost:8000/docs
```

---

## 🔗 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Check if server is running |
| `POST` | `/interview/start` | Start a new interview session |
| `POST` | `/interview/answer` | Submit answer → receive next question |
| `GET` | `/interview/progress/{session_id}` | Get live interview progress |
| `GET` | `/interview/summary/{session_id}` | Fetch final interview summary |
| `POST` | `/interview/abort` | Cleanly abort a session |
| `GET` | `/interview/sessions` | Debug: list all active sessions |

---

## 📋 API Usage Examples

### ▶️ Start an Interview
```bash
curl -X POST http://localhost:8000/interview/start \
     -H "Content-Type: application/json" \
     -d '{"domain": "Deep Learning", "language": "en"}'
```
**Response:**
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
     -d '{"session_id": "a3f9c2d1-...", "answer": "Hi, I am Atharva, a CS student..."}'
```
**Response (while interview is ongoing):**
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

**Response (after 5th answer — interview complete):**
```json
{
  "interview_complete": true,
  "next_question": null,
  "summary": {
    "domain": "Deep Learning",
    "score": 74,
    "strengths": ["Clear communication", "Good conceptual knowledge"],
    "weaknesses": ["Could give more real-world examples"],
    "qa_pairs": [...]
  },
  "message": "Interview complete! Summary generated."
}
```

---

### 📊 Check Progress
```bash
curl http://localhost:8000/interview/progress/a3f9c2d1-...
```
**Response:**
```json
{
  "questions_asked": 2,
  "questions_remaining": 3,
  "total_questions": 5,
  "state": "in_progress",
  "current_difficulty": "medium"
}
```

---

## 🧠 Difficulty Progression

| Question # | Difficulty | Purpose |
|:-----------:|-----------|---------|
| 1 | 🟢 Easy | Fixed intro — *"Please introduce yourself."* |
| 2 | 🟢 Easy | Warm-up — basic domain knowledge |
| 3 | 🟡 Medium | Applied — real-world or project experience |
| 4 | 🔴 Hard | Deep technical — design, trade-offs |
| 5 | 🔴 Hard | Advanced — edge cases, architecture |

---

## 🔄 Session State Machine

```
NOT_STARTED ──► IN_PROGRESS ──► COMPLETED
                     │
                     └──────────► ABORTED
```

- The API returns `400 Bad Request` if you try to submit an answer to a completed or aborted session.
- Sessions are stored **in-memory** (can be replaced with Redis/DB by Dipak's module).

---

## 🤝 Integration with Other Modules

This module acts as a hub that calls every other intern's module at the right moment. Swapping a mock for a real implementation is just **one import line change** in `main.py`.

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
# main.py — replace this one import:

# Before (mock):
from mock_modules import question_generator

# After (Sarmin's real GPT module):
from sarmin_gpt_module import question_generator

# Nothing else in the codebase needs to change.
```

---

## 🗂️ Key Code Concepts

### The 5-Question Enforcement
The entire loop logic lives in `controller.py`. The counter only goes forward and the loop exits the moment it hits 5:

```python
while not session.is_complete:          # stops at exactly current_q == 5
    question_number = session.current_q + 1
    ...
    session.current_q += 1             # strict one-way counter
```

### Difficulty Map
```python
DIFFICULTY_MAP = {
    1: Difficulty.EASY,
    2: Difficulty.EASY,
    3: Difficulty.MEDIUM,
    4: Difficulty.HARD,
    5: Difficulty.HARD,
}
```

### Session Data Structure
```python
@dataclass
class InterviewSession:
    session_id  : str
    domain      : str
    language    : str
    state       : InterviewState   # NOT_STARTED | IN_PROGRESS | COMPLETED | ABORTED
    qa_pairs    : List[QAPair]     # grows from 0 to 5
    current_q   : int              # 0-indexed counter (0 to 4)
    start_time  : float
    end_time    : Optional[float]
    summary     : Optional[dict]
```

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

- [x] `main.py` — FastAPI app with 6 endpoints
- [x] `controller.py` — Interview loop logic + question counter + difficulty mapping
- [x] `models.py` — Pydantic schemas
- [x] `mock_modules.py` — Pluggable mocks for all teammate modules
- [x] `requirements.txt` — Dependencies
- [x] `README.md` — This documentation
- [x] `Interview_Flow_Controller_FastAPI_Explanation.pdf` — Detailed PDF documentation

---

*Module: Interview Flow Controller | Intern: Atharva Dilip Bhosale | Project: Domain-Based Intelligent Voice AI Interviewer*