"""Configuration from environment / .env (no secrets hard-coded)."""
import os
from pathlib import Path


def _load_dotenv():
    for p in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
# Same model list as bot.py, overridable by env.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_FALLBACKS = [
    m for m in os.environ.get(
        "GEMINI_FALLBACKS", "gemini-3.6-flash,gemini-3.8-flash,gemini-3-flash-preview,gemini-3.5-flash-lite"
    ).split(",") if m.strip()
]
GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "180"))

# Lecture bot uses its own token if given (a webhook bot and a polling worker cannot share one token).
LECTURE_BOT_TOKEN = os.environ.get("LECTURE_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_IDS = {int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x.isdigit()}

QUIZ_COUNT = int(os.environ.get("QUIZ_COUNT", "10"))
STUDY_NOTES_DIR = Path(os.path.expanduser(os.environ.get("STUDY_NOTES_DIR", "~/Documents/Study Notes")))

# Optional ready-made translator names shown as buttons (comma separated).
TRANSLATOR_NAMES = [n.strip() for n in os.environ.get("TRANSLATOR_NAMES", "").replace("،", ",").split(",") if n.strip()]
