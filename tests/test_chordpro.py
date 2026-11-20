"""Unit and round-trip tests for StandardChordProConverter."""

from __future__ import annotations

import json
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

SAMPLE_JSON_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "sample_song.json"
LOCAL_206360_PATH = Path(__file__).resolve().parent.parent / "outputs" / "song_206360.json"


def _assert_documents_semantically_equal(a: SongDocument, b: SongDocument) -> None:
    assert a.title == b.title
    assert a.artist == b.artist
    assert a.source_url == b.source_url
    assert a.capo == b.capo
    assert len(a.sections) == len(b.sections)
    for sec_a, sec_b in zip(a.sections, b.sections, strict=True):
        assert sec_a.id == sec_b.id
        assert sec_a.name == sec_b.name
        assert sec_a.order == sec_b.order
        assert len(sec_a.lines) == len(sec_b.lines)
        for line_a, line_b in zip(sec_a.lines, sec_b.lines, strict=True):
            assert line_a.line_type == line_b.line_type
            assert line_a.lyrics == line_b.lyrics
            assert line_a.chords == line_b.chords
            if line_a.raw_text is not None:
                assert line_b.raw_text == line_a.raw_text


def test_unit_special_chords_and_capo_states() -> None:
    converter = StandardChordProConverter()
    doc = SongDocument(
        title="特殊和弦テスト",
        artist="テスト歌手",
        capo=CapoInfo(status=CapoStatus.UNKNOWN, value=None),
        sections=[
            Section(
                id="sec-0",
                name="Intro",
                order=0,
                lines=[
                    SongLine(
                        line_type=LineType.CHORDS_ONLY,
                        lyrics="",
                        chords=[
                            ChordAnchor(name="F#m7", char_index=0, chord_index=0),
                            ChordAnchor(name="Bb", char_index=1, chord_index=1),
                            ChordAnchor(name="C/G", char_index=2, chord_index=2),
                            ChordAnchor(name="F#sus4", char_index=2, chord_index=3),
                            ChordAnchor(name="N.C.", char_index=3, chord_index=4),
                        ],
                        raw_text="[F#m7]\u3000[Bb]\u3000[C/G][F#sus4]\u3000[N.C.]",
                    )
                ],
            )
        ],
        diagnostics=SourceDiagnostics(source_type="ufret_web"),
    )

    cho = converter.to_chordpro(doc)
    assert "{capo:" not in cho
    assert "{meta: ufret_capo_status unknown}" in cho

    reimported = converter.from_chordpro(cho)
    _assert_documents_semantically_equal(doc, reimported)
    assert reimported.diagnostics.source_type == "chordpro_import"


def test_unmodified_round_trip_sample_song() -> None:
    converter = StandardChordProConverter()
    original = SongDocument.model_validate_json(SAMPLE_JSON_PATH.read_text(encoding="utf-8"))
    cho = converter.to_chordpro(original)
    reimported = converter.from_chordpro(cho)
    _assert_documents_semantically_equal(original, reimported)


@pytest.mark.skipif(not LOCAL_206360_PATH.exists(), reason="Local ignored 206360 JSON not present")
def test_unmodified_round_trip_local_real_song() -> None:
    converter = StandardChordProConverter()
    original = SongDocument.model_validate_json(LOCAL_206360_PATH.read_text(encoding="utf-8"))
    cho = converter.to_chordpro(original)
    reimported = converter.from_chordpro(cho)
    _assert_documents_semantically_equal(original, reimported)


def test_user_edited_round_trip_overrides_old_metadata() -> None:
    converter = StandardChordProConverter()
    original = SongDocument.model_validate_json(SAMPLE_JSON_PATH.read_text(encoding="utf-8"))
    cho = converter.to_chordpro(original)

    # User edits: change Capo 2 -> 4, C/G -> G, insert [Am] in lyric, edit chords_only, add section
    edited = cho.replace("{capo: 2}", "{capo: 4}")
    edited = edited.replace("[C/G]", "[G]")
    edited = edited.replace("いいな", "[Am]いいな")
    edited = edited.replace("[F#m7] [Bb] [G]", "[Em]\u3000[C]\u3000[G]")
    edited += "\n{comment: Chorus}\n[G]新しい歌詞\n"

    reimported = converter.from_chordpro(edited)

    assert reimported.capo.status == CapoStatus.KNOWN
    assert reimported.capo.value == 4
    assert reimported.capo.raw_text == "Capo 4"

    assert len(reimported.sections) == 3
    assert reimported.sections[2].name == "Chorus"
    assert reimported.sections[0].lines[0].raw_text == "[Em]\u3000[C]\u3000[G]"
    assert [c.name for c in reimported.sections[0].lines[0].chords] == ["Em", "C", "G"]
    assert [c.name for c in reimported.sections[1].lines[0].chords] == ["F#m7", "G", "Am"]
    assert reimported.sections[2].lines[0].lyrics == "新しい歌詞"
    assert json.loads(reimported.model_dump_json())["capo"]["value"] == 4
