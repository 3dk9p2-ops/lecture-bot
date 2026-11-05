"""JSON -> HTML (Jinja2, escaped) -> PDF (Playwright chromium, A4). Bilingual EN + Iraqi Arabic."""
from __future__ import annotations

import base64
import re
from typing import Optional

from jinja2 import Environment
from markupsafe import Markup, escape

from . import constants as C
from .schema import StudyGuide

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


def hl(text) -> Markup:
    """Escape everything, then turn **bold** markers into <mark>. Stray ** are dropped."""
    s = str(escape(str(text if text is not None else "")))
    s = _BOLD.sub(r"<mark>\1</mark>", s)
    return Markup(s.replace("**", ""))


def plain(text) -> str:
    return str(text or "").replace("**", "")


def ar(text) -> Markup:
    """Arabic line under an English part (empty -> nothing)."""
    t = str(text or "").strip()
    return Markup(f'<div class="ar" dir="rtl" lang="ar">{hl(t)}</div>') if t else Markup("")


def cell(text) -> Markup:
    """'English ||| Arabic' table cell."""
    en, _, a = str(text or "").partition("|||")
    return Markup(f"{hl(en.strip())}{ar(a)}")


def at(lst, i) -> str:
    return lst[i] if lst and i < len(lst) else ""


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{{ g.title|plain }}</title>
<style>{{ css }}</style></head><body>
<h1>{{ g.title|hl }}{{ g.title_ar|ar }}</h1>
<div class="sub">{{ g.subtitle|hl }}</div>
{% for s in g.sections %}
<h2>{{ loop.index }}. {{ s.heading|hl }}{{ s.heading_ar|ar }}</h2>
{% for b in s.blocks %}
{%- if b.type == 'paragraph' %}<p>{{ b.text|hl }}{{ b.ar|ar }}</p>
{%- elif b.type == 'subheading' %}<h3>{{ b.text|hl }}{{ b.ar|ar }}</h3>
{%- elif b.type == 'bullets' %}<ul>{% for i in b.items %}<li>{{ i|hl }}{{ at(b.items_ar, loop.index0)|ar }}</li>{% endfor %}</ul>
{%- elif b.type == 'numbered' %}<ol>{% for i in b.items %}<li>{{ i|hl }}{{ at(b.items_ar, loop.index0)|ar }}</li>{% endfor %}</ol>
{%- elif b.type == 'table' %}<table><thead><tr>{% for h in b.headers %}<th>{{ h|cell }}</th>{% endfor %}</tr></thead>
<tbody>{% for r in b.rows %}<tr>{% for c in r %}<td>{{ c|cell }}</td>{% endfor %}</tr>{% endfor %}</tbody></table>
{%- elif b.type == 'key_point' %}<div class="key"><b>Key Point:</b> {{ b.text|hl }}{{ b.ar|ar }}</div>
{%- elif b.type == 'info_box' %}<div class="box">{{ b.text|hl }}{{ b.ar|ar }}</div>
{%- elif b.type == 'warning_box' %}<div class="red">{{ b.text|hl }}{{ b.ar|ar }}</div>
{%- elif b.type == 'formula' %}<div class="formula">{{ b.formula|plain }}</div>
{%- if b.example %}<p><b>Example:</b> {{ b.example|hl }}{{ b.example_ar|ar }}</p>{% endif %}
{%- elif b.type == 'image' and b.image_id in images %}<figure><img src="{{ images[b.image_id] }}" alt="">
{%- if b.caption or b.caption_ar %}<figcaption>{{ b.caption|hl }}{{ b.caption_ar|ar }}</figcaption>{% endif %}</figure>
{%- endif %}
{% endfor %}
{% endfor %}
</body></html>"""

_env = Environment(autoescape=True)
_env.filters.update(hl=hl, plain=plain, ar=ar, cell=cell)
_env.globals["at"] = at
_tpl = _env.from_string(_TEMPLATE)


def _data_uris(images: Optional[dict]) -> dict:
    return {k: f"data:{r.mime};base64,{base64.b64encode(r.data).decode()}" for k, r in (images or {}).items()}


def render_html(guide: StudyGuide, images: Optional[dict] = None) -> str:
    return _tpl.render(g=guide, css=C.FIXED_CSS, images=_data_uris(images))


def html_to_pdf(html: str, out_path: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(path=out_path, format="A4", print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()
    return out_path


def render_pdf(guide: StudyGuide, out_path: str, images: Optional[dict] = None) -> str:
    return html_to_pdf(render_html(guide, images), out_path)
