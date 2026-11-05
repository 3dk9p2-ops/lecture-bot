"""Gemini REST client, JSON validation/retry, chunked study-guide generation."""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Callable, Optional

import requests
from pydantic import ValidationError

from . import config, constants as C
from .extract import MARKER, Extracted, chunk_units
from .schema import Bullets, Section, StudyGuide

log = logging.getLogger("lecture_guide.gemini")


class GeminiError(RuntimeError):
    pass


def _call(parts: list, system: Optional[str] = None, json_mode: bool = True, temperature: float = 0.1) -> str:
    if not config.GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY is not set.")
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 32768}}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    last = "unknown error"
    for model in [config.GEMINI_MODEL] + config.GEMINI_FALLBACKS:
        for attempt in range(3):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": config.GEMINI_API_KEY},
                    json=body, timeout=config.GEMINI_TIMEOUT)
                if r.status_code == 200:
                    cand = r.json().get("candidates") or []
                    if cand and cand[0].get("content", {}).get("parts"):
                        return "".join(p.get("text", "") for p in cand[0]["content"]["parts"])
                    last = f"{model}: empty response"
                    break
                last = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                log.warning("Gemini %s", " ".join(last.split())[:220])
                if r.status_code in (500, 503) or (r.status_code == 429 and "quota" not in r.text.lower()):
                    time.sleep(5 * 2 ** attempt)   # temporary overload: wait 5/10/20 s, then next model
                    continue
                break  # 400/403/404 -> next model
            except requests.RequestException as e:
                last = f"{model}: {e}"
                time.sleep(2)
    raise GeminiError(last)


def _parse_json(raw: str):
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    a, b = raw.find("{"), raw.rfind("}")
    if a == -1 or b <= a:
        raise ValueError("No JSON object found in response")
    return json.loads(raw[a:b + 1])


def generate_json(prompt_text: str, system: Optional[str], validate: Callable[[dict], object],
                  images: Optional[list] = None):
    """Call Gemini and validate. On invalid output retry (max MAX_VALIDATION_RETRIES) with the error in the prompt."""
    prompt, err = prompt_text, None
    for attempt in range(C.MAX_VALIDATION_RETRIES + 1):
        if err:
            prompt = (prompt_text + "\n\nYour previous answer was INVALID:\n" + err[:1500]
                      + "\nReturn corrected JSON only, following the schema exactly.")
        parts = [{"text": prompt}]
        for ref in images or []:                     # thumbnails so Gemini can judge which figures matter
            parts.append({"text": f"IMAGE {ref.id}:"})
            parts.append({"inline_data": {"mime_type": "image/jpeg",
                                          "data": base64.b64encode(ref.thumb).decode()}})
        raw = _call(parts, system)
        try:
            return validate(_parse_json(raw))
        except (ValueError, ValidationError) as e:  # JSONDecodeError is a ValueError
            err = str(e)
            log.warning("Invalid JSON (attempt %d): %s", attempt + 1, err[:300])
    raise GeminiError("Gemini returned invalid JSON after retries: " + (err or "")[:300])


def ocr_image(png: bytes) -> str:
    b64 = base64.b64encode(png).decode()
    return _call([{"text": C.OCR_PROMPT}, {"inline_data": {"mime_type": "image/png", "data": b64}}],
                 json_mode=False, temperature=0)


# ---------------------------------------------------------------- study guide
def _is_revision(heading: str) -> bool:
    return heading.strip().lower().rstrip(":").endswith("quick revision")


def outline(guide: StudyGuide) -> str:
    """Flat plain text of a guide (for quiz / revision prompts)."""
    out = [guide.title]
    for s in guide.sections:
        out.append(f"\n## {s.heading}")
        for b in s.blocks:
            d = b.model_dump()
            t = d["type"]
            if t in ("bullets", "numbered"):
                out += [f"- {x}" for x in d["items"]]
            elif t == "table":
                en = lambda c: c.split("|||")[0].strip()  # English half only
                out.append(" | ".join(en(h) for h in d["headers"]))
                out += [" | ".join(en(c) for c in r) for r in d["rows"]]
            elif t == "formula":
                out.append(f"{d['formula']}  {d['example']}")
            elif t == "image":
                out.append(f"[Figure: {d['caption']}]")
            else:
                out.append(d["text"])
    return "\n".join(out).replace("**", "")


def _validate_revision(d: dict):
    items = [str(x) for x in d.get("items", [])]
    if len(items) < 3:
        raise ValueError("need 6-10 items")
    return items[:10], [str(x) for x in d.get("items_ar", [])][:10]


def _build_revision(guide: StudyGuide):
    try:
        return generate_json(C.REVISION_PROMPT + "\n\n" + outline(guide)[:30000], None, _validate_revision)
    except GeminiError:
        return None


def _fallback_revision(guide: StudyGuide):
    pts = [(b.text, b.ar) for s in guide.sections for b in s.blocks if b.type == "key_point"][:10]
    if not pts:
        pts = [(s.heading, s.heading_ar) for s in guide.sections[:8]]
    return [p[0] for p in pts], [p[1] for p in pts]


MAX_IMAGES_PER_CHUNK = 20


def _clean_images(guide: StudyGuide, allowed: set[str]) -> StudyGuide:
    """Drop image blocks that reference unknown ids or repeat an id."""
    seen: set[str] = set()
    for s in guide.sections:
        keep = []
        for b in s.blocks:
            if b.type == "image":
                if b.image_id not in allowed or b.image_id in seen:
                    continue
                seen.add(b.image_id)
            keep.append(b)
        s.blocks = keep
    return guide


def generate_study_guide(ex: Extracted, progress: Callable[[str], None] = lambda m: None) -> StudyGuide:
    chunks = chunk_units(ex.units, C.CHUNK_CHARS)
    n = len(chunks)
    guides: list[StudyGuide] = []
    for i, chunk in enumerate(chunks, 1):
        progress(f"Generating study guide ({i}/{n})..." if n > 1 else "Generating study guide...")
        note = (C.CHUNK_NOTE.format(i=i, n=n) + "\n\n") if n > 1 else ""
        ids = list(dict.fromkeys(MARKER.findall(chunk)))
        ids = [x for x in ids if x in ex.images][:MAX_IMAGES_PER_CHUNK]
        prompt = f"{C.SCHEMA_DESCRIPTION}\n\n{note}LECTURE TEXT:\n{chunk}"
        g = generate_json(prompt, C.SYSTEM_PROMPT, StudyGuide.model_validate, [ex.images[x] for x in ids])
        guides.append(_clean_images(g, set(ids)))

    merged = StudyGuide(
        title=guides[0].title, title_ar=guides[0].title_ar, subtitle=guides[0].subtitle,
        theme=guides[0].theme,
        sections=[s for g in guides for s in g.sections if not _is_revision(s.heading)] or guides[0].sections)
    revision = None
    if n == 1:
        revision = next((s for s in guides[0].sections if _is_revision(s.heading)), None)
    if revision is None:
        progress("Building quick revision...")
        items, items_ar = _build_revision(merged) or _fallback_revision(merged)
        revision = Section(heading="Quick Revision", heading_ar="مراجعة سريعة",
                           blocks=[Bullets(type="bullets", items=items, items_ar=items_ar)])
    merged.sections.append(revision)
    return merged
