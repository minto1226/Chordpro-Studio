"""Tests for Web UI PDF preview/export API (/api/pdf)."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from chordpro_studio.chordpro import StandardChordProConverter
from chordpro_studio.models import SongDocument
from chordpro_studio.pdf_renderer import ChromiumNotFoundError
from chordpro_studio.web_api import create_app

SAMPLE_CHO = """{title: テスト/曲:A}
{artist: テスト歌手}
{capo: 0}
{meta: cstudio_schema_version 1.0.0}
{meta: cstudio_capo_status known}
{meta: cstudio_capo_raw capo=0}
{meta: cstudio_capo_value 0}
{meta: cstudio_section_id main}
{comment: Main}
[E]\u3000[B]\u3000[F#]\u3000[B]
月[G#m]曜日から前を[E/G#]向けない
"""


def _has_chrome() -> bool:
    return any(shutil.which(c) for c in ("google-chrome", "chromium", "chromium-browser"))


def test_pdf_api_security_and_validation(tmp_path: Path) -> None:
    client = TestClient(create_app(base_dir=tmp_path))
    hdr = {"X-Requested-With": "chordpro-editor"}

    # Missing Origin & X-Requested-With -> 403
    assert client.post("/api/pdf", json={"content": SAMPLE_CHO}).status_code == 403

    # Disallowed Host -> 403
    assert (
        client.post(
            "/api/pdf",
            json={"content": SAMPLE_CHO},
            headers={"Host": "evil.example.com", **hdr},
        ).status_code
        == 403
    )

    # Empty CHO -> 422
    assert client.post("/api/pdf", json={"content": "  "}, headers=hdr).status_code == 422

    # Unknown source capo with use_target_capo=True -> 422
    unknown_cho = "{title: T}\n{artist: A}\n[C]あ\n"
    assert (
        client.post(
            "/api/pdf",
            json={"content": unknown_cho, "use_target_capo": True, "target_capo": 4},
            headers=hdr,
        ).status_code
        == 422
    )

    # Chromium missing -> 503
    with patch(
        "chordpro_studio.web_api.ChromiumPdfRenderer.render",
        side_effect=ChromiumNotFoundError("not found"),
    ):
        resp = client.post("/api/pdf", json={"content": SAMPLE_CHO}, headers=hdr)
        assert resp.status_code == 503


@pytest.mark.skipif(not _has_chrome(), reason="Chromium/Chrome not installed")
def test_pdf_api_original_unsaved_and_capo4_export(tmp_path: Path) -> None:
    cho_file = tmp_path / "song.cho"
    cho_file.write_text(SAMPLE_CHO, encoding="utf-8")

    client = TestClient(create_app(base_dir=tmp_path))
    hdr = {"X-Requested-With": "chordpro-editor"}

    # Unsaved edit + original Capo
    edited_cho = SAMPLE_CHO.replace("向けない", "向ける")
    resp0 = client.post(
        "/api/pdf",
        json={"content": edited_cho, "use_target_capo": False},
        headers=hdr,
    )
    assert resp0.status_code == 200
    assert resp0.headers["content-type"] == "application/pdf"
    assert resp0.content[:5] == b"%PDF-"
    assert "capo0.pdf" in resp0.headers["x-pdf-filename"]
    # Original file on disk untouched
    assert cho_file.read_text(encoding="utf-8") == SAMPLE_CHO

    # Target Capo 4
    resp4 = client.post(
        "/api/pdf",
        json={"content": edited_cho, "use_target_capo": True, "target_capo": 4},
        headers=hdr,
    )
    assert resp4.status_code == 200
    assert resp4.content[:5] == b"%PDF-"
    assert "capo4.pdf" in resp4.headers["x-pdf-filename"]


@pytest.mark.skipif(not _has_chrome(), reason="Chromium/Chrome not installed")
def test_pdf_api_real_song_206360(tmp_path: Path) -> None:
    real_json = Path(__file__).resolve().parent.parent / "outputs" / "song_206360.json"
    if not real_json.exists():
        pytest.skip("Local outputs/song_206360.json not present")

    doc = SongDocument.model_validate_json(real_json.read_text(encoding="utf-8"))
    cho = StandardChordProConverter().to_chordpro(doc)
    client = TestClient(create_app(base_dir=tmp_path))
    hdr = {"X-Requested-With": "chordpro-editor"}

    resp = client.post(
        "/api/pdf",
        json={"content": cho, "use_target_capo": True, "target_capo": 4},
        headers=hdr,
    )
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"
