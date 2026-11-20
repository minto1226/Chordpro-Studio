"""Safe ChordPro file editor service with Capo transposition and conflict detection."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from chordpro_studio.chordpro import StandardChordProConverter
from chordpro_studio.models import CapoStatus, SongDocument
from chordpro_studio.transposition import TranspositionError, transpose_document


class EditorError(RuntimeError):
    """Base error for SongEditor operations."""


class EditorNotFoundError(EditorError):
    """Raised when a requested .cho file does not exist."""


class EditorPermissionError(EditorError):
    """Raised when a path escapes the authorized workspace directory."""


class EditorConflictError(EditorError):
    """Raised when a file was modified externally or already exists on Save As."""


class EditorValidationError(EditorError):
    """Raised when ChordPro content or transposition parameters are invalid."""


@dataclass(frozen=True)
class LoadedFile:
    """Loaded .cho file with its content, version token, and parsed summary."""

    file_id: str
    content: str
    version_token: str
    document: SongDocument


@dataclass(frozen=True)
class TransposePreview:
    """Non-destructive Capo transposition preview."""

    cho_text: str
    document: SongDocument


def compute_version_token(content: str) -> str:
    """Return a SHA-256 version token for optimistic concurrency checks."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _atomic_write_utf8(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".cho_tmp_", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        Path(tmp_name).replace(target)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


class LocalSongEditor:
    """Manages local .cho file editing, validation, and Capo transposition."""

    def __init__(
        self,
        base_dir: Path,
        converter: StandardChordProConverter | None = None,
    ) -> None:
        self.base_dir = base_dir.resolve()
        self.converter = converter or StandardChordProConverter()

    def export_for_edit(self, song: SongDocument, path: Path) -> Path:
        """Write `SongDocument` to a `.cho` file for user editing."""
        resolved = self.resolve_safe_path(path.name if not path.is_absolute() else str(path))
        cho_text = self.converter.to_chordpro(song)
        _atomic_write_utf8(resolved, cho_text)
        return resolved

    def reload_edited(self, path: Path) -> SongDocument:
        """Reload a user-edited `.cho` file into a validated `SongDocument`."""
        resolved = self.resolve_safe_path(path.name if not path.is_absolute() else str(path))
        if not resolved.exists():
            raise EditorNotFoundError(f"File not found: {resolved.name}")
        content = resolved.read_text(encoding="utf-8")
        return self.validate_cho(content)

    def resolve_safe_path(self, file_id: str) -> Path:
        """Resolve a relative `.cho` filename safely within `self.base_dir`."""
        cleaned = file_id.strip()
        if not cleaned or Path(cleaned).is_absolute():
            raise EditorPermissionError(f"Absolute or empty paths are not allowed: {file_id!r}")
        if "/" in cleaned or "\\" in cleaned or ".." in cleaned:
            raise EditorPermissionError(f"Path traversal is not allowed: {file_id!r}")
        if not cleaned.endswith(".cho"):
            raise EditorPermissionError(f"Only .cho files are allowed: {file_id!r}")
        candidate = (self.base_dir / cleaned).resolve()
        if candidate.parent != self.base_dir:
            raise EditorPermissionError(f"Path escapes authorized directory: {file_id!r}")
        return candidate

    def list_files(self) -> list[str]:
        """List `.cho` filenames in `self.base_dir`."""
        if not self.base_dir.exists():
            return []
        return sorted(p.name for p in self.base_dir.iterdir() if p.is_file() and p.suffix == ".cho")

    def load_file(self, file_id: str) -> LoadedFile:
        """Load a `.cho` file, compute its version token, and parse `SongDocument`."""
        path = self.resolve_safe_path(file_id)
        if not path.exists():
            raise EditorNotFoundError(f"File not found: {file_id}")
        content = path.read_text(encoding="utf-8")
        doc = self.validate_cho(content)
        return LoadedFile(
            file_id=path.name,
            content=content,
            version_token=compute_version_token(content),
            document=doc,
        )

    def validate_cho(self, content: str) -> SongDocument:
        """Parse and validate ChordPro text into a `SongDocument`."""
        if not content.strip():
            raise EditorValidationError("ChordPro content cannot be empty.")
        try:
            return self.converter.from_chordpro(content)
        except Exception as exc:
            raise EditorValidationError(f"Invalid ChordPro content: {exc}") from exc

    def transpose_preview(
        self,
        content: str,
        target_capo: int,
        *,
        source_capo: int | None = None,
    ) -> TransposePreview:
        """Parse current CHO text and return a non-destructive transposed preview."""
        doc = self.validate_cho(content)
        try:
            transposed = transpose_document(doc, target_capo=target_capo, source_capo=source_capo)
        except TranspositionError as exc:
            raise EditorValidationError(str(exc)) from exc
        cho_text = self.converter.to_chordpro(transposed)
        return TransposePreview(cho_text=cho_text, document=transposed)

    def save_file(
        self,
        file_id: str,
        content: str,
        *,
        expected_version: str | None = None,
    ) -> LoadedFile:
        """Validate and atomically save `content` to an existing `.cho` file."""
        path = self.resolve_safe_path(file_id)
        if not path.exists():
            raise EditorNotFoundError(f"File not found: {file_id}")

        doc = self.validate_cho(content)
        current_disk = path.read_text(encoding="utf-8")
        current_token = compute_version_token(current_disk)
        if expected_version is not None and expected_version != current_token:
            raise EditorConflictError(
                f"File {file_id!r} was modified externally; reload before saving."
            )

        _atomic_write_utf8(path, content)
        return LoadedFile(
            file_id=path.name,
            content=content,
            version_token=compute_version_token(content),
            document=doc,
        )

    def save_as(
        self,
        new_file_id: str,
        content: str,
        *,
        force: bool = False,
    ) -> LoadedFile:
        """Validate and save `content` to a new `.cho` file without overwriting by default."""
        path = self.resolve_safe_path(new_file_id)
        if path.exists() and not force:
            raise EditorConflictError(
                f"Target file {new_file_id!r} already exists (use force=True to overwrite)."
            )
        doc = self.validate_cho(content)
        _atomic_write_utf8(path, content)
        return LoadedFile(
            file_id=path.name,
            content=content,
            version_token=compute_version_token(content),
            document=doc,
        )


def summarize_document(doc: SongDocument) -> dict[str, object]:
    """Return a lightweight JSON-serializable summary of a `SongDocument`."""
    all_lines = [line for sec in doc.sections for line in sec.lines]
    return {
        "title": doc.title,
        "artist": doc.artist,
        "capo_status": doc.capo.status.value,
        "capo_value": doc.capo.value if doc.capo.status == CapoStatus.KNOWN else None,
        "section_count": len(doc.sections),
        "line_count": len(all_lines),
        "chord_count": sum(len(line.chords) for line in all_lines),
        "warnings": list(doc.diagnostics.warnings),
    }
