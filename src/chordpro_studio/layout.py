"""Intermediate layout models and SongDocument -> SongLayout builder."""

from __future__ import annotations

from dataclasses import dataclass, field

from chordpro_studio.models import (
    CapoStatus,
    LineType,
    SongDocument,
    SongLine,
)


class LayoutError(ValueError):
    """Raised when a SongDocument contains invalid layout data (e.g., out-of-bounds char_index)."""


@dataclass(frozen=True)
class HeaderMetadata:
    """Displayable header metadata for the first page."""

    title: str
    artist: str
    capo_label: str | None = None


@dataclass(frozen=True)
class ChordSegment:
    """A chord anchored above a slice of lyric text."""

    chord: str | None
    text: str


@dataclass(frozen=True)
class RenderedPhrase:
    """A single logical lyric phrase broken into chord-aligned segments."""

    segments: list[ChordSegment] = field(default_factory=list)


@dataclass(frozen=True)
class LyricPair:
    """One or two lyric phrases arranged side-by-side."""

    left: RenderedPhrase
    right: RenderedPhrase | None = None


@dataclass(frozen=True)
class ChordOnlyItem:
    """A chord in a chords-only row with relative spacing before it."""

    chord: str
    gap_before: int = 0


@dataclass(frozen=True)
class ChordOnlyRow:
    """A pure chord row, optionally split into bar-separated groups."""

    groups: list[list[ChordOnlyItem]] = field(default_factory=list)


@dataclass(frozen=True)
class BlankRow:
    """An explicit blank spacer row."""


LayoutRow = LyricPair | ChordOnlyRow | BlankRow


@dataclass(frozen=True)
class LayoutSection:
    """A named section containing ordered layout rows."""

    id: str
    name: str
    show_label: bool
    rows: list[LayoutRow] = field(default_factory=list)


@dataclass(frozen=True)
class SongLayout:
    """Complete intermediate layout representation of a song."""

    header: HeaderMetadata
    sections: list[LayoutSection] = field(default_factory=list)


def phrase_from_song_line(line: SongLine) -> RenderedPhrase:
    """Convert a lyric SongLine into a RenderedPhrase without truncating invalid anchors."""
    lyrics = line.lyrics
    lyric_len = len(lyrics)

    if not line.chords:
        return RenderedPhrase(segments=[ChordSegment(chord=None, text=lyrics)])

    sorted_chords = sorted(line.chords, key=lambda c: (c.char_index, c.chord_index))
    for anchor in sorted_chords:
        if anchor.char_index < 0 or anchor.char_index > lyric_len:
            raise LayoutError(
                f"ChordAnchor {anchor.name!r} has char_index={anchor.char_index}, "
                f"which is out of bounds for lyrics of length {lyric_len}."
            )

    segments: list[ChordSegment] = []
    first_idx = sorted_chords[0].char_index
    if first_idx > 0:
        segments.append(ChordSegment(chord=None, text=lyrics[:first_idx]))

    for i, anchor in enumerate(sorted_chords):
        start = anchor.char_index
        end = sorted_chords[i + 1].char_index if i + 1 < len(sorted_chords) else lyric_len
        text_slice = lyrics[start:end]
        segments.append(ChordSegment(chord=anchor.name, text=text_slice))

    return RenderedPhrase(segments=segments)


def chord_only_from_song_line(line: SongLine) -> ChordOnlyRow:
    """Convert a CHORDS_ONLY SongLine into a ChordOnlyRow preserving relative spacing."""
    import re

    sorted_chords = sorted(line.chords, key=lambda c: (c.char_index, c.chord_index))
    if line.raw_text is not None:
        raw_names = [m.strip() for m in re.findall(r"\[([^\[\]]+)\]", line.raw_text) if m.strip()]
        model_names = [c.name for c in sorted_chords]
        if raw_names != model_names:
            raise LayoutError(
                f"Inconsistent chords_only raw_text {raw_names} vs chords {model_names}."
            )
        groups: list[list[ChordOnlyItem]] = []
        for part in line.raw_text.split("|"):
            items: list[ChordOnlyItem] = []
            cursor = 0
            for match in re.finditer(r"\[([^\[\]]+)\]", part):
                name = match.group(1).strip()
                if not name:
                    continue
                gap = len(part[cursor : match.start()])
                items.append(ChordOnlyItem(chord=name, gap_before=gap))
                cursor = match.end()
            if items:
                groups.append(items)
        if groups:
            return ChordOnlyRow(groups=groups)

    items_fallback: list[ChordOnlyItem] = []
    prev_idx = 0
    for i, c in enumerate(sorted_chords):
        gap = max(0, c.char_index - prev_idx) if i > 0 else c.char_index
        items_fallback.append(ChordOnlyItem(chord=c.name, gap_before=gap))
        prev_idx = c.char_index
    return ChordOnlyRow(groups=[items_fallback] if items_fallback else [])


def build_layout(doc: SongDocument) -> SongLayout:
    """Build a `SongLayout` from a `SongDocument` without mutating the input."""
    capo_label: str | None = None
    if doc.capo.status == CapoStatus.KNOWN and doc.capo.value is not None:
        capo_label = f"Capo：{doc.capo.value}"

    header = HeaderMetadata(
        title=doc.title,
        artist=doc.artist,
        capo_label=capo_label,
    )

    layout_sections: list[LayoutSection] = []
    show_section_labels = len(doc.sections) > 1

    for sec in sorted(doc.sections, key=lambda s: s.order):
        rows: list[LayoutRow] = []
        pending_phrase: RenderedPhrase | None = None

        for line in sec.lines:
            if line.line_type in (LineType.LYRIC_WITH_CHORDS, LineType.LYRIC_ONLY):
                phrase = phrase_from_song_line(line)
                if pending_phrase is None:
                    pending_phrase = phrase
                else:
                    rows.append(LyricPair(left=pending_phrase, right=phrase))
                    pending_phrase = None
            elif line.line_type == LineType.CHORDS_ONLY:
                if pending_phrase is not None:
                    rows.append(LyricPair(left=pending_phrase, right=None))
                    pending_phrase = None
                rows.append(chord_only_from_song_line(line))
            elif line.line_type == LineType.BLANK:
                if pending_phrase is not None:
                    rows.append(LyricPair(left=pending_phrase, right=None))
                    pending_phrase = None
                rows.append(BlankRow())

        if pending_phrase is not None:
            rows.append(LyricPair(left=pending_phrase, right=None))

        layout_sections.append(
            LayoutSection(
                id=sec.id,
                name=sec.name,
                show_label=show_section_labels or sec.name.lower() != "main",
                rows=rows,
            )
        )

    return SongLayout(header=header, sections=layout_sections)
