"""Unit and integration tests for ChromiumPdfRenderer and CLI."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from chordpro_studio.html_renderer import render_song_html
from chordpro_studio.layout import ChordOnlyRow, build_layout
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
from chordpro_studio.pdf_renderer import (
    ChromiumExecutionError,
    ChromiumNotFoundError,
    ChromiumPdfRenderer,
    PdfOutputExistsError,
    PdfValidationError,
    main,
)


def _has_chrome() -> bool:
    return any(shutil.which(c) for c in ("google-chrome", "chromium", "chromium-browser"))


def _make_sample_doc() -> SongDocument:
    return SongDocument(
        title="テスト楽曲",
        artist="テスト歌手",
        capo=CapoInfo(status=CapoStatus.KNOWN, value=0),
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
                            ChordAnchor(name="G", char_index=0, chord_index=0),
                            ChordAnchor(name="D", char_index=3, chord_index=1),
                        ],
                        raw_text="[G]   [D]",
                    ),
                    SongLine(
                        line_type=LineType.LYRIC_WITH_CHORDS,
                        lyrics="あした晴れたらいいな",
                        chords=[ChordAnchor(name="C", char_index=0, chord_index=0)],
                    ),
                ],
            )
        ],
        diagnostics=SourceDiagnostics(source_type="ufret_web"),
    )


def test_chords_only_spacing_preserved_in_layout_and_html() -> None:
    doc = _make_sample_doc()
    layout = build_layout(doc)
    row = layout.sections[0].rows[0]
    assert isinstance(row, ChordOnlyRow)
    assert row.groups[0][0].gap_before == 0
    assert row.groups[0][1].gap_before == 3
    html_out = render_song_html(doc)
    assert "margin-left: 1.35em;" in html_out


def test_css_loads_from_different_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    html_out = render_song_html(_make_sample_doc())
    assert "@page" in html_out
    assert "size: A4 portrait" in html_out


def test_pdf_overwrite_protection(tmp_path: Path) -> None:
    out_pdf = tmp_path / "out.pdf"
    out_pdf.write_bytes(b"%PDF-1.4 existing")
    renderer = ChromiumPdfRenderer(chromium_path="/bin/echo", force=False)
    with pytest.raises(PdfOutputExistsError, match="already exists"):
        renderer.render(_make_sample_doc(), out_pdf)
    assert out_pdf.read_bytes() == b"%PDF-1.4 existing"


def test_chromium_missing_raises() -> None:
    renderer = ChromiumPdfRenderer(chromium_path="/nonexistent/chrome_bin")
    with pytest.raises(ChromiumNotFoundError):
        renderer.render(_make_sample_doc(), Path("/tmp/unused.pdf"))


def test_chromium_timeout_and_nonzero_leave_no_output(tmp_path: Path) -> None:
    out_pdf = tmp_path / "fail.pdf"
    renderer = ChromiumPdfRenderer(chromium_path="/bin/true")

    with (
        patch("subprocess.run", side_effect=subprocess.TimeoutExpired("chrome", 30)),
        pytest.raises(ChromiumExecutionError, match="timed out"),
    ):
        renderer.render(_make_sample_doc(), out_pdf)
    assert not out_pdf.exists()

    fail_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="crash")
    with (
        patch("subprocess.run", return_value=fail_proc),
        pytest.raises(ChromiumExecutionError, match="exited with code 1"),
    ):
        renderer.render(_make_sample_doc(), out_pdf)
    assert not out_pdf.exists()


def test_invalid_pdf_header_raises(tmp_path: Path) -> None:
    out_pdf = tmp_path / "bad.pdf"

    def _fake_run(cmd, **_kwargs):
        for arg in cmd:
            if arg.startswith("--print-to-pdf="):
                Path(arg.split("=", 1)[1]).write_bytes(b"NOT_A_PDF")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with (
        patch("subprocess.run", side_effect=_fake_run),
        pytest.raises(PdfValidationError, match="Invalid PDF header"),
    ):
        ChromiumPdfRenderer(chromium_path="/bin/true").render(_make_sample_doc(), out_pdf)
    assert not out_pdf.exists()


def test_cli_missing_input_returns_nonzero(tmp_path: Path) -> None:
    assert main([str(tmp_path / "missing.cho"), "-o", str(tmp_path / "out.pdf")]) == 1


@pytest.mark.skipif(not _has_chrome(), reason="Chromium/Chrome not installed")
def test_real_chromium_render_a4_and_cli(tmp_path: Path) -> None:
    doc = _make_sample_doc()
    out_pdf = tmp_path / "real.pdf"
    result = ChromiumPdfRenderer().render(doc, out_pdf)
    assert result.exists()
    assert result.read_bytes()[:5] == b"%PDF-"

    cho_path = tmp_path / "sample.cho"
    cho_path.write_text("{title: CLI曲}\n{artist: 歌手}\n{capo: 2}\n[C]テスト\n", encoding="utf-8")
    cli_pdf = tmp_path / "cli.pdf"
    assert main([str(cho_path), "-o", str(cli_pdf)]) == 0
    assert cli_pdf.read_bytes()[:5] == b"%PDF-"


def test_trailing_chord_css_has_min_height() -> None:
    doc = SongDocument(
        title="Trailing",
        artist="Artist",
        capo=CapoInfo(status=CapoStatus.KNOWN, value=0),
        sections=[
            Section(
                id="main",
                name="Main",
                order=0,
                lines=[
                    SongLine(
                        line_type=LineType.LYRIC_WITH_CHORDS,
                        lyrics="思います",
                        chords=[
                            ChordAnchor(name="F#", char_index=0, chord_index=0),
                            ChordAnchor(name="B", char_index=4, chord_index=1),
                        ],
                    )
                ],
            )
        ],
        diagnostics=SourceDiagnostics(source_type="ufret_web"),
    )
    html_out = render_song_html(doc)
    assert "min-height: 1.35em;" in html_out
    assert '<span class="chord">B</span><span class="lyric"></span>' in html_out


@pytest.mark.skipif(not _has_chrome(), reason="Chromium/Chrome not installed")
def test_real_song_206360_capo0_and_capo4_pdfs(tmp_path: Path) -> None:
    real_json = Path(__file__).resolve().parent.parent / "outputs" / "song_206360.json"
    if not real_json.exists():
        pytest.skip("Local outputs/song_206360.json not present")

    from chordpro_studio.transposition import transpose_document

    doc0 = SongDocument.model_validate_json(real_json.read_text(encoding="utf-8"))
    doc4 = transpose_document(doc0, target_capo=4)
    assert [c.name for c in doc4.sections[0].lines[0].chords] == ["C", "G", "D", "G"]
    assert sum(len(line.chords) for line in doc4.sections[0].lines) == 152

    pdf0 = tmp_path / "capo0.pdf"
    pdf4 = tmp_path / "capo4.pdf"
    renderer = ChromiumPdfRenderer()
    renderer.render(doc0, pdf0)
    renderer.render(doc4, pdf4)
    assert pdf0.read_bytes()[:5] == b"%PDF-"
    assert pdf4.read_bytes()[:5] == b"%PDF-"
