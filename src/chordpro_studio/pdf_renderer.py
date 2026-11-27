"""Formal Chromium Headless PDF renderer implementing interfaces.PdfRenderer."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from chordpro_studio.chordpro import StandardChordProConverter
from chordpro_studio.html_renderer import render_song_html
from chordpro_studio.models import PdfRenderOptions, SongDocument

DEFAULT_CHROMIUM_CANDIDATES = ("google-chrome", "chromium", "chromium-browser")
DEFAULT_TIMEOUT_SECONDS = 30.0


class PdfRenderError(RuntimeError):
    """Base error for PDF rendering."""


class PdfOutputExistsError(PdfRenderError):
    """Raised when the target PDF already exists and overwrite is not enabled."""


class ChromiumNotFoundError(PdfRenderError):
    """Raised when no Chromium/Chrome executable can be found."""


class ChromiumExecutionError(PdfRenderError):
    """Raised when Chromium exits non-zero or times out."""


class PdfValidationError(PdfRenderError):
    """Raised when the generated PDF file is missing, empty, or invalid."""


def resolve_chromium_executable(explicit_path: str | Path | None = None) -> str:
    """Resolve the Chromium/Chrome executable path."""
    if explicit_path is not None:
        p = Path(explicit_path)
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        found = shutil.which(str(explicit_path))
        if found:
            return found
        raise ChromiumNotFoundError(f"Specified Chromium executable not found: {explicit_path}")

    env_path = os.environ.get("CHORDPRO_STUDIO_CHROMIUM_PATH")
    if env_path:
        return resolve_chromium_executable(env_path)

    for candidate in DEFAULT_CHROMIUM_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found

    raise ChromiumNotFoundError(
        "No Chromium/Chrome executable found. Install google-chrome or pass --chromium."
    )


class ChromiumPdfRenderer:
    """Renders a `SongDocument` to an A4 PDF using Chromium Headless."""

    def __init__(
        self,
        *,
        chromium_path: str | Path | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        force: bool = False,
    ) -> None:
        self.chromium_path = chromium_path
        self.timeout = timeout
        self.force = force

    def render(
        self,
        song: SongDocument,
        output_path: Path,
        options: PdfRenderOptions | None = None,
    ) -> Path:
        """Render `song` to a PDF file at `output_path`."""
        _ = options or PdfRenderOptions()
        dest = Path(output_path)
        if dest.exists() and not self.force:
            raise PdfOutputExistsError(
                f"Output PDF already exists: {dest} (pass force=True or --force to overwrite)"
            )

        executable = resolve_chromium_executable(self.chromium_path)
        html_content = render_song_html(song)

        with tempfile.TemporaryDirectory(prefix="chordpro_pdf_") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            html_path = tmp_dir / "song.html"
            tmp_pdf = tmp_dir / "song.pdf"
            user_data_dir = tmp_dir / "chrome_profile"
            user_data_dir.mkdir(parents=True, exist_ok=True)
            html_path.write_text(html_content, encoding="utf-8")

            cmd = [
                executable,
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--user-data-dir={user_data_dir}",
                f"--print-to-pdf={tmp_pdf}",
                html_path.as_uri(),
            ]

            try:
                proc = subprocess.run(
                    cmd,
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ChromiumExecutionError(
                    f"Chromium timed out after {self.timeout}s."
                ) from exc
            except OSError as exc:
                raise ChromiumExecutionError(f"Failed to execute Chromium: {exc}") from exc

            if proc.returncode != 0:
                raise ChromiumExecutionError(
                    f"Chromium exited with code {proc.returncode}: {proc.stderr.strip()}"
                )

            if not tmp_pdf.exists() or tmp_pdf.stat().st_size == 0:
                raise PdfValidationError("Chromium did not produce a non-empty PDF file.")

            header = tmp_pdf.read_bytes()[:5]
            if header != b"%PDF-":
                raise PdfValidationError(f"Invalid PDF header: {header!r}")

            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_pdf), str(dest))

        return dest


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: convert a `.cho` file to `.pdf`."""
    parser = argparse.ArgumentParser(description="Render a ChordPro (.cho) file to A4 PDF.")
    parser.add_argument("input_cho", type=Path, help="Input .cho file path.")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output .pdf file path.")
    parser.add_argument(
        "--chromium", type=str, default=None, help="Path to Chromium/Chrome binary."
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing PDF file.")
    args = parser.parse_args(argv)

    if not args.input_cho.exists():
        print(f"Error: Input file not found: {args.input_cho}", file=sys.stderr)
        return 1

    try:
        cho_text = args.input_cho.read_text(encoding="utf-8")
        doc = StandardChordProConverter().from_chordpro(cho_text)
        renderer = ChromiumPdfRenderer(chromium_path=args.chromium, force=args.force)
        out = renderer.render(doc, args.output)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Successfully rendered PDF: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
