"""Parser-independent source records and strict model-response contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BlockKind = Literal[
    "heading",
    "paragraph",
    "list",
    "table",
    "equation",
    "question",
    "answer_key",
    "figure",
    "caption",
    "footnote",
    "header",
    "footer",
    "annotation",
    "unknown",
]


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegionProposal(StrictModel):
    kind: BlockKind
    bbox: tuple[float, float, float, float]

    @model_validator(mode="after")
    def valid_box(self) -> RegionProposal:
        x0, y0, x1, y1 = self.bbox
        if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
            raise ValueError("Region coordinates must be ordered within 0..1000")
        return self


class Inventory(StrictModel):
    regions: list[RegionProposal] = Field(max_length=64)
    complete: bool
    blank: bool = False
    printed_page_label: str | None = None

    @model_validator(mode="after")
    def nonempty(self) -> Inventory:
        if self.blank == bool(self.regions):
            raise ValueError("A nonblank page needs regions; a blank page cannot have regions")
        return self


class Cell(StrictModel):
    cell_id: str | None = None
    row: int = Field(ge=0, le=1000)
    column: int = Field(ge=0, le=1000)
    row_span: int = Field(default=1, ge=1, le=1000)
    column_span: int = Field(default=1, ge=1, le=1000)
    text: str = Field(max_length=20000)
    state: Literal["VALUE", "BLANK", "UNREADABLE", "AMBIGUOUS", "COVERED_BY_MERGE", "STRUCTURE_UNKNOWN"] = (
        "VALUE"
    )
    header: bool = False
    header_refs: list[str] = Field(default_factory=list, max_length=100)
    unit: str | None = None


class SourceRelationship(StrictModel):
    kind: Literal[
        "continuation",
        "caption_of",
        "illustrates",
        "shared_passage",
        "answer_for",
        "footnote_for",
        "parent_section",
    ]
    target_id: str = Field(min_length=1, max_length=100)


class QuestionPart(StrictModel):
    label: str
    text: str


class Reading(StrictModel):
    kind: BlockKind
    text: str = Field(max_length=200000)
    complete: bool
    blank: bool = False
    uncertain: bool = False
    cells: list[Cell] = Field(default_factory=list, max_length=1000)
    latex: str | None = None
    printed_label: str | None = None
    printed_caption: str | None = None
    figure_labels: list[str] = Field(default_factory=list, max_length=100)
    handwritten_annotation: str | None = None
    observed_relationships: list[str] = Field(default_factory=list, max_length=100)
    derived_description: str | None = None
    option_labels: list[str] = Field(default_factory=list, max_length=100)
    printed_answer: str | None = None
    continues_from_previous: bool = False
    continues_on_next: bool = False
    question_parts: list[QuestionPart] = Field(default_factory=list, max_length=100)
    options: list[QuestionPart] = Field(default_factory=list, max_length=100)
    marks: str | None = None
    instructions: str | None = None
    relationships: list[SourceRelationship] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def meaningful(self) -> Reading:
        if self.blank and (self.text or self.cells or self.figure_labels):
            raise ValueError("Blank regions cannot contain extracted values")
        if not self.blank and not (self.text or self.cells or self.figure_labels or self.kind == "figure"):
            raise ValueError("Nonblank reading needs source content")
        return self


def parse_response(raw: Any, schema: type[Inventory] | type[Reading]) -> Inventory | Reading:
    if not isinstance(raw, str):
        raise ValueError("Expected a JSON text response")
    value = raw.strip()
    if value.startswith("```json") and value.endswith("```"):
        value = value[7:-3].strip()
    elif value.startswith("```") and value.endswith("```"):
        value = value[3:-3].strip()
    return schema.model_validate_json(value)
