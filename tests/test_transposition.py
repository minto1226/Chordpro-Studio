"""Unit and integration tests for Capo transposition engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from chordpro_studio.chordpro import StandardChordProConverter
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
from chordpro_studio.transposition import (
    TranspositionError,
    transpose_chord,
    transpose_document,
)

LOCAL_206360_PATH = Path(__file__).resolve().parent.parent / "outputs" / "song_206360.json"


@pytest.mark.parametrize(
    ("chord", "semitones", "expected"),
    [
        ("E", -4, "C"),
        ("B", -4, "G"),
        ("F#", -4, "D"),
        ("C", 4, "E"),
        ("G", 4, "B"),
        ("D", 4, "F#"),
        ("G#m", -4, "Em"),
        ("D#m7", -4, "Bm7"),
        ("F#sus4", -4, "Dsus4"),
        ("E/G#", -4, "C/E"),
        ("N.C.", -4, "N.C."),
        ("Bb", -2, "Ab"),
        ("C#", 1, "D"),
        ("Db", 2, "Eb"),
        ("Am7", -3, "F#m7"),
    ],
)
def test_transpose_chord_cases(chord: str, semitones: int, expected: str) -> None:
    assert transpose_chord(chord, semitones) == expected


def test_unrecognized_chord_raises() -> None:
    with pytest.raises(TranspositionError, match="Unrecognized chord symbol"):
        transpose_chord("Hmaj7", -2)


def test_transpose_document_preserves_original_and_roundtrips_cho() -> None:
    original = SongDocument(
        title="テスト曲",
        artist="テスト歌手",
        capo=CapoInfo(status=CapoStatus.KNOWN, value=0, raw_text="capo=0"),
        sections=[
            Section(
                id="main",
                name="Main",
                order=0,
                lines=[
                    SongLine(
                        line_type=LineType.CHORDS_ONLY,
                        lyrics="",
                        chords=[
                            ChordAnchor(name="E", char_index=0, chord_index=0),
                            ChordAnchor(name="B", char_index=1, chord_index=1),
                            ChordAnchor(name="F#", char_index=2, chord_index=2),
                            ChordAnchor(name="B", char_index=3, chord_index=3),
                        ],
                        raw_text="[E]\u3000[B]\u3000[F#]\u3000[B]",
                    ),
                    SongLine(
                        line_type=LineType.LYRIC_WITH_CHORDS,
                        lyrics="月曜日から前を向けない",
                        chords=[
                            ChordAnchor(name="G#m", char_index=1, chord_index=0),
                            ChordAnchor(name="E/G#", char_index=5, chord_index=1),
                        ],
                    ),
                ],
            )
        ],
        diagnostics=SourceDiagnostics(source_type="ufret_web"),
    )

    capo4 = transpose_document(original, target_capo=4)
    # Original is untouched
    assert original.capo.value == 0
    assert [c.name for c in original.sections[0].lines[0].chords] == ["E", "B", "F#", "B"]
    assert original.sections[0].lines[0].raw_text == "[E]\u3000[B]\u3000[F#]\u3000[B]"

    # Transposed to Capo 4
    assert capo4.capo.value == 4
    assert [c.name for c in capo4.sections[0].lines[0].chords] == ["C", "G", "D", "G"]
    assert capo4.sections[0].lines[0].raw_text == "[C]\u3000[G]\u3000[D]\u3000[G]"
    assert [c.name for c in capo4.sections[0].lines[1].chords] == ["Em", "C/E"]
    assert capo4.sections[0].lines[1].lyrics == "月曜日から前を向けない"

    # Round-trip through .cho
    converter = StandardChordProConverter()
    cho_text = converter.to_chordpro(capo4)
    reimported = converter.from_chordpro(cho_text)
    assert reimported.capo.value == 4
    assert reimported.sections[0].lines[0].raw_text == "[C]\u3000[G]\u3000[D]\u3000[G]"

    # Capo 4 -> 0 restores original pitches
    back_to_0 = transpose_document(reimported, target_capo=0)
    assert [c.name for c in back_to_0.sections[0].lines[0].chords] == ["E", "B", "F#", "B"]
    assert [c.name for c in back_to_0.sections[0].lines[1].chords] == ["G#m", "E/G#"]


def test_transpose_unknown_or_failed_capo_requires_explicit_source() -> None:
    doc = SongDocument(
        title="Unknown Capo",
        artist="Artist",
        capo=CapoInfo(status=CapoStatus.UNKNOWN, value=None),
        sections=[
            Section(
                id="main",
                name="Main",
                order=0,
                lines=[
                    SongLine(
                        line_type=LineType.LYRIC_WITH_CHORDS,
                        lyrics="歌詞",
                        chords=[ChordAnchor(name="C", char_index=0, chord_index=0)],
                    )
                ],
            )
        ],
        diagnostics=SourceDiagnostics(source_type="ufret_web"),
    )

    with pytest.raises(TranspositionError, match="source Capo is unknown"):
        transpose_document(doc, target_capo=2)

    transposed = transpose_document(doc, target_capo=5, source_capo=2)
    assert transposed.capo.value == 5
    assert transposed.sections[0].lines[0].chords[0].name == "A"


@pytest.mark.skipif(not LOCAL_206360_PATH.exists(), reason="Local 206360 JSON not present")
def test_real_song_206360_capo_0_to_4() -> None:
    doc = SongDocument.model_validate_json(LOCAL_206360_PATH.read_text(encoding="utf-8"))
    assert doc.capo.value == 0
    capo4 = transpose_document(doc, target_capo=4)
    assert [c.name for c in capo4.sections[0].lines[0].chords] == ["C", "G", "D", "G"]
    assert len(capo4.sections[0].lines) == 54
    assert sum(len(line.chords) for line in capo4.sections[0].lines) == 152
