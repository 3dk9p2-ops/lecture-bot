"""Minimal Telegram Bot API client with timeouts, retries and size checks."""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

import requests

from . import constants as C

log = logging.getLogger("lecture_guide.telegram")


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, token: str):
        if not token:
            raise TelegramError("Telegram bot token is not set (LECTURE_BOT_TOKEN / TELEGRAM_BOT_TOKEN).")
        self.base = f"https://api.telegram.org/bot{token}"
        self.file_base = f"https://api.telegram.org/file/bot{token}"

    def call(self, method: str, data: dict = None, files: dict = None, timeout: int = 60, retries: int = 3):
        last = ""
        for attempt in range(retries):
            try:
                if files:
                    for f in files.values():
                        f[1].seek(0)
                r = requests.post(f"{self.base}/{method}", data=data, files=files, timeout=timeout)
                try:
                    j = r.json()
                except ValueError:
                    j = {}
                if j.get("ok"):
                    return j["result"]
                last = j.get("description", f"HTTP {r.status_code}")
                if r.status_code == 429:
                    time.sleep(int(j.get("parameters", {}).get("retry_after", 3)) + 1)
                    continue
                if r.status_code < 500:
                    break  # client error: retrying will not help
            except requests.RequestException as e:
                last = str(e)
            time.sleep(2 * (attempt + 1))
        raise TelegramError(f"{method} failed: {last}")

    # --- messaging
    def send_message(self, chat_id, text: str, **kw) -> Optional[dict]:
        try:
            if isinstance(kw.get("reply_markup"), dict):
                kw["reply_markup"] = json.dumps(kw["reply_markup"])
            return self.call("sendMessage", {"chat_id": chat_id, "text": text[: C.TG_MESSAGE_MAX], **kw})
        except TelegramError as e:
            log.warning("send_message: %s", e)
            return None

    def edit_message(self, chat_id, message_id, text: str):
        try:
            self.call("editMessageText", {"chat_id": chat_id, "message_id": message_id, "text": text}, retries=1)
        except TelegramError:
            pass

    def send_long(self, chat_id, text: str):
        """Split on line boundaries to respect the 4096 limit."""
        buf = ""
        for line in text.splitlines(keepends=True):
            while len(line) > C.TG_MESSAGE_MAX:
                if buf:
                    self.send_message(chat_id, buf)
                    buf = ""
                self.send_message(chat_id, line[: C.TG_MESSAGE_MAX])
                line = line[C.TG_MESSAGE_MAX:]
            if len(buf) + len(line) > C.TG_MESSAGE_MAX:
                self.send_message(chat_id, buf)
                buf = ""
            buf += line
        if buf.strip():
            self.send_message(chat_id, buf)

    def send_document(self, chat_id, path: str, filename: str, caption: str = ""):
        import os
        if os.path.getsize(path) > C.TG_UPLOAD_MAX:
            raise TelegramError("The generated PDF is larger than Telegram's 50 MB bot upload limit.")
        with open(path, "rb") as f:
            return self.call("sendDocument", {"chat_id": chat_id, "caption": caption[:1000]},
                             files={"document": (filename, f, "application/pdf")}, timeout=180)

    def send_quiz(self, chat_id, q: dict):
        data = {"chat_id": chat_id, "question": q["question"], "options": json.dumps(q["options"]),
                "type": "quiz", "correct_option_id": q["correct_option_id"], "is_anonymous": "false"}
        if q.get("explanation"):
            data["explanation"] = q["explanation"]
        return self.call("sendPoll", data)

    # --- files
    def download_file(self, file_id: str, dest: str, size_hint: int = 0) -> str:
        if size_hint and size_hint > C.TG_DOWNLOAD_MAX:
            raise TelegramError(
                f"This file is {size_hint/1048576:.1f} MB. Telegram bots can only download files up to 20 MB — "
                "please compress it or split it into parts.")
        info = self.call("getFile", {"file_id": file_id})
        with requests.get(f"{self.file_base}/{info['file_path']}", stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(dest, "wb") as out:
                for chunk in r.iter_content(1 << 16):
                    out.write(chunk)
        return dest

    def get_updates(self, offset: int, timeout: int = 50):
        return self.call("getUpdates", {"offset": offset, "timeout": timeout,
                                        "allowed_updates": '["message","callback_query","poll_answer"]'}, timeout=timeout + 15, retries=1)
