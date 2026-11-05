"""Long-polling worker for the lecture -> study-PDF feature.

Playwright/Chromium cannot run on Vercel, so this runs as a separate process (PC / VPS / Docker /
GitHub Actions). Use a SEPARATE bot token (LECTURE_BOT_TOKEN): a bot with a webhook set (the Vercel bot)
cannot use getUpdates.

Run:  python lecture_worker.py
"""
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from lecture_guide import config, constants as C
from lecture_guide.exam import EXAMS
from lecture_guide.pipeline import handle_lecture, parse_caption
from lecture_guide.telegram_io import Telegram, TelegramError

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("lecture_worker")

WELCOME = ("Send me a lecture (.docx, .pptx or .pdf) and I'll return a final study PDF (English + Arabic) "
           "plus an exam with score and grade.\n"
           "I will ask who translated it, and print that name inside the PDF.\n"
           "Optional caption: line 1 = doctor name (to file the PDF), line 2 = translator name.")

PENDING: dict = {}        # chat_id -> file waiting for a translator name
AWAIT_NAME: set = set()   # chats where the next text message is the translator name
RECENT: dict = {}         # chat_id -> recently used names (most recent first)
BUSY: set = set()


def start_health_server():
    """Free hosts need an open HTTP port; an uptime pinger hitting it keeps the service awake."""
    port = os.environ.get("PORT")
    if not port:
        return

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"lecture bot ok")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("0.0.0.0", int(port)), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("Health server on port %s", port)


def remember(chat_id, name):
    names = [n for n in RECENT.get(chat_id, []) if n != name]
    RECENT[chat_id] = ([name] + names)[:4]


def start_job(tg, chat_id, job, signature):
    if chat_id in BUSY:
        tg.send_message(chat_id, "Still working on your previous file - please wait.")
        return
    BUSY.add(chat_id)

    def run():
        try:
            handle_lecture(tg, chat_id, job["file_id"], job["name"], job["size"], job["caption"], signature)
        finally:
            BUSY.discard(chat_id)

    threading.Thread(target=run, daemon=True).start()


def ask_signature(tg, chat_id, job):
    names = list(dict.fromkeys(RECENT.get(chat_id, []) + config.TRANSLATOR_NAMES))[:6]
    job["names"] = names
    rows = [[{"text": n, "callback_data": f"sig:{i}"}] for i, n in enumerate(names)]
    rows.append([{"text": "✍️ Other name / اسم آخر", "callback_data": "sig:new"},
                 {"text": "⏭ No name / بدون اسم", "callback_data": "sig:none"}])
    PENDING[chat_id] = job
    AWAIT_NAME.discard(chat_id)
    tg.send_message(chat_id, "Who translated this file? The name is printed inside the PDF.\n"
                             "من ترجم هذا الملف؟ يُكتب الاسم داخل الملف.",
                    reply_markup={"inline_keyboard": rows})


def on_signature_callback(tg, cb):
    chat_id = cb["message"]["chat"]["id"]
    try:
        tg.call("answerCallbackQuery", {"callback_query_id": cb["id"]}, retries=1)
    except TelegramError:
        pass
    job = PENDING.get(chat_id)
    if not job:
        tg.send_message(chat_id, "Please send the file again.")
        return
    choice = cb["data"][4:]
    if choice == "new":
        AWAIT_NAME.add(chat_id)
        tg.send_message(chat_id, "Type the translator name now:\nاكتب اسم المترجم الآن:")
        return
    if choice == "none":
        PENDING.pop(chat_id, None)
        start_job(tg, chat_id, job, "")
        return
    try:
        name = job["names"][int(choice)]
    except (ValueError, IndexError):
        tg.send_message(chat_id, "Please send the file again.")
        return
    PENDING.pop(chat_id, None)
    remember(chat_id, name)
    start_job(tg, chat_id, job, name)


def handle_update(tg, u):
    cb = u.get("callback_query")
    if cb:
        if config.ALLOWED_USER_IDS and cb.get("from", {}).get("id") not in config.ALLOWED_USER_IDS:
            return
        data = cb.get("data", "")
        if data.startswith("sig:"):
            on_signature_callback(tg, cb)
        else:
            EXAMS.on_callback(tg, cb)
        return
    if u.get("poll_answer"):
        EXAMS.on_poll_answer(tg, u["poll_answer"])
        return

    m = u.get("message") or {}
    chat_id = (m.get("chat") or {}).get("id")
    uid = (m.get("from") or {}).get("id")
    if not chat_id:
        return
    if config.ALLOWED_USER_IDS and uid not in config.ALLOWED_USER_IDS:
        return
    doc = m.get("document")
    if not doc:
        text = (m.get("text") or "").strip()
        if text.startswith(("/start", "/help")):
            tg.send_message(chat_id, WELCOME)
        elif chat_id in AWAIT_NAME and text and not text.startswith("/"):
            name = " ".join(text.split())[:60]
            AWAIT_NAME.discard(chat_id)
            job = PENDING.pop(chat_id, None)
            if not job:
                tg.send_message(chat_id, "Please send the file again.")
                return
            remember(chat_id, name)
            start_job(tg, chat_id, job, name)
        return

    name = doc.get("file_name", "lecture")
    if not name.lower().endswith(C.SUPPORTED_EXT):
        tg.send_message(chat_id, "Please send a .docx, .pptx or .pdf file.")
        return
    job = {"file_id": doc["file_id"], "name": name, "size": doc.get("file_size", 0),
           "caption": m.get("caption")}
    signature = parse_caption(job["caption"])[1]
    if signature:                       # translator name written in caption line 2
        remember(chat_id, signature)
        start_job(tg, chat_id, job, signature)
    else:
        ask_signature(tg, chat_id, job)


def main():
    start_health_server()
    tg = Telegram(config.LECTURE_BOT_TOKEN)
    offset = 0
    log.info("Lecture worker started.")
    while True:
        try:
            updates = tg.get_updates(offset)
        except TelegramError as e:
            log.error("getUpdates: %s", e)
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                handle_update(tg, u)
            except Exception:
                log.exception("update failed")


if __name__ == "__main__":
    main()
