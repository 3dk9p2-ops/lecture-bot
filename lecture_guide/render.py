"""JSON -> HTML (Jinja2, escaped) -> PDF (Playwright chromium, A4). English + literal Arabic."""
from __future__ import annotations

import base64
import re
from html import escape as html_escape
from typing import Optional

from jinja2 import Environment
from markupsafe import Markup, escape

from . import constants as C
from .schema import StudyGuide

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


def hl(text) -> Markup:
    """Escape everything, then turn **term** into bold text (no highlight). Stray ** are dropped."""
    s = str(escape(str(text if text is not None else "")))
    s = _BOLD.sub(r"<strong>\1</strong>", s)
    return Markup(s.replace("**", ""))


def plain(text) -> str:
    return str(text or "").replace("**", "")


def ar(text) -> Markup:
    """Arabic line under an English part (empty -> nothing)."""
    t = str(text or "").replace("**", "").strip()
    return Markup(f'<div class="ar" dir="rtl" lang="ar">{escape(t)}</div>') if t else Markup("")


def cell(text) -> Markup:
    """'English ||| Arabic' table cell."""
    en, _, a = str(text or "").partition("|||")
    return Markup(f"{hl(en.strip())}{ar(a)}")


def at(lst, i) -> str:
    return lst[i] if lst and i < len(lst) else ""


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{{ g.title|plain }}</title>
<style>{{ css|safe }}</style></head><body>
<h1>{{ g.title|hl }}{{ g.title_ar|ar }}</h1>
<div class="sub">{{ g.subtitle|hl }}</div>
{% if signature %}<div class="sig"><span>Translated by: {{ signature }}</span><span class="sar" dir="rtl" lang="ar">تمت الترجمة بواسطة: {{ signature }}</span></div>{% endif %}
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


def render_html(guide: StudyGuide, images: Optional[dict] = None, signature: str = "") -> str:
    return _tpl.render(g=guide, css=C.build_css(guide.theme), images=_data_uris(images), signature=signature.strip())


def _footer(signature: str, color: str = "#0b3d6b") -> str:
    """Footer on every page: translator signature chip (if any) + page numbers."""
    sig = ""
    if signature.strip():
        name = html_escape(signature.strip())
        sig = (f'<span style="background:{color};color:#fff;padding:2px 10px;border-radius:10px;font-weight:bold;-webkit-print-color-adjust:exact;print-color-adjust:exact">'
               f'Translated by: {name} &nbsp;|&nbsp; تمت الترجمة بواسطة: {name}</span>')
    return ('<div style="width:100%;font-size:10px;color:#555;padding:0 15mm;-webkit-print-color-adjust:exact;display:flex;'
            'justify-content:space-between;align-items:center;font-family:Arial,sans-serif">'
            f'<span>{sig}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')


def html_to_pdf(html: str, out_path: str, signature: str = "", color: str = "#0b3d6b") -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(path=out_path, format="A4", print_background=True, prefer_css_page_size=True,
                     display_header_footer=True, header_template="<div></div>",
                     footer_template=_footer(signature, color))
        finally:
            browser.close()
    return out_path


def render_pdf(guide: StudyGuide, out_path: str, images: Optional[dict] = None, signature: str = "") -> str:
    return html_to_pdf(render_html(guide, images, signature), out_path, signature, C.THEMES.get(guide.theme, C.THEMES["blue"])[0])
