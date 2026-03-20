"""
mock_modules.py
---------------
Placeholder implementations of all modules owned by other interns.
Replace each function body with the real implementation when integrated.

  question_generator  →  Sarmin Sultana    (GPT Question Generator)
  tts_speaker         →  Fahima Fahmitha M (Text-to-Speech)
  stt_listener        →  Gaurav Kshirsagar (Speech-to-Text)
  summary_generator   →  Aleeza Majid      (Interview Summary)
  detect_language     →  Mohd Aas Khan     (Language Detection)
"""

from typing import List


# ─────────────────────────────────────────────────────────────────
# SARMIN  —  GPT Question Generator
# ─────────────────────────────────────────────────────────────────

def question_generator(
    domain:     str,
    difficulty: str,
    history:    List[dict],
    language:   str,
) -> str:
    """
    MOCK: Returns a canned question.
    REAL: Build a GPT prompt from domain + difficulty + history and call OpenAI API.

    Expected GPT prompt structure (for Sarmin):
      System: "You are a technical interviewer. Domain: {domain}. Language: {language}."
      User:   "Previous Q&A: {history}. Ask ONE {difficulty} question."
    """
    q_num = len(history) + 1      # next question number
    templates = {
        "easy":   f"Can you explain a fundamental concept in {domain} that you've used?",
        "medium": f"Describe a real project where you applied {domain} techniques.",
        "hard":   f"How would you design a scalable {domain} system under constraints?",
    }
    return templates.get(difficulty, f"Tell me more about {domain}. (Q{q_num})")


# ─────────────────────────────────────────────────────────────────
# FAHIMA  —  Text-to-Speech
# ─────────────────────────────────────────────────────────────────

def tts_speaker(text: str, language: str) -> None:
    """
    MOCK: Just prints to console.
    REAL: Use Google TTS to convert text → audio, then play it.
    """
    print(f"[TTS | {language}] 🔊 {text}")


# ─────────────────────────────────────────────────────────────────
# GAURAV K  —  Speech-to-Text
# ─────────────────────────────────────────────────────────────────

def stt_listener() -> str:
    """
    MOCK: Returns a placeholder answer.
    REAL: Record microphone input, send to STT model, return transcript.
    In REST API mode this is not called directly —
    the candidate's answer arrives as a JSON field in POST /interview/answer.
    """
    return "This is a mock candidate response for testing purposes."


# ─────────────────────────────────────────────────────────────────
# ALEEZA  —  Interview Summary Generator
# ─────────────────────────────────────────────────────────────────

def summary_generator(session) -> dict:
    """
    MOCK: Returns a static summary skeleton.
    REAL: Build a GPT prompt from all Q&A pairs and generate structured JSON.

    Expected output schema:
    {
        "session_id":  str,
        "domain":      str,
        "language":    str,
        "duration_s":  float,
        "q_count":     int,
        "strengths":   [str],
        "weaknesses":  [str],
        "score":       int (0–100),
        "qa_pairs":    [...]
    }
    """
    import time
    duration = round((session.end_time or time.time()) - session.start_time, 2)
    return {
        "session_id":  session.session_id,
        "domain":      session.domain,
        "language":    session.language,
        "duration_s":  duration,
        "q_count":     len(session.qa_pairs),
        "strengths":   ["Clear communication", "Good conceptual knowledge"],
        "weaknesses":  ["Could give more real-world examples"],
        "score":       74,
        "qa_pairs":    session.get_history(),
    }


# ─────────────────────────────────────────────────────────────────
# MOHD AAS KHAN  —  Language Detection
# ─────────────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    """
    MOCK: Always returns 'en'.
    REAL: Use langdetect or similar library to identify language from answer text.
    """
    return "en"
