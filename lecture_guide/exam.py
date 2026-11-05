"""Interactive exam on top of Telegram quiz polls: start button, one question at a time, score + grade + review."""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time

from .telegram_io import Telegram, TelegramError

log = logging.getLogger("lecture_guide.exam")

# (min percent, English label, Arabic label)
GRADES = [(90, "Excellent", "امتياز"), (80, "Very Good", "جيد جداً"), (70, "Good", "جيد"),
          (60, "Average", "متوسط"), (50, "Pass", "مقبول"), (0, "Fail", "راسب")]
SESSION_TTL = 6 * 3600


def grade_for(pct: float):
    for lo, en, ar in GRADES:
        if pct >= lo:
            return en, ar
    return GRADES[-1][1:]


class ExamManager:
    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.by_poll: dict[str, str] = {}
        self.lock = threading.Lock()

    # -- called after the PDF is sent
    def offer(self, tg: Telegram, chat_id: int, questions: list[dict], title: str):
        self._gc()
        sid = secrets.token_hex(4)
        with self.lock:
            self.sessions[sid] = {"chat": chat_id, "qs": questions, "i": 0, "ans": [], "title": title,
                                  "started": False, "t0": time.time(), "created": time.time()}
        kb = {"inline_keyboard": [[{"text": "▶️ Start exam", "callback_data": f"exam:{sid}"}]]}
        tg.send_message(chat_id, f"📝 Exam ready: {len(questions)} questions on\n{title}\n\n"
                                 "Answer each question; at the end you get your score and grade.",
                        reply_markup=kb)

    # -- callback "Start exam"
    def on_callback(self, tg: Telegram, cb: dict):
        data = cb.get("data", "")
        if not data.startswith("exam:"):
            return
        try:
            tg.call("answerCallbackQuery", {"callback_query_id": cb["id"]}, retries=1)
        except TelegramError:
            pass
        with self.lock:
            s = self.sessions.get(data[5:])
            if not s or s["started"]:
                return
            s["started"], s["t0"] = True, time.time()
        self._send_next(tg, data[5:])

    # -- poll_answer update
    def on_poll_answer(self, tg: Telegram, pa: dict):
        with self.lock:
            sid = self.by_poll.pop(pa.get("poll_id"), None)
            s = self.sessions.get(sid) if sid else None
            if not s:
                return
            q = s["qs"][s["i"]]
            chosen = (pa.get("option_ids") or [None])[0]
            s["ans"].append(chosen == q["correct_option_id"])
            s["i"] += 1
            finished = s["i"] >= len(s["qs"])
        if finished:
            self._finish(tg, sid)
        else:
            self._send_next(tg, sid)

    # -- internals
    def _send_next(self, tg: Telegram, sid: str):
        s = self.sessions[sid]
        n, i = len(s["qs"]), s["i"]
        q = s["qs"][i]
        q = dict(q, question=f"({i + 1}/{n}) {q['question']}"[:300])
        try:
            res = tg.send_quiz(s["chat"], q)
            with self.lock:
                self.by_poll[res["poll"]["id"]] = sid
        except TelegramError as e:
            tg.send_message(s["chat"], f"Exam stopped: {e}")

    def _finish(self, tg: Telegram, sid: str):
        s = self.sessions.pop(sid)
        n = len(s["qs"])
        ok = sum(s["ans"])
        pct = ok / n * 100
        en, ar = grade_for(pct)
        mins = max(1, round((time.time() - s["t0"]) / 60))
        lines = [f"🏁 Exam finished — {s['title']}", "",
                 f"Score: {ok}/{n}  ({pct:.0f}%)", f"Grade: {en} — {ar}", f"Time: ~{mins} min"]
        wrong = [(q, a) for q, a in zip(s["qs"], s["ans"]) if not a]
        if wrong:
            lines += ["", f"❌ Review ({len(wrong)} wrong):"]
            for k, (q, _) in enumerate(wrong, 1):
                lines.append(f"\n{k}. {q['question'].split(') ', 1)[-1]}")
                lines.append(f"✅ {q['options'][q['correct_option_id']]}")
                if q.get("explanation"):
                    lines.append(f"ℹ️ {q['explanation']}")
        else:
            lines += ["", "🎉 Perfect score!"]
        tg.send_long(s["chat"], "\n".join(lines))

    def _gc(self):
        now = time.time()
        with self.lock:
            for sid in [k for k, v in self.sessions.items() if now - v["created"] > SESSION_TTL]:
                self.sessions.pop(sid, None)
            live = set(self.sessions)
            self.by_poll = {p: s for p, s in self.by_poll.items() if s in live}


EXAMS = ExamManager()
