#!/usr/bin/env python3
"""Convert additional-material OCR text into pipeline-ready body XHTML.

Takes the plain-text OCR files from additional-material/ and produces a
single additional-body.xhtml that can be ingested by the IE pipeline.

The pipeline expects body XHTML with:
  - <h2> headings for each section (used by split_files for classification)
  - <!--se:split--> markers between sections
  - <p> wrapped paragraphs
  - Footnotes left inline (rough_cleanup + convert_endnotes handle extraction)

This script handles:
  1. Removing page headers/footers (running heads)
  2. Joining hyphenated line breaks
  3. Collapsing forced line breaks into paragraphs
  4. Extracting footnote text from bottom-of-page positions into inline markers
  5. Wrapping content in proper XHTML structure

Output: additional-body.xhtml in the book directory.
The pipeline can then be run with --body-file to ingest it.

Usage:
    python3 convert_additional_material.py [--book-dir DIR]
"""

import argparse
import re
import sys
from pathlib import Path


# Running head patterns to strip (page headers/footers from OCR)
RUNNING_HEAD_PATTERNS = [
    # Roman numeral page numbers with section title
    r'^\s*[ivxlcdm]+\s+(PREFACE\.|CONTENTS\.|PHYSICAL FEATURES\.|RELIGION.*|SOCIAL.*|CHRONOLOGY.*)',
    r'^\s*(PREFACE\.|CONTENTS\.|PHYSICAL FEATURES\.|RELIGION.*|SOCIAL.*|CHRONOLOGY.*|INTRODUCTION\.)\s+[ivxlcdm]+\s*$',
    # All-caps section headers on their own line (running heads)
    r'^\s*(PREFACE|CONTENTS|INTRODUCTION|PHYSICAL FEATURES|RELIGION OF THE RACE|SOCIAL PRINCIPLES|CHRONOLOGY AND OUTLINE.*|CHIEF SETTLERS.*|COMMONWEALTH.*|MONEY AND CURRENCY|ADDITIONS AND CORRECTIONS)\s*$',
    # Bare Roman numeral page numbers
    r'^\s*[ivxlcdm]{1,6}\s*$',
    # "INDEX." running head
    r'^\s*INDEX\.\s*$',
    # Section headers repeated as running heads with page numbers
    r'^\s*(FETCHES|SHAPESTRONG|BARESARKS|OPENNESS|THE LAND|HOUSE AND|CIVIL POWER|THEIR POWER|THINGS|ULFLJ|THE ALTHING|FUNCTIONS|THE SPEAKER|PROVINCIAL|THE QUARTERS|CHANGES|REVENGE|WAGER|THE DUTY|FATE AND|HALLOWING|ALLOTMENT|END OF|IRISH|HAROLD|RUSH OF|SUPERSTITIONS)\b.*$',
    # "ADDITIONS AND CORRECTIONS." running head
    r'^\s*ADDITIONS AND CORRECTIONS\.\s*$',
    # Page numbers (bare digits) — but only standalone
    r'^\s*\d{1,4}\s*$',
]

# Footnote markers in body text: *, †, ‡, §
FOOTNOTE_REFS = re.compile(r'(?<!\w)([*†‡§])(?!\w)')

# Lines that start footnote text at bottom of page
FOOTNOTE_START = re.compile(r'^([*†‡§])\s')


def clean_running_heads(text: str) -> str:
    """Remove page headers and running heads from OCR text."""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        skip = False
        for pattern in RUNNING_HEAD_PATTERNS:
            if re.match(pattern, stripped, re.IGNORECASE):
                skip = True
                break
        if not skip:
            cleaned.append(line)
    return '\n'.join(cleaned)


def join_hyphens(text: str) -> str:
    """Join words broken across lines by hyphens.
    
    'tra-\nding' → 'trading'
    But preserve em-dashes and intentional hyphens.
    """
    # Join hyphenated line breaks: lowercase-\nlowercase
    text = re.sub(r'([a-z])-\n([a-z])', r'\1\2', text)
    # Join hyphenated line breaks: uppercase-\n (proper nouns)
    text = re.sub(r'([A-Z][a-z]+)-\n([a-z])', r'\1\2', text)
    return text


def extract_footnotes(text: str) -> tuple[str, list[dict]]:
    """Extract footnote text from bottom-of-page positions.
    
    Returns (body_text, footnotes) where footnotes is a list of
    {marker, text} dicts. Footnotes are removed from body text.
    
    Strategy: Lines starting with *, †, ‡ after a block of body text
    are footnote text. They appear at the bottom of each scan page.
    """
    footnotes = []
    lines = text.split('\n')
    body_lines = []
    in_footnote = False
    current_footnote_marker = None
    current_footnote_text = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Check if this line starts a footnote
        m = FOOTNOTE_START.match(stripped)
        if m:
            # Save any previous footnote
            if current_footnote_marker:
                footnotes.append({
                    'marker': current_footnote_marker,
                    'text': ' '.join(current_footnote_text).strip()
                })
            current_footnote_marker = m.group(1)
            current_footnote_text = [stripped[1:].strip()]
            in_footnote = True
            continue
        
        if in_footnote:
            # Check if this line is continuation of footnote (indented or short)
            if stripped and (
                # Continuation: starts lowercase, or is continuation text
                stripped[0].islower() or
                # Or looks like a sentence continuation
                not stripped[0].isupper() or
                # Or the previous footnote text doesn't end with sentence terminator
                (current_footnote_text and not current_footnote_text[-1].rstrip().endswith(('.', ',', ';', ':', ')', ']')))
            ):
                # But not if this looks like a new paragraph (longer line starting with capital)
                if len(stripped) > 80 and stripped[0].isupper():
                    # This is probably new body text, not footnote continuation
                    if current_footnote_marker:
                        footnotes.append({
                            'marker': current_footnote_marker,
                            'text': ' '.join(current_footnote_text).strip()
                        })
                        current_footnote_marker = None
                        current_footnote_text = []
                    in_footnote = False
                    body_lines.append(line)
                    continue
                
                current_footnote_text.append(stripped)
            else:
                # End of footnote
                if current_footnote_marker:
                    footnotes.append({
                        'marker': current_footnote_marker,
                        'text': ' '.join(current_footnote_text).strip()
                    })
                    current_footnote_marker = None
                    current_footnote_text = []
                in_footnote = False
                body_lines.append(line)
        else:
            body_lines.append(line)
    
    # Save trailing footnote
    if current_footnote_marker:
        footnotes.append({
            'marker': current_footnote_marker,
            'text': ' '.join(current_footnote_text).strip()
        })
    
    return '\n'.join(body_lines), footnotes


def text_to_paragraphs(text: str) -> str:
    """Convert plain text to XHTML paragraphs.
    
    Splits on blank lines, wraps each block in <p> tags.
    Handles section headings (all-caps lines) as <h3> subheadings.
    """
    # Normalize whitespace
    text = re.sub(r'\r\n', '\n', text)
    
    # Split into blocks on double newlines
    blocks = re.split(r'\n\s*\n', text)
    
    html_blocks = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        
        # Join single newlines within a paragraph (soft wrap)
        block = re.sub(r'\n', ' ', block)
        block = re.sub(r'\s+', ' ', block).strip()
        
        # Escape XML
        block = (block
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
        )
        # Restore em-dashes and curly quotes that OCR produced
        # (they're literal Unicode in the source, so escaping is fine)
        
        # Detect subheadings: SHORT ALL-CAPS lines or known heading patterns
        if (len(block) < 100 and 
            (block.isupper() or 
             re.match(r'^(CHAPTER|APPENDIX|PREFACE|INTRODUCTION|INDEX|MONEY AND CURRENCY|ADDITIONS AND CORRECTIONS|ICELANDIC CHRONOLOGY|PHYSICAL FEATURES|RELIGION|SOCIAL PRINCIPLES|CHRONOLOGY|SEA-ROVING)', block, re.IGNORECASE))):
            html_blocks.append(f'<h3>{block}</h3>')
        else:
            html_blocks.append(f'<p>{block}</p>')
    
    return '\n'.join(html_blocks)


def process_section(name: str, title: str, text: str) -> tuple[str, list[dict]]:
    """Process one section of additional material.
    
    Returns (xhtml_body, footnotes) where xhtml_body is the content
    between <h2> and the next section.
    """
    # Remove page markers and running heads
    text = re.sub(r'--- Page \d+ ---', '', text)
    text = clean_running_heads(text)
    
    # Join hyphenated line breaks
    text = join_hyphens(text)
    
    # Extract footnotes
    text, footnotes = extract_footnotes(text)
    
    # Convert to paragraphs
    body_html = text_to_paragraphs(text)
    
    return body_html, footnotes


def build_footnote_endnotes(footnotes: list[dict], section_name: str) -> str:
    """Build an endnotes-style section from extracted footnotes."""
    if not footnotes:
        return ''
    
    lines = [f'<h2>Notes: {section_name}</h2>']
    # Group by marker sequence (they repeat per page: *, †, ‡, §)
    for i, fn in enumerate(footnotes, 1):
        marker = fn['marker']
        text = fn['text']
        # Escape
        text = (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
        )
        lines.append(f'<p id="note-{section_name}-{i}">{text}</p>')
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description="Convert additional material to pipeline-ready XHTML")
    parser.add_argument('--book-dir', type=Path,
                        default=Path('/root/projects/books/dasent-george-webbe-burnt-njal'))
    args = parser.parse_args()
    
    am_dir = args.book_dir / 'additional-material'
    if not am_dir.exists():
        print(f"ERROR: {am_dir} not found")
        sys.exit(1)
    
    # Section definitions: (filename, title, output_type)
    # output_type determines where it goes in the spine
    sections = [
        ('preface.txt', "Preface", 'preface'),
        ('intro-physical-features.txt', "Physical Features", 'appendix'),
        ('intro-religion.txt', "Religion of the Race", 'appendix'),
        ('intro-social-principles.txt', "Social Principles", 'appendix'),
        ('intro-commonwealth.txt', "The Icelandic Commonwealth", 'appendix'),
        ('intro-chief-settlers.txt', "Chief Settlers in the South-West", 'appendix'),
        ('intro-chronology-story.txt', "Chronology and Outline of the Story", 'appendix'),
        ('icelandic-chronology.txt', "Icelandic Chronology", 'frontmatter'),
        ('essay-sea-roving.txt', "Sea-Roving and the Viking Spirit", 'appendix'),
        ('essay-money-currency.txt', "Money and Currency in the Tenth Century", 'appendix'),
        ('additions-and-corrections.txt', "Additions and Corrections", 'appendix'),
    ]
    
    all_parts = []
    all_footnotes = []
    
    for filename, title, section_type in sections:
        filepath = am_dir / filename
        if not filepath.exists():
            print(f"  SKIP: {filename} not found")
            continue
        
        text = filepath.read_text(encoding='utf-8')
        
        # Strip comment header lines (lines starting with #)
        text = '\n'.join(line for line in text.split('\n') if not line.startswith('#'))
        
        body_html, footnotes = process_section(filename.replace('.txt', ''), title, text)
        
        print(f"  {filename}: {len(body_html):,} chars body, {len(footnotes)} footnotes")
        all_footnotes.extend(footnotes)
        
        all_parts.append(f'<h2 epub:type="title">{title}</h2>')
        all_parts.append(body_html)
        all_parts.append('<!--se:split-->')
    
    # Build the body XHTML
    html = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/, se: https://standardebooks.org/vocab/1.0" xml:lang="en-GB">
<head>
<title>Additional Material</title>
</head>
<body epub:type="backmatter">
{''.join(f'\n{part}\n' for part in all_parts)}
</body>
</html>"""
    
    out_path = args.book_dir / 'additional-body.xhtml'
    out_path.write_text(html, encoding='utf-8')
    print(f"\nWrote {out_path}")
    print(f"Total footnotes extracted: {len(all_footnotes)}")
    
    # Also write footnotes summary for review
    if all_footnotes:
        fn_path = am_dir / 'extracted-footnotes.txt'
        with open(fn_path, 'w') as f:
            f.write(f"# Extracted footnotes from additional material\n")
            f.write(f"# Total: {len(all_footnotes)} footnotes\n\n")
            for i, fn in enumerate(all_footnotes, 1):
                f.write(f"{fn['marker']} [{i}] {fn['text'][:120]}\n")
        print(f"Footnotes summary: {fn_path}")


if __name__ == '__main__':
    main()
