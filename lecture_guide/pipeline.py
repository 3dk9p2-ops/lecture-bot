"""Orchestrator: file -> text -> Gemini JSON -> HTML -> PDF (+ quiz, Arabic, filing)."""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional

from . import config, filing
from .extract import Unit, extract_any
from .gemini import generate_study_guide, ocr_image
from .exam import EXAMS
from .quiz import generate_quiz
from .render import render_pdf
from .schema import StudyGuide
from .telegram_io import Telegram, TelegramError

log = logging.getLogger("lecture_guide.pipeline")


@dataclass
class Result:
    guide: StudyGuide
    pdf_path: str
    units: list


def build_pdf(src_path: str, out_pdf: str, progress: Callable[[str], None] = lambda m: None) -> Result:
    """Pure pipeline (no Telegram): used by the bot and by the test script."""
    progress("Reading the file...")
    ex = extract_any(src_path, ocr=ocr_image, progress=progress)
    guide = generate_study_guide(ex, progress)
    progress("Rendering PDF...")
    render_pdf(guide, out_pdf, ex.images)
    return Result(guide, out_pdf, ex.units)


def handle_lecture(tg: Telegram, chat_id: int, file_id: str, file_name: str, file_size: int,
                   caption: Optional[str] = None):
    """Full Telegram flow. Never raises: errors are reported to the chat."""
    status = tg.send_message(chat_id, "Reading...")
    mid = status["message_id"] if status else None

    def progress(msg: str):
        if mid:
            tg.edit_message(chat_id, mid, msg)
        else:
            tg.send_message(chat_id, msg)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "lecture" + os.path.splitext(file_name)[1].lower())
            tg.download_file(file_id, src, file_size)
            out_pdf = os.path.join(tmp, "guide.pdf")

            progress("Reading...")
            ex = extract_any(src, ocr=ocr_image, progress=progress)
            guide = generate_study_guide(ex, progress)
            progress("Rendering PDF...")
            render_pdf(guide, out_pdf, ex.images)

            safe_title = filing.safe_name(guide.title, "Study Guide")
            tg.send_document(chat_id, out_pdf, safe_title + ".pdf", caption=guide.title)
            try:
                saved = filing.file_copy(out_pdf, guide.title, caption)
                log.info("Filed copy at %s", saved)
            except OSError as e:
                log.warning("Filing failed: %s", e)

            progress("Done. Preparing the exam...")
            try:
                EXAMS.offer(tg, chat_id, generate_quiz(guide, config.QUIZ_COUNT), guide.title)
            except Exception as e:
                log.warning("Quiz failed: %s", e)
                tg.send_message(chat_id, "The PDF is ready, but I couldn't generate the exam this time.")
    except TelegramError as e:
        log.exception("Telegram error")
        tg.send_message(chat_id, f"Telegram problem: {e}")
    except Exception as e:
        log.exception("Pipeline failed")
        tg.send_message(chat_id, f"Sorry, I couldn't process this file: {str(e)[:300]}")
