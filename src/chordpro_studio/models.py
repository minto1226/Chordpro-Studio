"""Core data models for ChordPro Studio."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class CapoStatus(StrEnum):
    """Extraction status of capo information."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    FAILED = "failed"


class CapoInfo(BaseModel):
    """Capo value and extraction status.

    Explicitly distinguishes Capo 0 (status='known', value=0) from
    unknown/failed extraction (status='unknown'|'failed', value=None).
    """

    status: CapoStatus
    value: int | None = Field(default=None, ge=0, le=12)
    raw_text: str | None = Field(
        default=None,
        description="Original capo text from the source page (e.g., 'カポなし', 'Capo 2').",
    )

    @model_validator(mode="after")
    def validate_status_and_value(self) -> CapoInfo:
        if self.status == CapoStatus.KNOWN and self.value is None:
            raise ValueError("CapoInfo with status='known' must have an integer value (0-12).")
        if self.status in (CapoStatus.UNKNOWN, CapoStatus.FAILED) and self.value is not None:
            raise ValueError(
                f"CapoInfo with status='{self.status}' must have value=None, not {self.value}."
            )
        return self


class ChordAnchor(BaseModel):
    """A chord anchored to a Unicode character index in a lyric line."""

    name: str = Field(min_length=1, description="Chord symbol, e.g. 'F#m7', 'Bb', 'C/G'.")
    char_index: int = Field(
        ge=0,
        description=(
            "0-based Unicode code point index in lyrics for lyric lines; "
            "plain-text character offset after stripping chord markers for chords_only."
        ),
    )
    chord_index: int = Field(
        ge=0,
        description="0-based order of this chord within the line.",
    )


class LineType(StrEnum):
    """Classification of a song line."""

    LYRIC_WITH_CHORDS = "lyric_with_chords"
    CHORDS_ONLY = "chords_only"
    LYRIC_ONLY = "lyric_only"
    BLANK = "blank"


class SongLine(BaseModel):
    """A single line within a song section."""

    line_type: LineType
    lyrics: str = ""
    chords: list[ChordAnchor] = Field(default_factory=list)
    raw_text: str | None = Field(
        default=None,
        description=(
            "Optional original raw line text (preserves exact spacing on chords_only lines)."
        ),
    )

    @model_validator(mode="after")
    def validate_line_consistency(self) -> SongLine:
        if self.line_type == LineType.BLANK and (self.lyrics != "" or self.chords):
            raise ValueError("Blank line must have empty lyrics and no chords.")
        if self.line_type == LineType.CHORDS_ONLY:
            if self.lyrics != "":
                raise ValueError("Chords-only line must have empty lyrics.")
            if not self.chords:
                raise ValueError("Chords-only line must contain at least one chord.")
        if self.line_type == LineType.LYRIC_ONLY and self.chords:
            raise ValueError("Lyric-only line must not contain chords.")
        return self


class Section(BaseModel):
    """A named, ordered section of a song (e.g. Intro, Verse 1, Chorus)."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    order: int = Field(ge=0)
    lines: list[SongLine] = Field(default_factory=list)


class SourceDiagnostics(BaseModel):
    """Provenance and diagnostic information from scraping or importing."""

    source_type: str = Field(
        description="Origin type, e.g. 'web_import', 'chordpro_import', 'manual'."
    )
    fetched_at: datetime | None = None
    parser_version: str | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional non-lossy metadata preserved from source.",
    )


class SongDocument(BaseModel):
    """Intermediate canonical representation of a song."""

    schema_version: str = "1.0.0"
    title: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    source_url: str | None = None
    capo: CapoInfo
    sections: list[Section] = Field(default_factory=list)
    diagnostics: SourceDiagnostics


class PdfRenderOptions(BaseModel):
    """Input options contract for the future PDF renderer."""

    page_size: str = "A4"
    show_capo: bool = True
    font_family: str | None = None
