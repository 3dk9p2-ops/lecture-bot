"""Pydantic schema for the Gemini bilingual study-guide JSON."""
from __future__ import annotations

from typing import Annotated, List, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _B(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Paragraph(_B):
    type: Literal["paragraph"]
    text: str
    ar: str = ""


class Subheading(_B):
    type: Literal["subheading"]
    text: str
    ar: str = ""


class Bullets(_B):
    type: Literal["bullets"]
    items: List[str]
    items_ar: List[str] = []


class Numbered(_B):
    type: Literal["numbered"]
    items: List[str]
    items_ar: List[str] = []


class Table(_B):
    """Cells may be 'English ||| Arabic' to show both languages in one cell."""
    type: Literal["table"]
    headers: List[str]
    rows: List[List[str]]

    @field_validator("rows")
    @classmethod
    def _pad(cls, rows, info):
        n = len(info.data.get("headers", []))
        return [[str(c) for c in r] + [""] * (n - len(r)) for r in rows]


class KeyPoint(_B):
    type: Literal["key_point"]
    text: str
    ar: str = ""


class InfoBox(_B):
    type: Literal["info_box"]
    text: str
    ar: str = ""


class WarningBox(_B):
    type: Literal["warning_box"]
    text: str
    ar: str = ""


class Formula(_B):
    type: Literal["formula"]
    formula: str
    example: str = ""
    example_ar: str = ""


class Image(_B):
    type: Literal["image"]
    image_id: str
    caption: str = ""
    caption_ar: str = ""


Block = Annotated[
    Union[Paragraph, Subheading, Bullets, Numbered, Table, KeyPoint, InfoBox, WarningBox, Formula, Image],
    Field(discriminator="type"),
]


class Section(_B):
    heading: str
    heading_ar: str = ""
    blocks: List[Block]


class StudyGuide(_B):
    title: str
    title_ar: str = ""
    subtitle: str = ""
    theme: str = "blue"
    sections: List[Section] = Field(min_length=1)

    @field_validator("theme", mode="before")
    @classmethod
    def _theme(cls, v):
        from .constants import THEMES
        v = str(v or "blue").strip().lower()
        return v if v in THEMES else "blue"
