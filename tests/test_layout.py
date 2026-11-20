"""Unit tests for SongLayout intermediate model and HTML renderer."""

from __future__ import annotations

import pytest

from chordpro_studio.html_renderer import render_song_html
from chordpro_studio.layout import (
    BlankRow,
    ChordOnlyRow,
    LayoutError,
    LyricPair,
    build_layout,
)
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


def _make_doc(lines: list[SongLine], *, capo_val: int | None = 4) -> SongDocument:
    capo = (
        CapoInfo(status=CapoStatus.KNOWN, value=capo_val)
        if capo_val is not None
        else CapoInfo(status=CapoStatus.UNKNOWN, value=None)
    )
    return SongDocument(
        title="テスト<曲>",
        artist="歌手&A",
        capo=capo,
        sections=[Section(id="s1", name="Verse 1", order=0, lines=lines)],
        diagnostics=SourceDiagnostics(source_type="ufret_web", parser_version="0.1.0"),
    )


def test_layout_pairing_odd_lines_blank_and_chords_only() -> None:
    doc = _make_doc(
        [
            SongLine(
                line_type=LineType.CHORDS_ONLY,
                lyrics="",
                chords=[
                    ChordAnchor(name="F#m7", char_index=0, chord_index=0),
                    ChordAnchor(name="C/G", char_index=1, chord_index=1),
                ],
                raw_text="[F#m7] | [C/G]",
            ),
            SongLine(
                line_type=LineType.LYRIC_WITH_CHORDS,
                lyrics="あした晴れたら",
                chords=[ChordAnchor(name="C", char_index=0, chord_index=0)],
            ),
            SongLine(
                line_type=LineType.LYRIC_ONLY,
                lyrics="いいなと思う",
            ),
            SongLine(line_type=LineType.BLANK),
            SongLine(
                line_type=LineType.LYRIC_WITH_CHORDS,
                lyrics="単独の最後行",
                chords=[ChordAnchor(name="G", char_index=3, chord_index=0)],
            ),
        ]
    )

    layout = build_layout(doc)
    assert layout.header.capo_label == "Capo：4"
    rows = layout.sections[0].rows
    assert isinstance(rows[0], ChordOnlyRow)
    assert [[item.chord for item in grp] for grp in rows[0].groups] == [["F#m7"], ["C/G"]]
    assert isinstance(rows[1], LyricPair)
    assert rows[1].right is not None
    assert rows[1].left.segments[0].text == "あした晴れたら"
    assert rows[1].right.segments[0].text == "いいなと思う"
    assert isinstance(rows[2], BlankRow)
    assert isinstance(rows[3], LyricPair)
    assert rows[3].right is None
    assert rows[3].left.segments[0].chord is None
    assert rows[3].left.segments[0].text == "単独の"
    assert rows[3].left.segments[1].chord == "G"
    assert rows[3].left.segments[1].text == "最後行"


def test_same_char_index_multi_chords_and_fullwidth_space() -> None:
    doc = _make_doc(
        [
            SongLine(
                line_type=LineType.LYRIC_WITH_CHORDS,
                lyrics="全形　空白",
                chords=[
                    ChordAnchor(name="C", char_index=0, chord_index=0),
                    ChordAnchor(name="G", char_index=0, chord_index=1),
                ],
            )
        ],
        capo_val=0,
    )
    layout = build_layout(doc)
    assert layout.header.capo_label == "Capo：0"
    pair = layout.sections[0].rows[0]
    assert isinstance(pair, LyricPair)
    assert [(s.chord, s.text) for s in pair.left.segments] == [("C", ""), ("G", "全形　空白")]


def test_out_of_bounds_char_index_raises() -> None:
    doc = _make_doc(
        [
            SongLine(
                line_type=LineType.LYRIC_WITH_CHORDS,
                lyrics="短い",
                chords=[ChordAnchor(name="C", char_index=10, chord_index=0)],
            )
        ]
    )
    with pytest.raises(LayoutError, match="out of bounds"):
        build_layout(doc)


def test_html_escaping_and_metadata_filtering() -> None:
    doc = _make_doc(
        [
            SongLine(
                line_type=LineType.LYRIC_WITH_CHORDS,
                lyrics="<script>alert(1)</script>",
                chords=[ChordAnchor(name="C&G", char_index=0, chord_index=0)],
            )
        ],
        capo_val=None,
    )
    html_out = render_song_html(doc)
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_out
    assert "テスト&lt;曲&gt;" in html_out
    assert "歌手&amp;A" in html_out
    assert "C&amp;G" in html_out
    assert "parser_version" not in html_out
    assert "Capo：" not in html_out
