#!/usr/bin/env python3
"""Convert additional-material OCR text into pipeline-ready body XHTML.

Takes the plain-text OCR files from additional-material/ and produces a
single additional-body.xhtml that can be ingested by the IE pipeline.

Algorithm:
  1. Split text by "--- Page N ---" markers
  2. Within each page, remove running heads (headers/footers)
  3. Find footnotes at bottom of page (lines starting with *, †, ‡, §)
  4. Body text = everything before footnotes
  5. Join body text across pages into continuous paragraphs
  6. Collect footnotes into a separate notes section per major section

Output: additional-body.xhtml in the book directory.
"""

import argparse
import re
import sys
from pathlib import Path


def split_pages(text: str) -> list[tuple[int, str]]:
    """Split text on --- Page N --- markers, returning (page_num, page_text) pairs."""
    pages = []
    parts = re.split(r'--- Page (\d+) ---', text)
    # parts[0] is the header, then alternating: page_num, page_text
    for i in range(1, len(parts), 2):
        page_num = int(parts[i])
        page_text = parts[i + 1] if i + 1 < len(parts) else ""
        pages.append((page_num, page_text))
    return pages


def strip_running_head(page_text: str) -> str:
    """Remove the running head (page header) from a page.
    
    Running heads look like:
      "PREFACE.                                     vii"
      "vi                                     PREFACE."
      "PHYSICAL FEATURES.                                  iii"
      "RELIGION OF THE RACE.                                xv"
    They're the first non-empty line and contain a section title + Roman numeral.
    """
    lines = page_text.split('\n')
    if not lines:
        return page_text
    
    # Find first non-empty line
    first_idx = 0
    while first_idx < len(lines) and not lines[first_idx].strip():
        first_idx += 1
    
    if first_idx >= len(lines):
        return page_text
    
    first_line = lines[first_idx].strip()
    
    # Is it a running head? Check for patterns:
    # 1. Roman numeral page number + section title
    # 2. Section title + Roman numeral
    # 3. All-caps section title alone
    is_running_head = False
    
    # Pattern: word(s) + Roman numeral or Roman numeral + word(s)
    roman_pat = r'^[ivxlcdm]{1,8}[\.\s]|[ivxlcdm]{1,8}$'
    title_words = ['PREFACE', 'CONTENTS', 'INTRODUCTION', 'PHYSICAL', 'FEATURES',
                   'RELIGION', 'SOCIAL', 'PRINCIPLES', 'COMMONWEALTH', 'CHIEF',
                   'SETTLERS', 'CHRONOLOGY', 'OUTLINE', 'STORY', 'ICELANDIC',
                   'MONEY', 'CURRENCY', 'ADDITIONS', 'CORRECTIONS', 'INDEX',
                   'SEA', 'ROVING', 'SAGA', 'NORTHMEN', 'LANDNAM', 'HALLOWING',
                   'ALLOTMENT', 'REVENGE', 'WAGER', 'FETCHES', 'SHAPESTRONG',
                   'BARESARKS', 'OPENNESS', 'THINGS', 'ULFLJ', 'ALTHING',
                   'FUNCTIONS', 'SPEAKER', 'PROVINCIAL', 'QUARTERS', 'CHANGES',
                   'POWER', 'END', 'IRISH', 'HAROLD', 'RUSH', 'SUPERSTITIONS',
                   'HOUSE', 'TEMPLE', 'HUMAN', 'SACRED', 'SACRIFICES', 'FEASTS',
                   'TOASTS', 'CIVIL', 'SHIFTING', 'ORIGIN', 'DUTY', 'FATE',
                   'MANLINESS', 'INDEPENDENCE']
    
    for word in title_words:
        if word in first_line.upper():
            # Check if it also has a Roman numeral or is just the header
            if re.search(r'[ivxlcdm]{1,8}', first_line, re.IGNORECASE) or len(first_line) < 80:
                is_running_head = True
                break
    
    # Also check: bare Roman numeral page number
    if re.match(r'^[ivxlcdm]{1,8}\s*$', first_line, re.IGNORECASE):
        is_running_head = True
    
    # Or bare Arabic page number
    if re.match(r'^\d{1,4}\s*$', first_line):
        is_running_head = True
    
    # Or a known multi-word running head pattern
    running_head_patterns = [
        r'^\s*[ivxlcdm]+\s+[A-Z]',  # Roman numeral + Capitalized text
        r'^[A-Z][A-Z\s\.\,]+[ivxlcdm]+\s*$',  # ALL CAPS text + Roman numeral
        r'^[A-Z\s\.\,]{5,80}$',  # ALL CAPS line under 80 chars (running head)
    ]
    for pat in running_head_patterns:
        if re.match(pat, first_line) and len(first_line) < 100:
            is_running_head = True
            break
    
    if is_running_head:
        # Remove the first non-empty line
        lines.pop(first_idx)
        return '\n'.join(lines)
    
    return page_text


def extract_page_footnotes(page_text: str) -> tuple[str, list[dict]]:
    """Extract footnotes from a single page.
    
    Footnotes are at the bottom of the page, starting with *, †, ‡, §.
    Everything from the first footnote marker to end of page is footnote text.
    
    Returns (body_text, footnotes) where footnotes is a list of
    {marker, text} dicts.
    """
    lines = page_text.split('\n')
    
    # Find the first footnote line
    fn_start_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Footnote starts with *, †, ‡, § at start of line
        # But not if it's a math/correction expression like "* 100" or "5 * 3"
        if stripped and stripped[0] in '*†‡§':
            # Verify: next char should be space or letter (not digit/operator)
            if len(stripped) > 1 and (stripped[1].isspace() or stripped[1].isalpha()):
                fn_start_idx = i
                break
    
    if fn_start_idx is None:
        return page_text, []
    
    body_lines = lines[:fn_start_idx]
    fn_lines = lines[fn_start_idx:]
    
    # Parse footnote lines into individual footnotes
    footnotes = []
    current_marker = None
    current_text = []
    
    for line in fn_lines:
        stripped = line.strip()
        if not stripped:
            continue
        
        if stripped[0] in '*†‡§' and len(stripped) > 1 and (stripped[1].isspace() or stripped[1].isalpha()):
            # New footnote
            if current_marker:
                footnotes.append({
                    'marker': current_marker,
                    'text': ' '.join(current_text).strip()
                })
            current_marker = stripped[0]
            current_text = [stripped[1:].strip()]
        elif current_marker:
            # Continuation of current footnote
            current_text.append(stripped)
        else:
            # Text before any footnote marker — shouldn't happen, 
            # but treat as body text
            body_lines.append(line)
    
    if current_marker:
        footnotes.append({
            'marker': current_marker,
            'text': ' '.join(current_text).strip()
        })
    
    return '\n'.join(body_lines), footnotes


def join_hyphens(text: str) -> str:
    """Join words broken across lines by hyphens."""
    text = re.sub(r'([a-z])-?\n([a-z])', r'\1\2', text)
    text = re.sub(r'([A-Z][a-z]+)-\n([a-z])', r'\1\2', text)
    return text


def body_to_paragraphs(text: str) -> list[str]:
    """Convert cleaned body text to paragraphs.
    
    Joins soft-wrapped lines into paragraphs (split on blank lines).
    Returns list of paragraph strings.
    """
    # Normalize whitespace
    text = text.strip()
    
    # Split on blank lines
    blocks = re.split(r'\n\s*\n', text)
    
    paragraphs = []
    for block in blocks:
        # Join lines within a paragraph
        block = re.sub(r'\s+', ' ', block).strip()
        if block:
            paragraphs.append(block)
    
    return paragraphs


def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;'))


def is_subheading(text: str) -> bool:
    """Check if a short paragraph is actually a subheading."""
    if len(text) > 100:
        return False
    # Known subheading patterns
    patterns = [
        r'^(PREFACE|INTRODUCTION|CONTENTS|INDEX)\.?$',
        r'^(PHYSICAL FEATURES|RELIGION OF THE RACE|SOCIAL PRINCIPLES)$',
        r'^(THE ICELANDIC COMMONWEALTH|CHIEF SETTLERS.*|CHRONOLOGY.*)$',
        r'^(MONEY AND CURRENCY|ADDITIONS AND CORRECTIONS)$',
        r'^(SEA-ROVING|ICELANDIC CHRONOLOGY)$',
        r'^(FIRST SETTLERS|THE NORTHMEN|RUSH OF SETTLERS)$',
        r'^(HALLOWING THE LAND|ALLOTMENT OF LAND)$',
        r'^(HOUSE AND TEMPLE|WORSHIP|HUMAN SACRIFICES|SACRED TOASTS)$',
        r'^(THE DUTY OF REVENGE|WAGER OF BATTLE|FATE AND FAME)$',
        r'^(OPENNESS AND MANLINESS|END OF THE LANDNAMTIDE)$',
        r'^(THEIR POWER|THINGS|ORIGIN OF A COMMONWEALTH)$',
        r'^(THE ALTHING|FUNCTIONS OF THE ALTHING|THE SPEAKER)$',
        r'^(PROVINCIAL|THE QUARTERS|CHANGES IN THE)$',
        r'^(CIVIL POWER|SHIFTING NATURE)$',
        r'^(SUPERSTITIONS|FETCHES|SHAPESTRONG|BARESARKS)$',
        r'^(KETTLE|BAUG|THE FLEETLITHE|ASGERDA)$',
        r'^(HOLT-THORIR|JORUND|AUD THE)$',
        r'^(ERIC\'S DEATH SONG)$',
        r'^(ADDITIONS AND CORRECTIONS)$',
        # Sub-sections within the chronology outline
        r'^(THE STORY|THE BURNING|THE LAWSUIT|THE VENGEANCE)$',
        # Bare proper-name subheadings in essays
        r'^[A-Z][A-Z\s\.\-]{4,60}$',
    ]
    for pat in patterns:
        if re.match(pat, text):
            return True
    return False


def process_section(name: str, raw_text: str) -> tuple[list[str], list[dict]]:
    """Process one section: strip headers, extract footnotes, build paragraphs.
    
    Returns (paragraphs, footnotes).
    """
    # Strip comment header lines
    raw_text = '\n'.join(l for l in raw_text.split('\n') if not l.startswith('#'))
    
    # Split into pages
    pages = split_pages(raw_text)
    
    all_body_text = []
    all_footnotes = []
    
    for page_num, page_text in pages:
        # Strip running head from top of page
        page_text = strip_running_head(page_text)
        
        # Extract footnotes from bottom of page
        body_text, footnotes = extract_page_footnotes(page_text)
        
        all_body_text.append(body_text)
        all_footnotes.extend(footnotes)
    
    # Join all body text and convert to paragraphs
    combined = '\n'.join(all_body_text)
    combined = join_hyphens(combined)
    paragraphs = body_to_paragraphs(combined)
    
    return paragraphs, all_footnotes


def build_xhtml(sections: list[tuple[str, str, list[str], list[dict]]]) -> str:
    """Build the complete XHTML document from processed sections.
    
    sections: list of (filename, title, paragraphs, footnotes)
    """
    parts = []
    
    for filename, title, paragraphs, footnotes in sections:
        # Section heading
        parts.append(f'<h2 epub:type="title">{escape_xml(title)}</h2>')
        
        # Body paragraphs
        for para in paragraphs:
            if is_subheading(para):
                parts.append(f'<h3>{escape_xml(para)}</h3>')
            else:
                parts.append(f'<p>{escape_xml(para)}</p>')
        
        # Footnote section for this part
        if footnotes:
            parts.append(f'<h3>Notes</h3>')
            for i, fn in enumerate(footnotes, 1):
                fn_text = escape_xml(fn['text'])
                parts.append(f'<p id="note-{filename}-{i}">{fn_text}</p>')
        
        # Split marker between sections
        parts.append('<!--se:split-->')
    
    body = '\n'.join(parts)
    
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/, se: https://standardebooks.org/vocab/1.0" xml:lang="en-GB">
<head>
<title>Additional Material</title>
</head>
<body epub:type="backmatter">
{body}
</body>
</html>"""


def build_section_xhtml(title: str, paragraphs: list[str], footnotes: list[dict],
                        short_name: str, section_type: str) -> str:
    """Build a single finished XHTML file for one section.
    
    Produces a complete, pipeline-ready XHTML file that the manifest builder
    and spine reorder will pick up automatically.
    """
    # Determine epub:type based on section type
    if section_type == 'preface':
        outer_type = 'frontmatter'
        section_semantic = 'z3998:preface'
    elif section_type == 'frontmatter':
        outer_type = 'frontmatter'
        section_semantic = 'z3998:roman'  # generic frontmatter
    else:  # appendix / backmatter
        outer_type = 'backmatter'
        section_semantic = 'appendix'
    
    parts = []
    
    # Body paragraphs
    for para in paragraphs:
        if is_subheading(para):
            parts.append(f'\t\t\t<h3>{escape_xml(para)}</h3>')
        else:
            parts.append(f'\t\t\t<p>{escape_xml(para)}</p>')
    
    # Footnote section for this part
    if footnotes:
        parts.append('\t\t\t<hr/>')
        parts.append('\t\t\t<h3 epub:type="title">Notes</h3>')
        for i, fn in enumerate(footnotes, 1):
            fn_text = escape_xml(fn['text'])
            note_id = f"note-{short_name}-{i}"
            parts.append(f'\t\t\t<p id="{note_id}" epub:type="endnote">{fn_text}</p>')
    
    body_content = '\n'.join(parts)
    
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/, se: https://standardebooks.org/vocab/1.0" xml:lang="en-GB">
\t<head>
\t\t<title>{escape_xml(title)}</title>
\t\t<link href="../css/core.css" rel="stylesheet" type="text/css"/>
\t\t<link href="../css/local.css" rel="stylesheet" type="text/css"/>
\t</head>
\t<body epub:type="{outer_type}">
\t\t<section id="{short_name}" epub:type="{section_semantic}">
\t\t\t<h2 epub:type="title">{escape_xml(title)}</h2>
{body_content}
\t\t</section>
\t</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Convert additional material to pipeline-ready XHTML files")
    parser.add_argument('--book-dir', type=Path,
                        default=Path('/root/projects/books/dasent-george-webbe-burnt-njal'))
    args = parser.parse_args()
    
    am_dir = args.book_dir / 'additional-material'
    text_dir = args.book_dir / 'src' / 'epub' / 'text'
    if not am_dir.exists():
        print(f"ERROR: {am_dir} not found")
        sys.exit(1)
    
    # (short_name, filename, title, output_filename, section_type)
    sections_def = [
        ('preface', 'preface.txt', "Preface", 'preface.xhtml', 'preface'),
        ('physical-features', 'intro-physical-features.txt', "Physical Features",
         'appendix-6.xhtml', 'appendix'),
        ('religion', 'intro-religion.txt', "Religion of the Race",
         'appendix-7.xhtml', 'appendix'),
        ('social-principles', 'intro-social-principles.txt', "Social Principles",
         'appendix-8.xhtml', 'appendix'),
        ('commonwealth', 'intro-commonwealth.txt', "The Icelandic Commonwealth",
         'appendix-9.xhtml', 'appendix'),
        ('chief-settlers', 'intro-chief-settlers.txt', "Chief Settlers in the South-West",
         'appendix-10.xhtml', 'appendix'),
        ('chronology-outline', 'intro-chronology-story.txt', "Chronology and Outline of the Story",
         'appendix-11.xhtml', 'appendix'),
        ('icelandic-chronology', 'icelandic-chronology.txt', "Icelandic Chronology",
         'icelandic-chronology.xhtml', 'frontmatter'),
        ('sea-roving', 'essay-sea-roving.txt', "Sea-Roving and the Viking Spirit",
         'appendix-12.xhtml', 'appendix'),
        ('money-currency', 'essay-money-currency.txt', "Money and Currency in the Tenth Century",
         'appendix-13.xhtml', 'appendix'),
        ('additions', 'additions-and-corrections.txt', "Additions and Corrections",
         'appendix-14.xhtml', 'appendix'),
    ]
    
    total_footnotes = 0
    total_paragraphs = 0
    
    for short_name, filename, title, out_filename, section_type in sections_def:
        filepath = am_dir / filename
        if not filepath.exists():
            print(f"  SKIP: {filename} not found")
            continue
        
        raw_text = filepath.read_text(encoding='utf-8')
        paragraphs, footnotes = process_section(short_name, raw_text)
        
        total_footnotes += len(footnotes)
        total_paragraphs += len(paragraphs)
        print(f"  {out_filename:30s}: {len(paragraphs):4d} paragraphs, {len(footnotes):3d} footnotes")
        
        xhtml = build_section_xhtml(title, paragraphs, footnotes, short_name, section_type)
        out_path = text_dir / out_filename
        out_path.write_text(xhtml, encoding='utf-8')
    
    print(f"\nWrote {len(sections_def)} files to {text_dir}")
    print(f"Total: {total_paragraphs} paragraphs, {total_footnotes} footnotes")
    
    # Write footnotes summary
    fn_path = am_dir / 'extracted-footnotes.txt'
    with open(fn_path, 'w') as f:
        f.write(f"# Extracted footnotes from additional material\n")
        f.write(f"# Total: {total_footnotes} footnotes\n\n")
        for short_name, filename, title, out_fname, section_type in sections_def:
            filepath = am_dir / filename
            if not filepath.exists():
                continue
            raw_text = filepath.read_text(encoding='utf-8')
            _, footnotes = process_section(short_name, raw_text)
            if footnotes:
                f.write(f"\n=== {title} ({out_fname}) ===\n")
                for i, fn in enumerate(footnotes, 1):
                    f.write(f"{fn['marker']} [{i}] {fn['text'][:150]}\n")
    print(f"Footnotes summary: {fn_path}")


if __name__ == '__main__':
    main()
