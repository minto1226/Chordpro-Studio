"""Bidirectional ChordPro (.cho) converter for SongDocument."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

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

PARSER_VERSION = "1.0.0"
DIRECTIVE_RE = re.compile(r"^\{([a-zA-Z0-9_]+)(?::\s*(.*?))?\}\s*$")
CHORD_TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")


def parse_chordpro_line(raw_line: str) -> SongLine:
    """Parse a single ChordPro line into a `SongLine`."""
    cleaned = raw_line.rstrip("\r\n")
    if not cleaned.strip():
        return SongLine(line_type=LineType.BLANK)

    chords: list[ChordAnchor] = []
    plain_parts: list[str] = []
    cursor = 0
    plain_len = 0

    for match in CHORD_TOKEN_RE.finditer(cleaned):
        text_before = cleaned[cursor : match.start()]
        plain_parts.append(text_before)
        plain_len += len(text_before)
        chord_name = match.group(1).strip()
        if chord_name:
            chords.append(
                ChordAnchor(
                    name=chord_name,
                    char_index=plain_len,
                    chord_index=len(chords),
                )
            )
        cursor = match.end()

    plain_parts.append(cleaned[cursor:])
    lyrics = "".join(plain_parts)

    if not chords:
        return SongLine(line_type=LineType.LYRIC_ONLY, lyrics=lyrics)
    if not lyrics.strip():
        return SongLine(line_type=LineType.CHORDS_ONLY, lyrics="", chords=chords, raw_text=cleaned)
    return SongLine(line_type=LineType.LYRIC_WITH_CHORDS, lyrics=lyrics, chords=chords)


class ChordProError(ValueError):
    """Raised when ChordPro parsing or serialization fails."""


def _serialize_lyric_with_chords(line: SongLine) -> str:
    sorted_chords = sorted(line.chords, key=lambda c: (c.char_index, c.chord_index))
    lyric_len = len(line.lyrics)
    parts: list[str] = []
    cursor = 0
    for chord in sorted_chords:
        if chord.char_index < 0 or chord.char_index > lyric_len:
            raise ChordProError(
                f"ChordAnchor {chord.name!r} has char_index={chord.char_index}, "
                f"which is out of bounds for lyrics of length {lyric_len}."
            )
        idx = chord.char_index
        if idx > cursor:
            parts.append(line.lyrics[cursor:idx])
            cursor = idx
        parts.append(f"[{chord.name}]")
    if cursor < lyric_len:
        parts.append(line.lyrics[cursor:])
    return "".join(parts)


def _serialize_chords_only(line: SongLine) -> str:
    if line.raw_text is not None:
        return line.raw_text
    sorted_chords = sorted(line.chords, key=lambda c: (c.char_index, c.chord_index))
    parts: list[str] = []
    plain_pos = 0
    for i, chord in enumerate(sorted_chords):
        gap = max(0, chord.char_index - plain_pos)
        if i > 0 and gap == 0:
            pass
        elif gap > 0:
            parts.append(" " * gap)
            plain_pos += gap
        parts.append(f"[{chord.name}]")
    return "".join(parts)


class StandardChordProConverter:
    """Converts between `SongDocument` and editable ChordPro (`.cho`) text."""

    def to_chordpro(self, song: SongDocument) -> str:
        """Serialize a `SongDocument` into ChordPro (`.cho`) format."""
        out: list[str] = [
            f"{{title: {song.title}}}",
            f"{{artist: {song.artist}}}",
        ]

        if song.capo.status == CapoStatus.KNOWN and song.capo.value is not None:
            out.append(f"{{capo: {song.capo.value}}}")

        out.append(f"{{meta: cstudio_schema_version {song.schema_version}}}")
        if song.source_url:
            out.append(f"{{meta: cstudio_source_url {song.source_url}}}")
        out.append(f"{{meta: cstudio_capo_status {song.capo.status.value}}}")
        if song.capo.raw_text is not None:
            out.append(f"{{meta: cstudio_capo_raw {song.capo.raw_text}}}")
        if song.capo.status == CapoStatus.KNOWN and song.capo.value is not None:
            out.append(f"{{meta: cstudio_capo_value {song.capo.value}}}")

        for section in sorted(song.sections, key=lambda s: s.order):
            out.append(f"{{meta: cstudio_section_id {section.id}}}")
            out.append(f"{{comment: {section.name}}}")
            for line in section.lines:
                if line.line_type == LineType.BLANK:
                    out.append("")
                elif line.line_type == LineType.LYRIC_ONLY:
                    out.append(line.lyrics)
                elif line.line_type == LineType.LYRIC_WITH_CHORDS:
                    out.append(_serialize_lyric_with_chords(line))
                elif line.line_type == LineType.CHORDS_ONLY:
                    out.append(_serialize_chords_only(line))

        return "\n".join(out) + "\n"

    def from_chordpro(self, content: str) -> SongDocument:
        """Parse edited ChordPro (`.cho`) text back into a `SongDocument`."""
        title: str | None = None
        artist: str | None = None
        capo_directive: str | None = None
        meta: dict[str, str] = {}
        warnings: list[str] = []

        sections: list[Section] = []
        current_section: Section | None = None
        pending_section_id: str | None = None
        in_header = True

        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            match = DIRECTIVE_RE.match(stripped)
            if match:
                key = match.group(1).lower()
                val = (match.group(2) or "").strip()

                if key in ("title", "t"):
                    title = val
                    continue
                if key in ("artist", "subtitle", "st"):
                    artist = val
                    continue
                if key == "capo":
                    capo_directive = val
                    continue
                if key == "meta":
                    if " " in val:
                        m_key, m_val = val.split(" ", 1)
                        if m_key == "cstudio_section_id":
                            pending_section_id = m_val.strip()
                        else:
                            meta[m_key] = m_val.strip()
                    continue
                if key in ("comment", "c"):
                    in_header = False
                    sec_id = pending_section_id or f"section-{len(sections)}"
                    pending_section_id = None
                    current_section = Section(
                        id=sec_id,
                        name=val or f"Section {len(sections) + 1}",
                        order=len(sections),
                        lines=[],
                    )
                    sections.append(current_section)
                    continue
                warnings.append(f"Ignored unknown ChordPro directive '{{{key}: ...}}'.")
                continue

            # Ignore blank separator lines in the header before the first section
            if in_header and not stripped:
                continue

            in_header = False
            if current_section is None:
                sec_id = pending_section_id or "main"
                pending_section_id = None
                current_section = Section(id=sec_id, name="Main", order=0, lines=[])
                sections.append(current_section)

            current_section.lines.append(parse_chordpro_line(raw_line))

        if not title:
            warnings.append("Missing {title:} directive; using fallback 'Unknown Title'.")
            title = "Unknown Title"
        if not artist:
            warnings.append("Missing {artist:} directive; using fallback 'Unknown Artist'.")
            artist = "Unknown Artist"

        capo = self._resolve_capo(capo_directive, meta, warnings)

        diagnostics = SourceDiagnostics(
            source_type="chordpro_import",
            fetched_at=datetime.now(UTC),
            parser_version=PARSER_VERSION,
            warnings=warnings,
            extra={k: v for k, v in meta.items() if k != "cstudio_capo_value"},
        )

        return SongDocument(
            schema_version=meta.get("cstudio_schema_version", "1.0.0"),
            title=title,
            artist=artist,
            source_url=meta.get("cstudio_source_url"),
            capo=capo,
            sections=sections,
            diagnostics=diagnostics,
        )

    def _resolve_capo(
        self,
        capo_directive: str | None,
        meta: dict[str, str],
        warnings: list[str],
    ) -> CapoInfo:
        if capo_directive is not None:
            if capo_directive.isdigit() and 0 <= int(capo_directive) <= 12:
                val = int(capo_directive)
                orig_val = meta.get("cstudio_capo_value")
                if orig_val is not None and str(val) == orig_val:
                    raw_text = meta.get("cstudio_capo_raw")
                else:
                    raw_text = f"Capo {val}"
                return CapoInfo(status=CapoStatus.KNOWN, value=val, raw_text=raw_text)
            warnings.append(f"Invalid {{capo: {capo_directive}}} directive.")
            return CapoInfo(status=CapoStatus.FAILED, value=None, raw_text=capo_directive)

        orig_status = meta.get("cstudio_capo_status")
        orig_raw = meta.get("cstudio_capo_raw")
        if orig_status == CapoStatus.FAILED.value:
            return CapoInfo(status=CapoStatus.FAILED, value=None, raw_text=orig_raw)
        return CapoInfo(status=CapoStatus.UNKNOWN, value=None, raw_text=orig_raw)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for converting between SongDocument JSON and ChordPro (.cho)."""
    parser = argparse.ArgumentParser(description="Convert between SongDocument JSON and .cho.")
    parser.add_argument("mode", choices=["json2cho", "cho2json"], help="Conversion direction.")
    parser.add_argument("input_path", type=Path, help="Input file path.")
    parser.add_argument("output_path", type=Path, help="Output file path.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output file.")
    args = parser.parse_args(argv)

    if args.output_path.exists() and not args.force:
        print(
            f"Error: Output file already exists: {args.output_path} (use --force to overwrite)",
            file=sys.stderr,
        )
        return 1

    converter = StandardChordProConverter()
    text = args.input_path.read_text(encoding="utf-8")

    if args.mode == "json2cho":
        doc = SongDocument.model_validate_json(text)
        result = converter.to_chordpro(doc)
    else:
        doc = converter.from_chordpro(text)
        result = doc.model_dump_json(indent=2)

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(result, encoding="utf-8")
    print(f"Converted {args.input_path} -> {args.output_path} ({args.mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
