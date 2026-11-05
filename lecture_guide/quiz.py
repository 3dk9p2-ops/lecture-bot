"""MCQ generation (validated) respecting Telegram quiz-poll limits."""
from __future__ import annotations

import random
from typing import List

from pydantic import BaseModel, ConfigDict, field_validator

from . import constants as C
from .gemini import generate_json, outline
from .schema import StudyGuide


def _cut(s: str, n: int) -> str:
    s = " ".join(str(s).replace("**", "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


class MCQ(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str
    options: List[str]
    correct_index: int
    explanation: str = ""

    @field_validator("options")
    @classmethod
    def _four(cls, v):
        v = [str(x) for x in v]
        if len(v) != 4 or len({x.strip().lower() for x in v}) != 4:
            raise ValueError("options must be exactly 4 distinct strings")
        return v

    @field_validator("correct_index")
    @classmethod
    def _idx(cls, v):
        if not 0 <= v <= 3:
            raise ValueError("correct_index must be 0-3")
        return v


class QuizSet(BaseModel):
    model_config = ConfigDict(extra="ignore")
    questions: List[MCQ]

    @field_validator("questions")
    @classmethod
    def _count(cls, v):
        if len(v) < 5:
            raise ValueError("need at least 5 questions")
        return v


def finalize(q: MCQ) -> dict:
    """Shuffle options, apply Telegram length limits."""
    correct = q.options[q.correct_index]
    opts = q.options[:]
    random.shuffle(opts)
    return {
        "question": _cut(q.question, C.TG_QUESTION_MAX),
        "options": [_cut(o, C.TG_OPTION_MAX) for o in opts],
        "correct_option_id": opts.index(correct),
        "explanation": _cut(q.explanation, C.TG_EXPLANATION_MAX) if q.explanation.strip() else None,
    }


def generate_quiz(guide: StudyGuide, n: int = 10) -> list[dict]:
    n = max(10, min(12, n))
    prompt = C.QUIZ_PROMPT.format(n=n) + "\n\nCONTENT:\n" + outline(guide)[:40000]
    qs = generate_json(prompt, None, QuizSet.model_validate).questions[:12]
    return [finalize(q) for q in qs]
