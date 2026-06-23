#!/usr/bin/env python3
"""Fix endnotes for Burnt Njal (PG 597).

Problems:
  1. split_files.py dropped 24 of 55 endnotes sections (chapters 1-74)
  2. Endnotes are in table/<p> format, not SE-standard <ol><li>
  3. Body text (N) markers have no hyperlinks
  4. No backlinks from notes to body

This script:
  1. Extracts ALL endnotes from the original PG HTML
  2. Builds a single endnotes.xhtml with proper <ol><li> structure
  3. Converts body text (N) markers to <a epub:type="noteref"> links
  4. Adds backlinks from each note back to its chapter

Usage:
    python3 fix_endnotes.py [--book-dir DIR] [--pg-html PATH]
"""

import argparse
import os
import re
import sys
import html as html_mod
from pathlib import Path


def extract_pg_endnotes(pg_html_path: str) -> list[dict]:
    """Extract all endnotes sections from PG HTML.
    
    Returns list of {chapter: int, notes: [(num, text), ...]}
    """
    content = html_mod.unescape(Path(pg_html_path).read_text(encoding="utf-8"))
    
    en_positions = [(m.start(), m.end()) for m in re.finditer(r'>\s*ENDNOTES:?\s*<', content)]
    
    sections = []
    for start, end in en_positions:
        # Find next heading after this endnotes marker
        next_heading = re.search(r'<h[234]', content[end:])
        block_end = end + next_heading.start() if next_heading else end + 5000
        block = content[end:block_end]
        
        # Find which PG chapter precedes this endnotes section
        prev_ch = None
        for cm in re.finditer(r'<h[234][^>]*>(\d+)\.', content[:start]):
            prev_ch = int(cm.group(1))
        
        # Extract individual notes: (N) text
        # Strip HTML tags for clean text
        clean = re.sub(r'<[^>]+>', ' ', block)
        clean = html_mod.unescape(clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        # Remove leading "ENDNOTES:" if present
        clean = re.sub(r'^.*?ENDNOTES:?\s*', '', clean)
        
        notes = []
        # Split on (N) markers, keeping the number
        parts = re.split(r'\((\d+)\)', clean)
        for i in range(1, len(parts) - 1, 2):
            num = int(parts[i])
            text = parts[i + 1].strip()
            # Clean up whitespace
            text = re.sub(r'\s+', ' ', text)
            # Remove leading/trailing cruft
            text = text.strip()
            if text:
                notes.append((num, text))
        
        if notes and prev_ch:
            sections.append({"chapter": prev_ch, "notes": notes})
    
    return sections


def build_endnotes_xhtml(sections: list[dict]) -> str:
    """Build a single endnotes.xhtml from all sections."""
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        'epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/, '
        'se: https://standardebooks.org/vocab/1.0" xml:lang="en-GB">',
        '\t<head>',
        '\t\t<title>Endnotes</title>',
        '\t\t<link href="../css/core.css" rel="stylesheet" type="text/css"/>',
        '\t\t<link href="../css/local.css" rel="stylesheet" type="text/css"/>',
        '\t</head>',
        '\t<body epub:type="backmatter">',
        '\t\t<section id="endnotes" epub:type="endnotes">',
        '\t\t\t<h2 epub:type="title">Endnotes</h2>',
    ]
    
    total = 0
    for sec in sections:
        chap = sec["chapter"]
        for num, text in sec["notes"]:
            total += 1
            note_id = f"note-{chap}-{num}"
            backlink = f'chapter-{chap}.xhtml#noteref-{chap}-{num}'
            # Escape XML special chars
            text_escaped = (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))
            lines.append(
                f'\t\t\t<p id="{note_id}">{text_escaped} '
                f'<a href="{backlink}" epub:type="backlink">↩</a></p>'
            )
    
    lines.extend([
        '\t\t</section>',
        '\t</body>',
        '</html>',
    ])
    
    print(f"  Built endnotes.xhtml: {total} notes from {len(sections)} sections")
    return "\n".join(lines)


def link_body_markers(text_dir: Path, sections: list[dict]) -> int:
    """Replace (N) markers in chapter files with noteref links.
    
    Returns count of markers replaced.
    """
    # Build lookup: for each chapter, what note numbers exist?
    chapter_notes = {}
    for sec in sections:
        chapter_notes[sec["chapter"]] = {num: text for num, text in sec["notes"]}
    
    total_replaced = 0
    
    for chap_num in sorted(chapter_notes.keys()):
        chap_file = text_dir / f"chapter-{chap_num}.xhtml"
        if not chap_file.exists():
            continue
        
        content = chap_file.read_text(encoding="utf-8")
        notes_map = chapter_notes[chap_num]
        changed = False
        
        for note_num in sorted(notes_map.keys()):
            marker = f"({note_num})"
            # Only replace markers that aren't already inside <a> tags
            # and aren't part of larger numbers like (10) when looking for (1)
            
            # Use regex to find (N) not inside a tag
            # Pattern: (N) not preceded by href= or inside <a>...</a>
            def replace_marker(m):
                nonlocal changed, total_replaced
                pos = m.start()
                # Check if inside an existing <a> tag
                before = content[:pos]
                last_open_a = before.rfind("<a ")
                last_close_a = before.rfind("</a>")
                if last_open_a > last_close_a:
                    return m.group(0)  # Inside <a> tag, skip
                
                note_id = f"note-{chap_num}-{note_num}"
                ref_id = f"noteref-{chap_num}-{note_num}"
                # Replace (N) with superscript link
                total_replaced += 1
                changed = True
                return (f'<a href="endnotes.xhtml#{note_id}" '
                        f'id="{ref_id}" epub:type="noteref">{note_num}</a>')
            
            # Match (N) as a standalone marker
            # Use negative lookbehind to avoid matching inside URLs or IDs
            new_content = re.sub(
                rf'(?<!\d)\({note_num}\)(?!\d)',
                replace_marker,
                content,
            )
            content = new_content
        
        if changed:
            chap_file.write_text(content, encoding="utf-8")
    
    print(f"  Linked {total_replaced} body markers across {len(chapter_notes)} chapters")
    return total_replaced


def remove_old_endnotes(text_dir: Path) -> int:
    """Remove old endnotes-N.xhtml files."""
    count = 0
    for f in text_dir.glob("endnotes-*.xhtml"):
        f.unlink()
        count += 1
    print(f"  Removed {count} old endnotes-N.xhtml files")
    return count


def update_opf(book_dir: Path):
    """Update content.opf: remove old endnotes-N references, ensure endnotes.xhtml in manifest/spine."""
    opf_path = book_dir / "src" / "epub" / "content.opf"
    opf = opf_path.read_text(encoding="utf-8")
    
    # Remove manifest items for endnotes-N.xhtml
    opf = re.sub(
        r'\s*<item\s+[^>]*href="text/endnotes-\d+\.xhtml"[^>]*/>',
        '',
        opf,
    )
    # Remove spine items for endnotes-N.xhtml
    opf = re.sub(
        r'\s*<itemref\s+idref="endnotes-\d+\.xhtml"\s*/>',
        '',
        opf,
    )
    
    # Ensure endnotes.xhtml is in manifest
    if 'href="text/endnotes.xhtml"' not in opf:
        # Add to manifest
        opf = re.sub(
            r'(<manifest>)',
            r'\1\n\t\t<item href="text/endnotes.xhtml" id="endnotes.xhtml" media-type="application/xhtml+xml"/>',
            opf,
            count=1,
        )
    
    # Ensure endnotes.xhtml is in spine (before permissions/colophon)
    if 'idref="endnotes.xhtml"' not in opf:
        # Insert before permissions or colophon, whichever comes first
        for anchor in ["permissions.xhtml", "colophon.xhtml", "uncopyright.xhtml"]:
            if f'idref="{anchor}"' in opf:
                opf = re.sub(
                    rf'(.*?)(<itemref\s+idref="{anchor}")',
                    r'\1<itemref idref="endnotes.xhtml"/>\n\t\t\2',
                    opf,
                    count=1,
                    flags=re.DOTALL,
                )
                break
    
    opf_path.write_text(opf, encoding="utf-8")
    print(f"  Updated OPF manifest and spine")


def main():
    parser = argparse.ArgumentParser(description="Fix endnotes for Burnt Njal")
    parser.add_argument("--book-dir", type=Path, 
                        default=Path("/root/projects/books/dasent-george-webbe-burnt-njal"))
    parser.add_argument("--pg-html", type=Path,
                        default=Path("/tmp/pg597.html"))
    args = parser.parse_args()
    
    book_dir = args.book_dir
    text_dir = book_dir / "src" / "epub" / "text"
    pg_html = str(args.pg_html)
    
    if not args.pg_html.exists():
        print(f"ERROR: PG HTML not found at {pg_html}")
        sys.exit(1)
    
    print("=== Extracting endnotes from PG HTML ===")
    sections = extract_pg_endnotes(pg_html)
    total_notes = sum(len(s["notes"]) for s in sections)
    print(f"  Found {len(sections)} sections, {total_notes} total notes")
    
    print("\n=== Building endnotes.xhtml ===")
    endnotes_xhtml = build_endnotes_xhtml(sections)
    (text_dir / "endnotes.xhtml").write_text(endnotes_xhtml, encoding="utf-8")
    
    print("\n=== Removing old endnotes-N.xhtml files ===")
    remove_old_endnotes(text_dir)
    
    print("\n=== Linking body markers ===")
    link_body_markers(text_dir, sections)
    
    print("\n=== Updating OPF ===")
    update_opf(book_dir)
    
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
