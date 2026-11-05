"""Prompts, CSS and limits for the lecture study-guide pipeline."""

SYSTEM_PROMPT = (
    "You convert a university lecture (Medical Laboratory Techniques, Iraq) into a study handout in two "
    "languages. Rules: (1) Cover EVERYTHING in the lecture, in its order, nothing important left out. "
    "(2) The English text stays English and follows the lecture's wording. Every Arabic field ('ar', "
    "'items_ar', 'heading_ar', 'title_ar', 'caption_ar', 'example_ar', or an 'English ||| Arabic' cell) is a "
    "LITERAL translation of the English text next to it: sentence for sentence, same meaning, same order. "
    "Do not explain, do not add or remove information, do not paraphrase, do not use dialect. Keep scientific "
    "terms, abbreviations, drug and test names, units and numbers in English inside the Arabic. "
    "(3) Never invent facts or numbers; use only the lecture's values, cut-offs and wording. If something is "
    "not stated, skip it. (4) Wrap only the exam-critical terms, numbers, times, volumes, wavelengths and key "
    "facts in **double asterisks** in the ENGLISH text (they become bold). Bold a lot of short terms, never "
    "whole sentences. Do not put asterisks in Arabic fields. (5) Use tables for comparisons, steps with "
    "parameters, normal values and causes; in table cells and headers write 'English ||| Arabic'. (6) Include "
    "the WHY behind each rule when the lecture states it. (7) Put worked calculation examples inside formula "
    "blocks. (8) IMAGES: the lecture text contains markers like [IMAGE img_3] and the pictures are attached. "
    "Insert an image block (with a short English caption and a literal Arabic caption) at the right place ONLY "
    "for important scientific figures: diagrams, mechanisms, pathways, graphs, instruments, microscopy, flow "
    "charts, tables-as-pictures. Skip logos, icons, decorations, photos of people and repeated pictures. Use "
    "only the given image ids. (9) For a bullet or numbered item that is just a name, term or code (for example "
    "an enzyme name), write an EMPTY string in its items_ar slot. (10) End with a quick_revision section of "
    "6-10 one-line points. Return JSON only."
)

SCHEMA_DESCRIPTION = """JSON schema (return exactly this shape, nothing else):
{ "title": str, "title_ar": str, "subtitle": str,
  "sections": [ { "heading": str, "heading_ar": str, "blocks": [ block, ... ] } ] }
Block types (field "type"). Every "ar" field is the LITERAL Arabic translation of the English text next to it:
- {"type":"paragraph","text":str,"ar":str}
- {"type":"subheading","text":str,"ar":str}
- {"type":"bullets","items":[str],"items_ar":[str]}      (items_ar aligned 1:1 with items)
- {"type":"numbered","items":[str],"items_ar":[str]}
- {"type":"table","headers":[str],"rows":[[str]]}          (cells may be "English ||| Arabic")
- {"type":"key_point","text":str,"ar":str}                 (exam-critical points)
- {"type":"info_box","text":str,"ar":str}                  (definitions / reminders)
- {"type":"warning_box","text":str,"ar":str}               (discard / never / danger rules)
- {"type":"formula","formula":str,"example":str,"example_ar":str}
- {"type":"image","image_id":"img_N","caption":str,"caption_ar":str}
Do not number the section headings (numbering is added automatically).
The LAST section must be headed "Quick Revision" (heading_ar "مراجعة سريعة") with one bullets block of 6-10 one-line points (with items_ar)."""

CHUNK_NOTE = (
    "This is PART {i} of {n} of a long lecture. Cover only the text in this part, in order. "
    "Do NOT add a Quick Revision section (it is built later). Use the same title/subtitle style."
)

REVISION_PROMPT = (
    "Below is a condensed outline of a finished study guide. Return JSON only: "
    '{"items": [6 to 10 one-line English quick-revision points, each wrapping the critical term/number in '
    '**double asterisks**], "items_ar": [the same points as a literal Arabic translation, scientific terms '
    "kept in English, same order]}. Use only facts that appear in the outline."
)

QUIZ_PROMPT = (
    "From the study-guide content below, write {n} English multiple-choice exam questions for a "
    "Medical Laboratory Techniques student. Use only facts in the content. Each question has exactly "
    "4 options and exactly one correct answer. Keep the question under 280 characters, each option "
    "under 95 characters, the explanation under 190 characters. Do not use markdown or asterisks. "
    'Return JSON only: {{"questions":[{{"question":str,"options":[str,str,str,str],'
    '"correct_index":0-3,"explanation":str}}]}}'
)

OCR_PROMPT = (
    "Transcribe ALL text on this page exactly as written (tables as rows separated by ' | '). "
    "Return the text only, no commentary."
)

FIXED_CSS = """
@page{size:A4;margin:16mm 15mm}
body{font-family:"Liberation Sans",Arial,Helvetica,sans-serif;font-size:11.5pt;line-height:1.5;color:#1a1a1a}
h1{font-size:22pt;margin:0 0 2pt;color:#0b3d6b}
.sub{color:#555;font-size:10pt;margin-bottom:8pt;border-bottom:3px solid #0b3d6b;padding-bottom:8pt}
.sig{font-size:9.5pt;color:#0b3d6b;background:#f3f7fb;border:1px solid #9bbbd8;border-radius:3pt;padding:3pt 8pt;margin:0 0 12pt;display:inline-block}
h2{font-size:15pt;background:#0b3d6b;color:#fff;padding:5pt 10pt;border-radius:4pt;margin:18pt 0 8pt;page-break-after:avoid}
h3{font-size:12.5pt;color:#0b3d6b;border-bottom:1.5px solid #9bbbd8;padding-bottom:2pt;margin:12pt 0 6pt;page-break-after:avoid}
strong{font-weight:bold;color:#0b3d6b}
ol,ul{margin:4pt 0 6pt 0;padding-left:20pt}li{margin-bottom:3pt}
.key{border-left:5px solid #e65100;background:#fff3e0;padding:6pt 10pt;margin:8pt 0;page-break-inside:avoid}
.key b:first-child{color:#e65100}
.box{border:1.5px solid #0b3d6b;background:#eef4fa;padding:6pt 10pt;margin:8pt 0;page-break-inside:avoid}
.red{border:1.5px solid #b00020;background:#fdecea;padding:6pt 10pt;margin:8pt 0;page-break-inside:avoid}
table{border-collapse:collapse;width:100%;margin:6pt 0 10pt;font-size:10pt}
tr{page-break-inside:avoid}
th{background:#0b3d6b;color:#fff;text-align:left;padding:5pt 7pt;border:1px solid #0b3d6b}
td{padding:5pt 7pt;border:1px solid #9bbbd8;vertical-align:top}
tr:nth-child(even) td{background:#f3f7fb}
td:first-child{font-weight:bold}
.formula{text-align:center;font-size:13pt;font-weight:bold;background:#e8f5e9;border:1.5px solid #2e7d32;padding:7pt;margin:8pt 0;border-radius:4pt}

/* --- bilingual + figures --- */
h1,h2,h3{break-after:avoid-page}
h2+*,h3+*{break-before:avoid-page}
.ar{direction:rtl;text-align:right;unicode-bidi:plaintext;font-family:"Noto Naskh Arabic","Noto Sans Arabic","Segoe UI",Tahoma,Arial,sans-serif;font-size:12.5pt;line-height:1.8;color:#222;background:#f4f6f9;border-right:4px solid #5b7a99;border-radius:3pt;padding:4pt 9pt;margin:4pt 0 6pt}
li{break-inside:avoid}
p{break-inside:avoid}
li .ar{font-size:12pt;padding:2pt 8pt;margin:2pt 0 5pt}
h1 .ar,h2 .ar,h3 .ar{display:block;font-weight:normal;font-size:.85em;background:none;border:0;padding:0;margin:2pt 0 0}
h2 .ar{color:#dbe8f5}
h1 .ar{color:#444}
h3 .ar{color:#3d5a73}
.key .ar,.box .ar,.red .ar{background:none;border-right:0;border-top:1px dashed #bbb;border-radius:0;margin:5pt 0 0;padding:4pt 0 0}
td .ar,th .ar{font-size:10.5pt;line-height:1.55;background:none;border:0;padding:0;margin:1pt 0 0}
th .ar{color:#dbe8f5}
td:first-child .ar{font-weight:normal}
figure{margin:8pt 0;text-align:center;page-break-inside:avoid}
figure img{max-width:100%;max-height:105mm;border:1px solid #9bbbd8;border-radius:3pt}
figcaption{font-size:9.5pt;color:#444;margin-top:3pt}
figcaption .ar{text-align:center;font-size:11pt;background:none;border:0}
"""

# Limits
CHUNK_CHARS = 14000              # max lecture characters per Gemini call
MAX_VALIDATION_RETRIES = 2
TG_QUESTION_MAX = 300
TG_OPTION_MAX = 100
TG_EXPLANATION_MAX = 200
TG_MESSAGE_MAX = 4000
TG_DOWNLOAD_MAX = 20 * 1024 * 1024   # Bot API getFile limit
TG_UPLOAD_MAX = 50 * 1024 * 1024     # Bot API sendDocument limit
SUPPORTED_EXT = (".docx", ".pptx", ".pdf")

# Kept for compatibility with older code paths (not used by the current pipeline).
ARABIC_PROMPT = (
    "Translate the lecture below into Arabic, sentence by sentence, literally. Keep scientific terms, "
    "numbers and units in English. Plain text only."
)
