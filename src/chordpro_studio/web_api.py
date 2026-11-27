"""Local FastAPI backend for the ChordPro editor."""

from __future__ import annotations

import argparse
import re
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote, urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from chordpro_studio.editor import (
    EditorConflictError,
    EditorError,
    EditorNotFoundError,
    EditorPermissionError,
    EditorValidationError,
    LocalSongEditor,
    summarize_document,
)
from chordpro_studio.models import CapoStatus
from chordpro_studio.pdf_renderer import ChromiumPdfRenderer, PdfRenderError
from chordpro_studio.transposition import TranspositionError, transpose_document

ALLOWED_LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver"}
STATIC_INDEX = Path(__file__).resolve().parent / "static" / "index.html"


class ValidateRequest(BaseModel):
    content: str


class TransposeRequest(BaseModel):
    content: str
    target_capo: int = Field(ge=0, le=12)
    source_capo: int | None = Field(default=None, ge=0, le=12)


class SaveRequest(BaseModel):
    file_id: str
    content: str
    expected_version: str | None = None
    save_as: bool = False
    force: bool = False


class PdfRequest(BaseModel):
    content: str
    use_target_capo: bool = False
    target_capo: int | None = Field(default=None, ge=0, le=12)
    source_capo: int | None = Field(default=None, ge=0, le=12)


_UNSAFE_PDF_NAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_PDF_RENDER_LOCK = threading.Lock()


def _verify_local_post(request: Request) -> None:
    origin = request.headers.get("origin")
    x_req = request.headers.get("x-requested-with")
    if origin:
        host = (urlparse(origin).hostname or "").lower()
        if host not in ALLOWED_LOCAL_HOSTS:
            raise HTTPException(status_code=403, detail=f"Disallowed origin: {origin}")
        return
    if x_req != "chordpro-editor":
        raise HTTPException(
            status_code=403,
            detail="Missing local Origin or X-Requested-With header.",
        )


def _raise_http_for_editor_error(exc: EditorError) -> None:
    if isinstance(exc, EditorNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, EditorPermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, EditorConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, EditorValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail=str(exc)) from exc


def create_app(base_dir: Path = Path("outputs")) -> FastAPI:
    """Create a FastAPI app scoped to `base_dir`."""
    app = FastAPI(title="ChordPro Studio Editor API", version="0.1.0")
    editor = LocalSongEditor(base_dir=base_dir)

    @app.middleware("http")
    async def verify_local_host(request: Request, call_next):
        host_header = request.headers.get("host", "")
        hostname = host_header.split(":", 1)[0].lower()
        if hostname not in ALLOWED_LOCAL_HOSTS:
            return JSONResponse(
                status_code=403, content={"detail": f"Disallowed Host: {host_header}"}
            )
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(STATIC_INDEX.read_text(encoding="utf-8"))

    @app.get("/api/files")
    def list_files() -> dict[str, list[str]]:
        return {"files": editor.list_files()}

    @app.get("/api/files/{file_id}")
    def get_file(file_id: str) -> dict[str, object]:
        try:
            loaded = editor.load_file(file_id)
        except EditorError as exc:
            _raise_http_for_editor_error(exc)
        return {
            "file_id": loaded.file_id,
            "content": loaded.content,
            "version_token": loaded.version_token,
            "summary": summarize_document(loaded.document),
        }

    @app.post("/api/validate")
    def validate_cho(payload: ValidateRequest, request: Request) -> dict[str, object]:
        _verify_local_post(request)
        try:
            doc = editor.validate_cho(payload.content)
        except EditorError as exc:
            _raise_http_for_editor_error(exc)
        return {"valid": True, "summary": summarize_document(doc)}

    @app.post("/api/transpose")
    def transpose_cho(payload: TransposeRequest, request: Request) -> dict[str, object]:
        _verify_local_post(request)
        try:
            preview = editor.transpose_preview(
                payload.content,
                target_capo=payload.target_capo,
                source_capo=payload.source_capo,
            )
        except EditorError as exc:
            _raise_http_for_editor_error(exc)
        return {
            "cho_text": preview.cho_text,
            "summary": summarize_document(preview.document),
        }

    @app.post("/api/save")
    def save_cho(payload: SaveRequest, request: Request) -> dict[str, object]:
        _verify_local_post(request)
        try:
            if payload.save_as:
                saved = editor.save_as(
                    payload.file_id,
                    payload.content,
                    force=payload.force,
                )
            else:
                if not payload.expected_version:
                    raise EditorValidationError(
                        "expected_version is required when saving an existing file."
                    )
                saved = editor.save_file(
                    payload.file_id,
                    payload.content,
                    expected_version=payload.expected_version,
                )
        except EditorError as exc:
            _raise_http_for_editor_error(exc)
        return {
            "file_id": saved.file_id,
            "version_token": saved.version_token,
            "summary": summarize_document(saved.document),
        }

    @app.post("/api/pdf")
    def render_pdf(payload: PdfRequest, request: Request) -> Response:
        _verify_local_post(request)
        try:
            doc = editor.validate_cho(payload.content)
            if payload.use_target_capo:
                if payload.target_capo is None:
                    raise EditorValidationError(
                        "target_capo is required when use_target_capo is true."
                    )
                doc = transpose_document(
                    doc,
                    target_capo=payload.target_capo,
                    source_capo=payload.source_capo,
                )
        except TranspositionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EditorError as exc:
            _raise_http_for_editor_error(exc)

        safe_title = _UNSAFE_PDF_NAME_RE.sub("_", doc.title).strip(" .") or "chord_sheet"
        capo_suffix = (
            f"_capo{doc.capo.value}"
            if doc.capo.status == CapoStatus.KNOWN and doc.capo.value is not None
            else ""
        )
        filename = f"{safe_title}{capo_suffix}.pdf"

        with _PDF_RENDER_LOCK, tempfile.TemporaryDirectory(prefix="chordpro_pdf_") as tmp_dir:
            tmp_pdf = Path(tmp_dir) / "output.pdf"
            try:
                ChromiumPdfRenderer(force=True).render(doc, tmp_pdf)
                pdf_bytes = tmp_pdf.read_bytes()
            except PdfRenderError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
                "X-Pdf-Filename": quote(filename),
            },
        )

    return app


def main(argv: list[str] | None = None) -> int:
    """Run the local ChordPro Web Editor bound strictly to 127.0.0.1."""
    parser = argparse.ArgumentParser(description="Run local ChordPro Web Editor.")
    parser.add_argument(
        "--dir", type=Path, default=Path("outputs"), help="Authorized .cho directory."
    )
    parser.add_argument("--port", type=int, default=8000, help="Local port (default: 8000).")
    args = parser.parse_args(argv)

    print(f"Starting ChordPro Web Editor at http://127.0.0.1:{args.port} (dir: {args.dir})")
    uvicorn.run(create_app(base_dir=args.dir), host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
