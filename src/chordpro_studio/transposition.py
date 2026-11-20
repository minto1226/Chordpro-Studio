"""Independent Capo transposition engine for SongDocument and chord symbols."""

from __future__ import annotations

import re

from chordpro_studio.models import (
    CapoInfo,
    CapoStatus,
    ChordAnchor,
    LineType,
    Section,
    SongDocument,
    SongLine,
    SourceDiagnostics,
)

NOTE_TO_SEMITONE: dict[str, int] = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
}

SHARP_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NOTES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

NON_PITCH_CHORDS = {"N.C.", "NC", "X", "-", "%"}
CHORD_PARSE_RE = re.compile(r"^([A-G](?:#|b)?)([^/]*?)(?:/([A-G](?:#|b)?))?$")
CHORD_TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")


class TranspositionError(ValueError):
    """Raised when a chord cannot be parsed or Capo transposition is invalid."""


def _transpose_note(note: str, semitones: int) -> str:
    if note not in NOTE_TO_SEMITONE:
        raise TranspositionError(f"Unrecognized note: {note!r}")
    new_idx = (NOTE_TO_SEMITONE[note] + semitones) % 12
    table = FLAT_NOTES if "b" in note else SHARP_NOTES
    return table[new_idx]


def transpose_chord(chord: str, semitones: int) -> str:
    """Transpose a single chord symbol by `semitones` (12-TET)."""
    cleaned = chord.strip()
    if semitones == 0 or cleaned in NON_PITCH_CHORDS:
        return cleaned

    match = CHORD_PARSE_RE.match(cleaned)
    if not match:
        raise TranspositionError(f"Unrecognized chord symbol: {chord!r}")

    root, suffix, bass = match.group(1), match.group(2), match.group(3)
    new_root = _transpose_note(root, semitones)
    if bass is not None:
        new_bass = _transpose_note(bass, semitones)
        return f"{new_root}{suffix}/{new_bass}"
    return f"{new_root}{suffix}"


def _transpose_raw_text(raw_text: str, semitones: int) -> str:
    def _replace(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        return f"[{transpose_chord(inner, semitones)}]"

    return CHORD_TOKEN_RE.sub(_replace, raw_text)


def transpose_document(
    doc: SongDocument,
    target_capo: int,
    *,
    source_capo: int | None = None,
) -> SongDocument:
    """Return a new `SongDocument` transposed to `target_capo` without mutating `doc`."""
    if not (0 <= target_capo <= 12):
        raise TranspositionError(f"target_capo must be between 0 and 12, got {target_capo}.")

    if doc.capo.status == CapoStatus.KNOWN and doc.capo.value is not None:
        effective_source = doc.capo.value if source_capo is None else source_capo
    elif source_capo is not None:
        if not (0 <= source_capo <= 12):
            raise TranspositionError(f"source_capo must be between 0 and 12, got {source_capo}.")
        effective_source = source_capo
    else:
        raise TranspositionError(
            f"Cannot transpose when source Capo is {doc.capo.status.value}; "
            "provide an explicit source_capo."
        )

    semitone_shift = effective_source - target_capo

    new_sections: list[Section] = []
    for sec in doc.sections:
        new_lines: list[SongLine] = []
        for line in sec.lines:
            if line.line_type == LineType.CHORDS_ONLY and line.raw_text is not None:
                raw_chords = [m.strip() for m in CHORD_TOKEN_RE.findall(line.raw_text) if m.strip()]
                model_chords = [c.name for c in line.chords]
                if raw_chords != model_chords:
                    raise TranspositionError(
                        "Inconsistent chords_only line: raw_text chords "
                        f"{raw_chords} do not match SongLine.chords {model_chords}."
                    )
            new_chords = [
                ChordAnchor(
                    name=transpose_chord(c.name, semitone_shift),
                    char_index=c.char_index,
                    chord_index=c.chord_index,
                )
                for c in line.chords
            ]
            new_raw_text = (
                _transpose_raw_text(line.raw_text, semitone_shift)
                if line.line_type == LineType.CHORDS_ONLY and line.raw_text is not None
                else line.raw_text
            )
            new_lines.append(
                SongLine(
                    line_type=line.line_type,
                    lyrics=line.lyrics,
                    chords=new_chords,
                    raw_text=new_raw_text,
                )
            )
        new_sections.append(
            Section(id=sec.id, name=sec.name, order=sec.order, lines=new_lines)
        )

    new_extra = dict(doc.diagnostics.extra)
    new_extra.update(
        {
            "transposed_from_capo": effective_source,
            "transposed_to_capo": target_capo,
            "semitone_shift": semitone_shift,
        }
    )

    return SongDocument(
        schema_version=doc.schema_version,
        title=doc.title,
        artist=doc.artist,
        source_url=doc.source_url,
        capo=CapoInfo(
            status=CapoStatus.KNOWN,
            value=target_capo,
            raw_text=f"Capo {target_capo}",
        ),
        sections=new_sections,
        diagnostics=SourceDiagnostics(
            source_type=doc.diagnostics.source_type,
            fetched_at=doc.diagnostics.fetched_at,
            parser_version=doc.diagnostics.parser_version,
            warnings=list(doc.diagnostics.warnings),
            errors=list(doc.diagnostics.errors),
            extra=new_extra,
        ),
    )
