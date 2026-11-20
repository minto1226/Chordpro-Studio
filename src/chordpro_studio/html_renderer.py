"""Render SongDocument / SongLayout into self-contained print-ready HTML."""

from __future__ import annotations

import html
from importlib import resources

from chordpro_studio.layout import (
    BlankRow,
    ChordOnlyRow,
    LyricPair,
    RenderedPhrase,
    SongLayout,
    build_layout,
)
from chordpro_studio.models import SongDocument


def _load_reference_css() -> str:
    css_res = resources.files("chordpro_studio.resources").joinpath("chord_sheet.css")
    if not css_res.is_file():
        raise FileNotFoundError("Required package resource 'chord_sheet.css' not found.")
    return css_res.read_text(encoding="utf-8")


def _render_phrase_html(phrase: RenderedPhrase) -> str:
    segs: list[str] = []
    for seg in phrase.segments:
        chord_html = html.escape(seg.chord, quote=True) if seg.chord else ""
        text_html = html.escape(seg.text, quote=True)
        segs.append(
            f'<span class="seg"><span class="chord">{chord_html}</span>'
            f'<span class="lyric">{text_html}</span></span>'
        )
    return f'<div class="phrase">{"".join(segs)}</div>'


def render_layout_html(layout: SongLayout) -> str:
    """Render a `SongLayout` into a self-contained UTF-8 HTML document."""
    css = _load_reference_css()
    title_html = html.escape(layout.header.title, quote=True)
    artist_html = html.escape(layout.header.artist, quote=True)

    meta_parts = [f"<span>歌手：{artist_html}</span>"]
    if layout.header.capo_label:
        capo_html = html.escape(layout.header.capo_label, quote=True)
        meta_parts.append(f"<span>{capo_html}</span>")

    sections_html: list[str] = []
    for sec in layout.sections:
        rows_html: list[str] = []
        if sec.show_label:
            sec_name = html.escape(sec.name, quote=True)
            rows_html.append(f'<div class="section-label">[{sec_name}]</div>')

        for row in sec.rows:
            if isinstance(row, BlankRow):
                rows_html.append('<div class="blank-row" style="height: 3.5mm;"></div>')
            elif isinstance(row, ChordOnlyRow):
                group_htmls = []
                for grp in row.groups:
                    spans = []
                    for item in grp:
                        margin_em = min(item.gap_before, 8) * 0.45
                        style = f' style="margin-left: {margin_em:.2f}em;"' if margin_em > 0 else ""
                        spans.append(
                            f'<span class="chord"{style}>'
                            f"{html.escape(item.chord, quote=True)}</span>"
                        )
                    group_htmls.append(
                        '<div class="chords-only-group">' + "".join(spans) + "</div>"
                    )
                joined = '<span class="bar-sep">|</span>'.join(group_htmls)
                rows_html.append(f'<div class="chords-only-row">{joined}</div>')
            elif isinstance(row, LyricPair):
                left_html = _render_phrase_html(row.left)
                if row.right is not None:
                    right_html = _render_phrase_html(row.right)
                    rows_html.append(
                        f'<div class="pair-row">{left_html}'
                        f'<span class="bar-sep">|</span>{right_html}</div>'
                    )
                else:
                    rows_html.append(f'<div class="pair-row">{left_html}</div>')

        sections_html.append(f'<div class="section-block">{"".join(rows_html)}</div>')

    return (
        "<!DOCTYPE html>\n"
        '<html lang="ja">\n'
        "<head>\n"
        '  <meta charset="UTF-8" />\n'
        f"  <title>{title_html}</title>\n"
        f"  <style>\n{css}\n  </style>\n"
        "</head>\n"
        "<body>\n"
        '  <div class="sheet">\n'
        '    <header class="song-header">\n'
        f'      <h1 class="song-title">{title_html}</h1>\n'
        f'      <div class="song-meta">{"".join(meta_parts)}</div>\n'
        "    </header>\n"
        f'    {"".join(sections_html)}\n'
        "  </div>\n"
        "</body>\n"
        "</html>\n"
    )


def render_song_html(doc: SongDocument) -> str:
    """Convert a `SongDocument` directly into self-contained print-ready HTML."""
    return render_layout_html(build_layout(doc))
