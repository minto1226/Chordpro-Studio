"""Offline tests for LocalSongEditor, FastAPI backend, and raw_text consistency."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
from chordpro_studio.transposition import TranspositionError, transpose_document
from chordpro_studio.web_api import create_app

SAMPLE_CHO = """{title: テスト曲}
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


def test_raw_text_inconsistency_raises() -> None:
    doc = SongDocument(
        title="Inconsistent",
        artist="Artist",
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
                        chords=[ChordAnchor(name="C", char_index=0, chord_index=0)],
                        raw_text="[G]",
                    )
                ],
            )
        ],
        diagnostics=SourceDiagnostics(source_type="web_import"),
    )
    with pytest.raises(TranspositionError, match="Inconsistent chords_only line"):
        transpose_document(doc, target_capo=2)


def test_same_capo_preserves_spelling() -> None:
    doc = SongDocument(
        title="Same",
        artist="Artist",
        capo=CapoInfo(status=CapoStatus.KNOWN, value=2),
        sections=[
            Section(
                id="main",
                name="Main",
                order=0,
                lines=[
                    SongLine(
                        line_type=LineType.LYRIC_WITH_CHORDS,
                        lyrics="あ",
                        chords=[ChordAnchor(name="Db", char_index=0, chord_index=0)],
                    )
                ],
            )
        ],
        diagnostics=SourceDiagnostics(source_type="web_import"),
    )
    same = transpose_document(doc, target_capo=2)
    assert same.sections[0].lines[0].chords[0].name == "Db"


def test_api_load_validate_transpose_save_and_conflicts(tmp_path: Path) -> None:
    cho_path = tmp_path / "song.cho"
    cho_path.write_text(SAMPLE_CHO, encoding="utf-8")

    client = TestClient(create_app(base_dir=tmp_path))
    local_hdr = {"X-Requested-With": "chordpro-editor"}

    # Homepage UI
    resp_home = client.get("/")
    assert resp_home.status_code == 200
    assert "ChordPro Editor" in resp_home.text
    # P1-01 & P1-02 UI state guards
    assert "confirmDiscardIfDirty" in resp_home.text
    assert "invalidatePreview" in resp_home.text
    assert "previewReqSeq" in resp_home.text
    assert 'id="saveTransposedBtn" class="primary" type="button" disabled' in resp_home.text

    # Disallowed Host -> 403
    assert client.get("/api/files", headers={"Host": "evil.example.com"}).status_code == 403

    # List & load
    resp_list = client.get("/api/files")
    assert resp_list.status_code == 200
    assert resp_list.json() == {"files": ["song.cho"]}

    resp_get = client.get("/api/files/song.cho")
    assert resp_get.status_code == 200
    data = resp_get.json()
    version_token = data["version_token"]
    assert data["summary"]["title"] == "テスト曲"
    assert data["summary"]["capo_value"] == 0

    # Transpose 0 -> 4 preview (non-destructive)
    resp_tr = client.post(
        "/api/transpose",
        json={"content": SAMPLE_CHO, "target_capo": 4},
        headers=local_hdr,
    )
    assert resp_tr.status_code == 200
    tr_data = resp_tr.json()
    assert tr_data["summary"]["capo_value"] == 4
    assert "[C]\u3000[G]\u3000[D]\u3000[G]" in tr_data["cho_text"]
    assert "月[Em]曜日から前を[C/E]向けない" in tr_data["cho_text"]
    # Original file on disk unchanged
    assert cho_path.read_text(encoding="utf-8") == SAMPLE_CHO

    # Save As new file
    resp_save_as = client.post(
        "/api/save",
        json={"file_id": "song_capo4.cho", "content": tr_data["cho_text"], "save_as": True},
        headers=local_hdr,
    )
    assert resp_save_as.status_code == 200
    assert (tmp_path / "song_capo4.cho").exists()

    # Save As existing without force -> 409
    resp_dup = client.post(
        "/api/save",
        json={"file_id": "song_capo4.cho", "content": tr_data["cho_text"], "save_as": True},
        headers=local_hdr,
    )
    assert resp_dup.status_code == 409

    # Save original without expected_version -> 422
    assert (
        client.post(
            "/api/save",
            json={"file_id": "song.cho", "content": SAMPLE_CHO},
            headers=local_hdr,
        ).status_code
        == 422
    )

    # Save original with valid token
    edited_cho = SAMPLE_CHO.replace("テスト曲", "テスト曲改")
    resp_save = client.post(
        "/api/save",
        json={"file_id": "song.cho", "content": edited_cho, "expected_version": version_token},
        headers=local_hdr,
    )
    assert resp_save.status_code == 200

    # Stale token -> 409 conflict
    resp_conflict = client.post(
        "/api/save",
        json={"file_id": "song.cho", "content": SAMPLE_CHO, "expected_version": version_token},
        headers=local_hdr,
    )
    assert resp_conflict.status_code == 409

    # Invalid content -> 422, does not overwrite
    resp_invalid = client.post(
        "/api/save",
        json={
            "file_id": "song.cho",
            "content": "   ",
            "expected_version": resp_save.json()["version_token"],
        },
        headers=local_hdr,
    )
    assert resp_invalid.status_code == 422
    assert "テスト曲改" in cho_path.read_text(encoding="utf-8")

    # Path traversal -> 403 (or 404 when router normalizes %2F)
    assert client.get("/api/files/..secret.cho").status_code == 403
    assert (
        client.post(
            "/api/save",
            json={"file_id": "../evil.cho", "content": SAMPLE_CHO, "save_as": True},
            headers=local_hdr,
        ).status_code
        == 403
    )

    # Missing Origin AND missing X-Requested-With -> 403
    assert (
        client.post(
            "/api/save",
            json={"file_id": "song.cho", "content": edited_cho, "expected_version": version_token},
        ).status_code
        == 403
    )

    # Disallowed Origin -> 403
    assert (
        client.post(
            "/api/save",
            json={"file_id": "song.cho", "content": edited_cho},
            headers={"Origin": "https://evil.example.com"},
        ).status_code
        == 403
    )


def test_real_song_206360_api_transpose_roundtrip(tmp_path: Path) -> None:
    real_json = Path(__file__).resolve().parent.parent / "outputs" / "song_206360.json"
    if not real_json.exists():
        pytest.skip("Local outputs/song_206360.json not present")

    doc = SongDocument.model_validate_json(real_json.read_text(encoding="utf-8"))
    cho = StandardChordProConverter().to_chordpro(doc)
    client = TestClient(create_app(base_dir=tmp_path))

    # Homepage UI
    resp_home = client.get("/")
    assert resp_home.status_code == 200
    assert "ChordPro Editor" in resp_home.text
    # P1-01 & P1-02 UI state guards
    assert "confirmDiscardIfDirty" in resp_home.text
    assert "invalidatePreview" in resp_home.text
    assert "previewReqSeq" in resp_home.text
    assert 'id="saveTransposedBtn" class="primary" type="button" disabled' in resp_home.text

    # Disallowed Host -> 403
    assert client.get("/api/files", headers={"Host": "evil.example.com"}).status_code == 403

    resp = client.post(
        "/api/transpose",
        json={"content": cho, "target_capo": 4},
        headers={"X-Requested-With": "chordpro-editor"},
    )
    assert resp.status_code == 200
    assert resp.json()["summary"]["capo_value"] == 4
    assert resp.json()["summary"]["line_count"] == 54
    assert resp.json()["summary"]["chord_count"] == 152
