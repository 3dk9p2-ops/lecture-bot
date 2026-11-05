"""Long-polling worker for the lecture -> study-PDF feature.

Playwright/Chromium cannot run on Vercel, so this runs as a separate process (PC / VPS / Docker).
Use a SEPARATE bot token (LECTURE_BOT_TOKEN): a bot with a webhook set (the Vercel bot) cannot
use getUpdates, and the keep-alive workflow re-registers that webhook every 10 minutes.

Run:  python lecture_worker.py
"""
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from lecture_guide import config, constants as C
from lecture_guide.exam import EXAMS
from lecture_guide.pipeline import handle_lecture
from lecture_guide.telegram_io import Telegram, TelegramError

logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("lecture_worker")

WELCOME = ("Send me a lecture (.docx, .pptx or .pdf) and I'll return a final English study PDF "
           "plus a quiz.\nOptional: write the doctor's name in the file caption to file the PDF under it.")


def start_health_server():
    """Free hosts (Render) need an open HTTP port; an uptime pinger hitting it keeps the service awake."""
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


def main():
    start_health_server()
    tg = Telegram(config.LECTURE_BOT_TOKEN)
    busy: set[int] = set()
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
            if u.get("callback_query") or u.get("poll_answer"):
                try:
                    if u.get("callback_query"):
                        EXAMS.on_callback(tg, u["callback_query"])
                    else:
                        EXAMS.on_poll_answer(tg, u["poll_answer"])
                except Exception:
                    log.exception("exam update failed")
                continue
            m = u.get("message") or {}
            chat_id = (m.get("chat") or {}).get("id")
            uid = (m.get("from") or {}).get("id")
            if not chat_id:
                continue
            if config.ALLOWED_USER_IDS and uid not in config.ALLOWED_USER_IDS:
                continue
            doc = m.get("document")
            if not doc:
                if (m.get("text") or "").startswith(("/start", "/help")):
                    tg.send_message(chat_id, WELCOME)
                continue
            name = doc.get("file_name", "lecture")
            if not name.lower().endswith(C.SUPPORTED_EXT):
                tg.send_message(chat_id, "Please send a .docx, .pptx or .pdf file.")
                continue
            if chat_id in busy:
                tg.send_message(chat_id, "Still working on your previous file - please wait.")
                continue
            busy.add(chat_id)

            def run(cid=chat_id, d=doc, n=name, cap=m.get("caption")):
                try:
                    handle_lecture(tg, cid, d["file_id"], n, d.get("file_size", 0), cap)
                finally:
                    busy.discard(cid)

            threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":
    main()
