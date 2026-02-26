"""
models.py
---------
All Pydantic request & response models for the Interview Flow Controller API.
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from enum import Enum


# ─────────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────────

class DomainEnum(str, Enum):
    AI_ML          = "AI/ML"
    DEEP_LEARNING  = "Deep Learning"
    WEB_DEV        = "Web Development"
    DATA_SCIENCE   = "Data Science"
    CLOUD          = "Cloud Computing"
    DSA            = "Data Structures & Algorithms"


class DifficultyEnum(str, Enum):
    EASY   = "easy"
    MEDIUM = "medium"
    HARD   = "hard"


class InterviewStateEnum(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    ABORTED     = "aborted"


class LanguageEnum(str, Enum):
    ENGLISH = "en"
    HINDI   = "hi"
    FRENCH  = "fr"
    SPANISH = "es"
    GERMAN  = "de"


# ─────────────────────────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────────────────────────

class StartInterviewRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {"domain": "Deep Learning", "language": "en"}
    })

    domain:   DomainEnum   = Field(..., description="Technical domain for the interview")
    language: LanguageEnum = Field(LanguageEnum.ENGLISH, description="Language for the interview")


class SubmitAnswerRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "abc123",
            "answer":     "I have 3 years of experience in machine learning."
        }
    })

    session_id: str = Field(..., description="Session ID returned from /start")
    answer:     str = Field(..., min_length=1, description="Candidate's answer to the current question")


class AbortInterviewRequest(BaseModel):
    session_id: str  = Field(..., description="Session ID to abort")
    reason:     str  = Field("User requested abort", description="Reason for aborting")


# ─────────────────────────────────────────────────────────────────
# NESTED RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────

class QAPairResponse(BaseModel):
    question_number: int
    difficulty:      DifficultyEnum
    question:        str
    answer:          str
    timestamp:       float


class ProgressResponse(BaseModel):
    session_id:          str
    domain:              str
    language:            str
    state:               InterviewStateEnum
    questions_asked:     int
    questions_remaining: int
    total_questions:     int
    current_difficulty:  Optional[DifficultyEnum]


class SummaryResponse(BaseModel):
    session_id:  str
    domain:      str
    language:    str
    duration_s:  float
    q_count:     int
    strengths:   List[str]
    weaknesses:  List[str]
    score:       int
    qa_pairs:    List[QAPairResponse]


# ─────────────────────────────────────────────────────────────────
# ENDPOINT RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────

class StartInterviewResponse(BaseModel):
    session_id:      str
    first_question:  str
    difficulty:      DifficultyEnum
    question_number: int
    total_questions: int
    message:         str


class SubmitAnswerResponse(BaseModel):
    session_id:          str
    answer_recorded:     bool
    question_number:     int          # question just answered
    questions_remaining: int
    interview_complete:  bool
    next_question:       Optional[str]          = None
    next_difficulty:     Optional[DifficultyEnum] = None
    next_question_number: Optional[int]         = None
    summary:             Optional[SummaryResponse] = None
    message:             str


class AbortResponse(BaseModel):
    session_id: str
    aborted:    bool
    message:    str


class HealthResponse(BaseModel):
    status:  str
    version: str
    author:  str