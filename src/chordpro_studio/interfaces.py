"""Module interface contracts for ChordPro Studio.

These Protocols define the boundaries between the ChordPro converter,
editor, and PDF renderer without premature implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from chordpro_studio.models import PdfRenderOptions, SongDocument


class ChordProConverter(Protocol):
    """Converts between SongDocument and editable ChordPro (.cho) text."""

    def to_chordpro(self, song: SongDocument) -> str:
        """Serialize a SongDocument into ChordPro (.cho) format."""
        ...

    def from_chordpro(self, content: str) -> SongDocument:
        """Parse edited ChordPro (.cho) text back into a SongDocument."""
        ...


class SongEditor(Protocol):
    """Manages local .cho file editing and re-import workflows."""

    def export_for_edit(self, song: SongDocument, path: Path) -> Path:
        """Write SongDocument to a .cho file for user editing."""
        ...

    def reload_edited(self, path: Path) -> SongDocument:
        """Reload a user-edited .cho file into a validated SongDocument."""
        ...


class PdfRenderer(Protocol):
    """Renders a SongDocument into a formal guitar chord sheet PDF.

    Note: Layout design and PDF generation are out of scope for T00.
    """

    def render(
        self,
        song: SongDocument,
        output_path: Path,
        options: PdfRenderOptions | None = None,
    ) -> Path:
        """Render the given SongDocument to a PDF file at output_path."""
        ...
