"""Baseline tests for SongDocument data contracts and edge cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from chordpro_studio import (
    CapoInfo,
    CapoStatus,
    ChordAnchor,
    LineType,
    Section,
    SongDocument,
    SongLine,
    SourceDiagnostics,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def _base_diagnostics() -> SourceDiagnostics:
    return SourceDiagnostics(source_type="manual")


def test_general_lyrics_and_chords() -> None:
    line = SongLine(
        line_type=LineType.LYRIC_WITH_CHORDS,
        lyrics="Hello world",
        chords=[ChordAnchor(name="C", char_index=0, chord_index=0)],
    )
    assert line.lyrics == "Hello world"
    assert line.chords[0].name == "C"
    assert line.chords[0].char_index == 0


def test_multiple_chords_on_one_line() -> None:
    line = SongLine(
        line_type=LineType.LYRIC_WITH_CHORDS,
        lyrics="Take me home country roads",
        chords=[
            ChordAnchor(name="G", char_index=0, chord_index=0),
            ChordAnchor(name="D", char_index=8, chord_index=1),
            ChordAnchor(name="Em", char_index=13, chord_index=2),
            ChordAnchor(name="C", char_index=21, chord_index=3),
        ],
    )
    assert len(line.chords) == 4
    assert [c.chord_index for c in line.chords] == [0, 1, 2, 3]


def test_chords_only_line() -> None:
    line = SongLine(
        line_type=LineType.CHORDS_ONLY,
        lyrics="",
        chords=[
            ChordAnchor(name="Am", char_index=0, chord_index=0),
            ChordAnchor(name="F", char_index=1, chord_index=1),
            ChordAnchor(name="C", char_index=2, chord_index=2),
            ChordAnchor(name="G", char_index=3, chord_index=3),
        ],
    )
    assert line.line_type == LineType.CHORDS_ONLY
    assert line.lyrics == ""
    assert len(line.chords) == 4


def test_special_chords() -> None:
    chords = ["F#m7", "Bb", "C/G"]
    line = SongLine(
        line_type=LineType.CHORDS_ONLY,
        chords=[
            ChordAnchor(name=name, char_index=idx, chord_index=idx)
            for idx, name in enumerate(chords)
        ],
    )
    assert [c.name for c in line.chords] == ["F#m7", "Bb", "C/G"]


def test_japanese_and_unicode_lyrics() -> None:
    lyrics = "沈むように溶けてゆくように♪"
    line = SongLine(
        line_type=LineType.LYRIC_WITH_CHORDS,
        lyrics=lyrics,
        chords=[
            ChordAnchor(name="F#m7", char_index=0, chord_index=0),
            ChordAnchor(name="Bb", char_index=5, chord_index=1),
        ],
    )
    assert lyrics[line.chords[1].char_index] == "溶"


def test_capo_states_distinction() -> None:
    capo_zero = CapoInfo(status=CapoStatus.KNOWN, value=0, raw_text="カポなし")
    capo_nonzero = CapoInfo(status=CapoStatus.KNOWN, value=3, raw_text="Capo 3")
    capo_unknown = CapoInfo(status=CapoStatus.UNKNOWN, value=None, raw_text=None)
    capo_failed = CapoInfo(status=CapoStatus.FAILED, value=None, raw_text="N/A")

    assert capo_zero.value == 0
    assert capo_nonzero.value == 3
    assert capo_unknown.value is None
    assert capo_failed.value is None

    with pytest.raises(ValidationError):
        CapoInfo(status=CapoStatus.KNOWN, value=None)

    with pytest.raises(ValidationError):
        CapoInfo(status=CapoStatus.UNKNOWN, value=0)

    with pytest.raises(ValidationError):
        CapoInfo(status=CapoStatus.FAILED, value=0)


def test_blank_lines_and_multiple_sections() -> None:
    song = SongDocument(
        title="Test Song",
        artist="Test Artist",
        capo=CapoInfo(status=CapoStatus.KNOWN, value=0),
        sections=[
            Section(
                id="intro",
                name="Intro",
                order=0,
                lines=[
                    SongLine(
                        line_type=LineType.CHORDS_ONLY,
                        chords=[ChordAnchor(name="C", char_index=0, chord_index=0)],
                    ),
                    SongLine(line_type=LineType.BLANK),
                ],
            ),
            Section(
                id="verse-1",
                name="Verse 1",
                order=1,
                lines=[
                    SongLine(line_type=LineType.LYRIC_ONLY, lyrics="Just lyrics here"),
                ],
            ),
        ],
        diagnostics=_base_diagnostics(),
    )
    assert len(song.sections) == 2
    assert song.sections[0].lines[1].line_type == LineType.BLANK
    assert song.sections[1].order == 1


def test_fixture_and_json_schema_valid() -> None:
    fixture_path = ROOT_DIR / "fixtures" / "sample_song.json"
    schema_path = ROOT_DIR / "docs" / "song_schema.json"

    song = SongDocument.model_validate_json(fixture_path.read_text(encoding="utf-8"))
    assert song.title == "合成サンプル曲"
    assert song.capo.value == 2

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["title"] == "SongDocument"
    assert "capo" in schema["properties"]
