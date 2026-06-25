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


# Placeholder pattern for footnote markers in body text.
# Uses rare Unicode chars that won't appear in OCR text.
# Format: ⟦FN:N⟧ where N is the note number within the section.
FN_PLACEHOLDER = re.compile(r'⟦FN:(\d+)⟧')

def tag_footnote_markers(body_text: str, footnotes: list[dict], start_index: int) -> tuple[str, int]:
    """Replace footnote marker chars in body text with numbered placeholders.
    
    For each footnote, find the first unlinked occurrence of its marker symbol
    (e.g., '*', '†', '‡') in the body text and replace it with ⟦FN:N⟧.
    
    Markers can appear after word chars, closing parens, or punctuation:
    - word†  (most common)
    - )†     (after parenthetical)
    - .†     (after sentence end — rare)
    
    Returns (modified_body_text, next_index).
    """
    idx = start_index
    for fn in footnotes:
        marker = fn['marker']
        idx += 1
        escaped = re.escape(marker)
        # Match: word char, closing paren/quote, or punctuation + marker
        # Not followed by another marker or letter (avoids decorative runs)
        pattern = re.compile(rf'([\w\)\.,;:!?’”]){escaped}(?![\w{escaped}])')
        match = pattern.search(body_text)
        if match:
            pos = match.end() - 1  # position of the marker char
            body_text = body_text[:pos] + f'⟦FN:{idx}⟧' + body_text[match.end():]
        # If no match, the footnote has no body marker — still gets a number
    return body_text, idx


def join_hyphens(text: str) -> str:
    """Join words broken across lines by hyphens.
    
    Handles:
    - Hard hyphens: 'rash-\\nness' → 'rashness'  (join without space)
    - Soft breaks (no hyphen): 'island\\nin' → 'island in'  (add space)
    - Em-dash breaks: 'word—\\nword' → 'word—word'
    """
    # Hard hyphen at end of line: join without space
    # Use \w to handle Unicode letters (þ, ð, æ, é, etc.)
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    # Also catch "word- \n word" (space after hyphen before newline)
    text = re.sub(r'(\w)- \n(\w)', r'\1\2', text)
    # Soft break (no hyphen): add a space
    text = re.sub(r'(\w)\n(\w)', r'\1 \2', text)
    text = re.sub(r'([a-z,;:])\n([A-Z])', r'\1 \2', text)
    # Em-dash at end or beginning of line: join without adding space
    text = re.sub(r'—\n', '—', text)
    text = re.sub(r'\n—', '—', text)
    return text


def fix_missing_spaces(text: str, word_dict: set = None) -> str:
    """Fix missing spaces between words from OCR artifacts.
    
    Uses three strategies:
    1. Dictionary-based splitting for merged lowercase words (needs word_dict)
    2. lowercase→uppercase transition detection (Mc/Mac excluded)
    3. digit→letter transitions
    """
    if word_dict is None:
        word_dict = set()
    
    # Strategy 1: Split merged lowercase words using dictionary
    def split_merged_token(match):
        token = match.group(0)
        tl = token.lower()
        if len(tl) < 6:
            return token
        # Already a known word? Skip
        if tl in word_dict:
            return token
        # Try to find a split point where both halves are known words
        # Require both halves >= 3 chars. Prefer longest right half
        # (handles "thereader" → "the"+"reader" not "there"+"ader")
        best_split = None
        for split_pos in range(3, len(tl) - 2):
            left = tl[:split_pos]
            right = tl[split_pos:]
            if left in word_dict and right in word_dict:
                if best_split is None or len(right) > best_split[0]:
                    best_split = (len(right), split_pos)
        if best_split:
            sp = best_split[1]
            return token[:sp] + ' ' + token[sp:]
        return token
    
    text = re.sub(r"[a-zA-Z']{6,}", split_merged_token, text)
    
    # Strategy 2: lowercase→uppercase (missing space before proper noun)
    def add_space(m):
        prefix = m.group(1)
        suffix = m.group(2)
        if prefix.lower() in ('mc', 'mac', 'o'):
            return m.group(0)
        return prefix + ' ' + suffix
    
    text = re.sub(r'([a-z]{2,})([A-Z][a-z])', add_space, text)
    
    # Strategy 3: digit→letter
    text = re.sub(r'(\d)([A-Z][a-z])', r'\1 \2', text)
    
    return text


def merge_short_paragraphs(paragraphs: list[str]) -> list[str]:
    """Merge paragraphs that are likely OCR page-break artifacts.
    
    A paragraph starting with lowercase or a continuation word is probably
    a page-break artifact, not a real paragraph break.
    """
    if len(paragraphs) < 2:
        return paragraphs
    
    merged = [paragraphs[0]]
    for para in paragraphs[1:]:
        prev = merged[-1]
        # Merge if:
        # 1. Previous doesn't end with sentence-ending punctuation
        # 2. Current starts with lowercase
        should_merge = (
            prev and
            not prev.endswith(('.', '!', '?', ':', ';', '."', '!"', '?"', '."', '—')) and
            para and para[0].islower()
        )
        if should_merge:
            merged[-1] = prev + ' ' + para
        else:
            merged.append(para)
    
    return merged


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


def classify_short_text(text: str, section_title: str = '') -> str:
    """Classify a short paragraph as 'subheading', 'strip', or 'paragraph'.
    
    - 'subheading': legitimate section subheading → keep as <h3>
    - 'strip': duplicate of section title or page artifact → remove
    - 'paragraph': not a heading → keep as <p>
    """
    if len(text) > 100:
        return 'paragraph'
    
    # Normalize for comparison
    title_norm = re.sub(r'[^\w\s]', '', section_title.lower()).strip()
    text_norm = re.sub(r'[^\w\s]', '', text.lower()).strip()
    
    # Check if it's a duplicate of the section title (exact match only)
    if title_norm and text_norm == title_norm:
        return 'strip'
    
    # Check if it's a page artifact
    if re.match(r'^vol\.\s*[ivxlcdm]+\.?$', text, re.IGNORECASE):
        return 'strip'
    if text.lower().strip('.') in ('the end', 'finis', 'fin'):
        return 'strip'
    
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
        r'^(PUBLIC LIFE|THE ICELANDERS ABROAD|CONCLUSION)$',
        # Sea-roving poem stanza headings
        r'^(QUEEN GUNNHILLDA|ODIN|SIGMUND)',
        # Bare proper-name subheadings in essays
        r'^[A-Z][A-Z\s\.\-]{4,60}$',
    ]
    for pat in patterns:
        if re.match(pat, text):
            return 'subheading'
    return 'paragraph'


def is_subheading(text: str) -> bool:
    """Backward-compatible wrapper."""
    return classify_short_text(text) == 'subheading'


def process_section(name: str, raw_text: str, word_dict: set = None) -> tuple[list[str], list[dict]]:
    """Process one section: strip headers, extract footnotes, build paragraphs.
    
    Returns (paragraphs, footnotes) where footnotes have been numbered
    with 'index' keys for linking.
    """
    # Strip comment header lines
    raw_text = '\n'.join(l for l in raw_text.split('\n') if not l.startswith('#'))
    
    # Split into pages
    pages = split_pages(raw_text)
    
    all_body_text = []
    all_footnotes = []
    note_idx = 0  # global note counter for this section
    
    for page_num, page_text in pages:
        # Strip running head from top of page
        page_text = strip_running_head(page_text)
        
        # Extract footnotes from bottom of page
        body_text, footnotes = extract_page_footnotes(page_text)
        
        # Tag footnote markers in body text with numbered placeholders
        body_text, note_idx = tag_footnote_markers(body_text, footnotes, note_idx)
        
        # Assign indices to footnotes
        for i, fn in enumerate(footnotes):
            fn['index'] = note_idx - len(footnotes) + i + 1
        
        all_body_text.append(body_text)
        all_footnotes.extend(footnotes)
    
    # Join all body text and convert to paragraphs
    combined = '\n'.join(all_body_text)
    combined = join_hyphens(combined)
    paragraphs = body_to_paragraphs(combined)
    
    # Post-processing: fix OCR artifacts
    paragraphs = [fix_missing_spaces(p, word_dict or set()) for p in paragraphs]
    # Note: full fix_ocr_spacing runs later (after escape_xml) in build_section_xhtml
    paragraphs = merge_short_paragraphs(paragraphs)
    
    return paragraphs, all_footnotes


def fix_ocr_spacing(text: str) -> str:
    """Fix common OCR spacing artifacts in text content.
    
    Handles:
    - Double spaces: collapse to single (t-001)
    - Space before punctuation: "word !" → "word!"
    - Hyphen+space within words: "Fjórðungs- þing" → "Fjórðungsþing"
    - Space before closing quotes: —" → —"
    - Abbreviations: wrap in <abbr> for se lint t-029
    """
    # Collapse double+ spaces (t-001)
    text = re.sub(r"  +", " ", text)
    # Remove space before punctuation (!, ?, ;, :, ,)
    text = re.sub(r' +([!?;:,])', r'\1', text)
    
    # Fix space before opening quotes (after escape_xml, " → &quot;)
    text = re.sub(r' &quot; ', ' &quot;', text)
    text = re.sub(r" &apos; ", " &apos;", text)
    
    # Fix space before closing quotes after em-dash: —&quot; → —&quot;
    text = re.sub(r'—\s+&quot;', '—&quot;', text)
    text = re.sub(r'—\s+&apos;', "—&apos;", text)
    
    # Fix hyphen+space within words (OCR line-break artifacts)
    text = re.sub(r'(\w)- (\w)', r'\1\2', text)
    
    # Wrap common abbreviations in <abbr> (t-029: period + lowercase)
    text = re.sub(r'\bN\.\s*lat\b', '<abbr>N. lat</abbr>', text)
    text = re.sub(r'\bW\.\s*long\b', '<abbr>W. long</abbr>', text)
    text = re.sub(r'\bS\.\s*lat\b', '<abbr>S. lat</abbr>', text)
    text = re.sub(r'\bE\.\s*long\b', '<abbr>E. long</abbr>', text)
    text = re.sub(r'\bDict\.\s*sub\b', '<abbr>Dict. sub</abbr>', text)
    text = re.sub(r'\bvol\.\s*i\b', '<abbr>vol. i</abbr>', text, flags=re.IGNORECASE)
    text = re.sub(r'\bvol\.\s*ii\b', '<abbr>vol. ii</abbr>', text, flags=re.IGNORECASE)
    text = re.sub(r'\bvol\.\s*iii\b', '<abbr>vol. iii</abbr>', text, flags=re.IGNORECASE)
    text = re.sub(r'\bvol\.\s*iv\b', '<abbr>vol. iv</abbr>', text, flags=re.IGNORECASE)
    text = re.sub(r'\bvol\.\s*v\b', '<abbr>vol. v</abbr>', text, flags=re.IGNORECASE)
    
    return text


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
            action = classify_short_text(para, title)
            if action == 'subheading':
                parts.append(f'<h3>{escape_xml(para)}</h3>')
            elif action == 'paragraph':
                parts.append(f'<p>{escape_xml(para)}</p>')
            # 'strip' → skip entirely
        
        # Footnote section for this part
        if footnotes:
            parts.append(f'<h3>Notes</h3>')
            for i, fn in enumerate(footnotes, 1):
                fn_text = fix_ocr_spacing(escape_xml(fn['text']))
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


def convert_fn_placeholders(text: str, short_name: str) -> str:
    """Convert ⟦FN:N⟧ placeholders to SE-style noteref links."""
    def replace_fn(m):
        n = m.group(1)
        note_id = f"note-{short_name}-{n}"
        ref_id = f"noteref-{short_name}-{n}"
        return f'<a id="{ref_id}" href="#{note_id}" epub:type="noteref"><sup>{n}</sup></a>'
    return FN_PLACEHOLDER.sub(replace_fn, text)


def build_section_xhtml(title: str, paragraphs: list[str], footnotes: list[dict],
                        short_name: str, section_type: str, section_id: str = None) -> str:
    """Build a single finished XHTML file for one section.
    
    Produces a complete, pipeline-ready XHTML file that the manifest builder
    and spine reorder will pick up automatically.
    
    Footnote markers in body text (⟦FN:N⟧ placeholders) are converted to
    SE-style <a epub:type="noteref"> links. Notes get back-references.
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
    used_slugs = set()
    
    # Image mapping: PLATE text → image file
    PLATE_IMAGES = {
        'PLATE 1': ('plate-1-ground-plan.jpg', 'Ground plan of the interior of an old Icelandic skáli (hall), showing high seats, hearths, doors, and sleeping places. Drawn by Sigurður Guðmundsson, Reykjavík.'),
        'PLATE 2': ('plate-2-floor-plan.jpg', 'Floor plan of the old Icelandic skáli or hall, showing passages, porch, store-rooms, and pillar-doors. Engraved by Bartholomew & Co., Edinburgh.'),
        'PLATE 3': ('plate-3-section-lengthways.jpg', 'Section lengthways of the old Icelandic skáli or hall, showing hangings, lofts, and internal structure.'),
        'PLATE 4': ('plate-4-cross-section.jpg', 'Cross section at one end of the old Icelandic skáli or hall.'),
    }
    
    # Body paragraphs
    in_subsection = False
    for para in paragraphs:
        # Check for PLATE marker
        plate_match = re.match(r'^PLATE (\d+)\.?\s*$', para.strip())
        if plate_match:
            plate_key = f'PLATE {plate_match.group(1)}'
            if plate_key in PLATE_IMAGES:
                img_file, alt_text = PLATE_IMAGES[plate_key]
                parts.append(f'\t\t\t<figure class="full-page" id="{short_name}-plate-{plate_match.group(1)}">')
                parts.append(f'\t\t\t\t<img src="../images/{img_file}" alt="{escape_xml(alt_text)}"/>')
                parts.append(f'\t\t\t\t<figcaption><span epub:type="z3998:roman">{plate_match.group(1)}</span>. {escape_xml(alt_text)}</figcaption>')
                parts.append(f'\t\t\t</figure>')
                continue
        
        action = classify_short_text(para, title)
        if action == 'subheading':
            # Close previous subsection if open
            if in_subsection:
                parts.append('\t\t\t</section>')
            # Titlecase ALL CAPS subheadings
            heading_text = para
            if heading_text == heading_text.upper() and len(heading_text) > 3:
                heading_text = heading_text.title().replace("Iceland", "Iceland")
                # Fix common titlecase issues
                for fix in [("The North Men In Iceland", "The North Men in Iceland"),
                            ("Of The", "of the"), ("In The", "in the"),
                            ("To The", "to the"), ("And The", "and the")]:
                    heading_text = heading_text.replace(fix[0], fix[1])
            # Open new subsection with heading
            # Use heading text to generate an id slug (with dedup)
            slug = re.sub(r'[^a-z0-9]+', '-', heading_text.lower().strip('.')).strip('-')
            base_slug = slug
            counter = 2
            while slug in used_slugs:
                slug = f'{base_slug}-{counter}'
                counter += 1
            used_slugs.add(slug)
            parts.append(f'\t\t\t<section id="{short_name}-{slug}">')
            parts.append(f'\t\t\t\t<h3 epub:type="title">{escape_xml(heading_text)}</h3>')
            in_subsection = True
        elif action == 'paragraph':
            # Escape XML entities first (before adding link tags)
            para = escape_xml(para)
            # Fix OCR spacing errors after XML escaping
            para = fix_ocr_spacing(para)
            # Then convert FN placeholders to noteref links
            para = convert_fn_placeholders(para, short_name)
            # Add class="continued" if paragraph starts with lowercase
            # (OCR page-break continuations from the original scan)
            stripped = para.lstrip()
            if stripped and stripped[0].islower():
                parts.append(f'\t\t\t<p class="continued">{para}</p>')
            else:
                parts.append(f'\t\t\t<p>{para}</p>')
        # 'strip' → skip entirely
    
    # Close last subsection if still open
    if in_subsection:
        parts.append('\t\t\t</section>')
    
    # Footnote section for this part
    
    # Supplementary figures for specific sections
    if short_name == 'chronology-outline':
        parts.append('\t\t\t<figure class="full-page" id="front-view-icelandic-hall">')
        parts.append('\t\t\t\t<img src="../images/front-view-icelandic-hall.jpg" alt="Front view of the old Icelandic skáli or hall, showing the roofline, entrance porch, and surrounding landscape."/>')
        parts.append('\t\t\t\t<figcaption>Front view of the old Icelandic skáli or hall. Engraved by Bartholomew &amp; Co., Edinburgh.</figcaption>')
        parts.append('\t\t\t</figure>')
        parts.append('\t\t\t<figure class="full-page" id="plan-thingvalla">')
        parts.append('\t\t\t\t<img src="../images/plan-thingvalla.jpg" alt="Plan of Thingvalla or Thingfield, showing Thingvalla Lake, the Great Rift (Almannagjá), Raven\'s Rift (Hrafnagjá), and surrounding landscape."/>')
        parts.append('\t\t\t\t<figcaption>Plan of Thingvalla or Thingfield. Engraved by Bartholomew &amp; Co., Edinburgh.</figcaption>')
        parts.append('\t\t\t</figure>')
        parts.append('\t\t\t<figure class="full-page" id="plan-almannagia">')
        parts.append('\t\t\t\t<img src="../images/plan-almannagia-althing.jpg" alt="Enlarged plan of the Almannagjá and Althing, showing the Great Rift, booths, bridge, and the Hill of Laws (Lögberg)."/>')
        parts.append('\t\t\t\t<figcaption>Enlarged plan of the Almannagjá and Althing. Engraved by Bartholomew &amp; Co., Edinburgh.</figcaption>')
        parts.append('\t\t\t</figure>')
        parts.append('\t\t\t<figure class="full-page" id="map-sw-iceland">')
        parts.append('\t\t\t\t<img src="../images/map-sw-iceland.jpg" alt="Map of the south-western portion of Iceland, showing saga sites including Bergthorsknoll, Lithend, and the Markar River."/>')
        parts.append('\t\t\t\t<figcaption>Map of the south-western portion of Iceland. Engraved by Bartholomew &amp; Co., Edinburgh.</figcaption>')
        parts.append('\t\t\t</figure>')
    
    if footnotes:
        parts.append('\t\t\t<hr/>')
        parts.append(f'\t\t\t<section id="{short_name}-endnotes" epub:type="endnotes">')
        parts.append('\t\t\t\t<h3 epub:type="title">Notes</h3>')
        for fn in footnotes:
            n = fn['index']
            note_id = f"note-{short_name}-{n}"
            ref_id = f"noteref-{short_name}-{n}"
            fn_text = fix_ocr_spacing(escape_xml(fn['text']))
            # Back-reference link before the note text
            parts.append(f'\t\t\t\t<p id="{note_id}"><a href="#{ref_id}">{n}</a> {fn_text}</p>')
        parts.append('\t\t\t</section>')
    
    body_content = '\n'.join(parts)
    
    # Use section_id (from output filename) if provided, else short_name
    sid = section_id if section_id else short_name
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/, se: https://standardebooks.org/vocab/1.0" xml:lang="en-GB">
\t<head>
\t\t<title>{escape_xml(title)}</title>
\t\t<link href="../css/core.css" rel="stylesheet" type="text/css"/>
\t\t<link href="../css/local.css" rel="stylesheet" type="text/css"/>
\t</head>
\t<body epub:type="{outer_type}">
\t\t<section id="{sid}" epub:type="{section_semantic}">
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
         'appendix-15.xhtml', 'appendix'),
        ('sea-roving', 'essay-sea-roving.txt', "Sea-Roving and the Viking Spirit",
         'appendix-12.xhtml', 'appendix'),
        ('money-currency', 'essay-money-currency.txt', "Money and Currency in the Tenth Century",
         'appendix-13.xhtml', 'appendix'),
        ('additions', 'additions-and-corrections.txt', "Additions and Corrections",
         'appendix-14.xhtml', 'appendix'),
    ]
    
    # Build word dictionary: system dict + PG chapters + supplement
    word_dict = set()
    # System dictionary (if available)
    sys_dict_path = Path('/usr/share/dict/american-english')
    if sys_dict_path.exists():
        for line in sys_dict_path.read_text().splitlines():
            w = line.strip().lower()
            if w and len(w) >= 2:
                word_dict.add(w)
    # PG chapter words (saga-specific terms)
    for ch_file in text_dir.glob('chapter-*.xhtml'):
        ch_content = ch_file.read_text(encoding='utf-8')
        ch_text = re.sub(r'<[^>]+>', ' ', ch_content)
        word_dict.update(w.lower() for w in re.findall(r"[a-zA-Z']+", ch_text))
    # Supplement
    supp_path = args.book_dir / '.supplemental-dict.txt'
    if supp_path.exists():
        for line in supp_path.read_text().splitlines():
            word_dict.update(w.strip().lower() for w in line.split() if w.strip())
    
    print(f"  Dictionary: {len(word_dict):,} words (system + PG + supplement)")
    
    total_footnotes = 0
    total_paragraphs = 0
    
    for short_name, filename, title, out_filename, section_type in sections_def:
        filepath = am_dir / filename
        if not filepath.exists():
            print(f"  SKIP: {filename} not found")
            continue
        
        raw_text = filepath.read_text(encoding='utf-8')
        paragraphs, footnotes = process_section(short_name, raw_text, word_dict)
        
        total_footnotes += len(footnotes)
        total_paragraphs += len(paragraphs)
        print(f"  {out_filename:30s}: {len(paragraphs):4d} paragraphs, {len(footnotes):3d} footnotes")
        
        # Derive section_id from output filename (e.g., "appendix-6.xhtml" → "appendix-6")
        section_id = out_filename.replace('.xhtml', '')
        xhtml = build_section_xhtml(title, paragraphs, footnotes, short_name, section_type, section_id)
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
            _, footnotes = process_section(short_name, raw_text, word_dict)
            if footnotes:
                f.write(f"\n=== {title} ({out_fname}) ===\n")
                for i, fn in enumerate(footnotes, 1):
                    f.write(f"{fn['marker']} [{i}] {fn['text'][:150]}\n")
    print(f"Footnotes summary: {fn_path}")


if __name__ == '__main__':
    main()
