#!/usr/bin/env python3
"""
parse_pdf.py — Extract fish names from "Common and Scientific Names of Fishes"
8th edition PDF (AFS/ASIH, 2023) and write fish-name-checker/data/fish_names.json.

The PDF pages are landscape-formatted but stored portrait; each column of the
book table becomes a vertical x-strip in the PDF.  Characters within each word
are stored in reverse order.

Usage:
    uv run --with pymupdf python parse_pdf.py

Requires: pymupdf
"""

import json
import re
import sys
from pathlib import Path

try:
    import fitz  # pymupdf
except ImportError:
    print("ERROR: pymupdf not installed.")
    print("Run: uv run --with pymupdf python parse_pdf.py")
    sys.exit(1)

PDF_PATH    = Path(__file__).parent / "names_of_fishes" / "NAMES OF FISHES 8th.pdf"
OUTPUT_PATH = Path(__file__).parent / "fish-name-checker" / "data" / "fish_names.json"

# PDF page indices (0-based)
SPECIES_START  = 34   # page 35
SPECIES_END    = 229  # page 230
APPENDIX_START = 230  # page 231
APPENDIX_END   = 269  # page 270

# How close (in PDF points) x0 values must be to be grouped into the same strip
X_STRIP_TOL = 5

# ── Regexes ──────────────────────────────────────────────────────────────────

GENUS_RE   = re.compile(r'^[A-Z][a-z]{2,30}$')
SPECIES_RE = re.compile(r'^[a-z]{2,30}$')

# Occurrence codes: e.g. A:CMU, P:MU, A-P:CMU, F:CU, Ar:C
OCC_RE = re.compile(
    r'^([APFCMUAr](?:[-:,][APFCMUAr]{1,3})*'
    r'(?:\[I\]|\[X\]|\[XN\])*'
    r'(?:[-:,][APFCMUAr]{1,3}(?:\[I\]|\[X\]|\[XN\])*)*)$'
)

# Appendix synonym patterns (after character-reversal + strip joining)
TRANSFERRED_RE = re.compile(r'[Tt]ransferred\s+from\s+([A-Z][a-z]+)')
REPLACES_RE    = re.compile(r'[Rr]eplaces?\s+((?:[A-Z]\.?\s+)?[a-z]{3,})')
SYNONYMIZED_RE = re.compile(r'synonymiz\w+\s+with\s+((?:[A-Z]\.?\s+)?[a-z]{3,})')
FORMERLY_RE    = re.compile(r'(?:formerly|previously)\s+(?:known\s+as|listed\s+as)\s+([A-Z][a-z]+\s+[a-z]+)')


# ── Word extraction helpers ───────────────────────────────────────────────────

def extract_words_reversed(page):
    """
    Return list of word dicts ready for parsing.
    Each dict: {x0, x1, top, text, tokens}
    'tokens' splits the text on dot-leaders (2+ dots).

    PyMuPDF sorts characters by visual position, so words are already in
    correct reading order — no reversal needed.  It also decomposes ligature
    glyphs by default, so no manual ligature patching is required.
    """
    # get_text("words") returns (x0, y0, x1, y1, "word", block_no, line_no, word_no)
    raw = page.get_text("words")
    result = []
    for w in raw:
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
        # Split on dot-leaders to separate adjacent columns that got merged
        tokens = [t.strip() for t in re.split(r'\.{2,}', text) if t.strip()]
        result.append({
            'x0':    x0,
            'x1':    x1,
            'top':   y0,
            'text':  text,
            'tokens': tokens,
        })
    return result


def group_by_x_strip(words, tol=X_STRIP_TOL):
    """
    Group words into x-strips using a simple nearest-group algorithm.
    Returns dict: {representative_x0: [word, ...]}
    """
    groups = {}   # key = representative x0 (float)
    for w in words:
        x = w['x0']
        matched = None
        for key in groups:
            if abs(x - key) <= tol:
                matched = key
                break
        if matched is None:
            groups[x] = [w]
        else:
            groups[matched].append(w)
    return groups


# ── Species page parser ───────────────────────────────────────────────────────

def parse_strip(strip_words):
    """
    Given words in one x-strip (sorted descending by top = reading order),
    return a parsed dict with keys: type, genus, species, occurrence, common_en
    or type='order'/'family'/'skip'.
    """
    texts  = [w['text']  for w in strip_words]
    tokens = []
    for w in strip_words:
        tokens.extend(w['tokens'])

    # ── ORDER heading detection ──────────────────────────────────────────────
    if 'ORDER' in texts:
        idx = texts.index('ORDER')
        # Order name words follow ORDER (lower top = smaller index value after
        # sorting descending-top, so they come AFTER in the list)
        parts = []
        for t in texts[idx + 1:]:
            if re.match(r'^[A-Z]{2,}$', t):
                parts.append(t)
            else:
                break
        if not parts:
            # Try words before ORDER (some layouts put name before keyword)
            for t in texts[:idx]:
                if re.match(r'^[A-Z]{2,}$', t):
                    parts.append(t)
        name = ' '.join(p.capitalize() for p in parts)
        return {'type': 'order', 'value': name} if name else {'type': 'skip'}

    # ── Family heading detection ─────────────────────────────────────────────
    for t in texts:
        m = re.match(r'^([A-Z][a-z]+(?:idae|inae))\s*[–—\-]', t)
        if m:
            return {'type': 'family', 'value': m.group(1)}
        # Family name alone (no dash yet)
        if re.match(r'^[A-Z][a-z]+(?:idae|inae)$', t):
            return {'type': 'family', 'value': t}

    # ── Genus + species detection ────────────────────────────────────────────
    genus = None
    species_ep = None

    for i, t in enumerate(texts):
        if t in ('*', '^', '&', '+', '[I]', '[X]'):
            continue
        if GENUS_RE.match(t):
            for j in range(i + 1, min(i + 5, len(texts))):
                candidate = texts[j]
                if candidate in ('*', '^', '&'):
                    continue
                if SPECIES_RE.match(candidate):
                    genus = t
                    species_ep = candidate
                    break
            if genus:
                break

    if not genus:
        return {'type': 'skip'}

    # ── Occurrence code ──────────────────────────────────────────────────────
    occurrence = ''
    for tok in tokens:
        tok_clean = re.sub(r'[\s\.]', '', tok)
        if OCC_RE.match(tok_clean):
            occurrence = tok_clean
            break

    # ── English common name ──────────────────────────────────────────────────
    # All tokens, joined, after removing dots and splitting
    flat = ' '.join(tokens)
    flat = re.sub(r'\s+', ' ', flat).strip()

    common_en = ''
    if occurrence and occurrence in flat:
        after = flat.split(occurrence, 1)[1].strip()
        name_parts = []
        for tok in after.split():
            # English common names: mixed-case words starting with capital
            if re.match(r'^[A-Z][a-zA-Z\'\-]+$', tok) and len(tok) > 1:
                if not re.match(r'^[A-Z][a-z]+(?:idae|inae)$', tok):
                    name_parts.append(tok)
            elif name_parts:
                break
        common_en = ' '.join(name_parts)

    return {
        'type':      'species',
        'genus':     genus,
        'species':   species_ep,
        'occurrence': occurrence,
        'common_en': common_en,
    }


def parse_species_pages(pdf):
    valid_names: dict = {}
    genera: set = set()
    current_order  = ""
    current_family = ""

    total = min(SPECIES_END + 1, len(pdf))
    print(f"Parsing species pages {SPECIES_START + 1}–{total} ...")

    for page_idx in range(SPECIES_START, total):
        page  = pdf[page_idx]
        words = extract_words_reversed(page)
        strips = group_by_x_strip(words, X_STRIP_TOL)

        # Process strips in ascending x0 (= book reading order)
        for xkey in sorted(strips.keys()):
            strip_words = sorted(strips[xkey], key=lambda w: -w['top'])
            result = parse_strip(strip_words)

            if result['type'] == 'order':
                if result['value']:
                    current_order = result['value']
            elif result['type'] == 'family':
                current_family = result['value']
            elif result['type'] == 'species':
                g, s = result['genus'], result['species']
                binomial = f"{g} {s}"
                genera.add(g)
                if binomial not in valid_names:
                    valid_names[binomial] = {
                        "family":       current_family,
                        "order":        current_order,
                        "common_name_en": result['common_en'],
                    }

        if (page_idx + 1) % 25 == 0:
            done = page_idx + 1
            print(f"  page {done}/{total}  ({len(valid_names)} names so far)")

    return valid_names, genera


# ── Appendix parser ───────────────────────────────────────────────────────────

def expand_abbrev(abbrev: str, context_genus: str) -> str:
    m = re.match(r'([A-Z])\.?\s+([a-z]{3,})', abbrev.strip())
    if m and context_genus and context_genus[0] == m.group(1):
        return f"{context_genus} {m.group(2)}"
    if re.match(r'[A-Z][a-z]+\s+[a-z]+', abbrev.strip()):
        return abbrev.strip()
    return ""


def parse_appendix_pages(pdf, valid_names: dict) -> dict:
    synonyms: dict = {}
    total = min(APPENDIX_END + 1, len(pdf))
    print(f"\nParsing appendix pages {APPENDIX_START + 1}–{total} ...")

    # Collect all appendix text using the same word-reversal approach
    all_words = []
    for page_idx in range(APPENDIX_START, total):
        page  = pdf[page_idx]
        words = extract_words_reversed(page)
        all_words.extend(words)

    # Sort into reading order and join into a single text block
    strips = group_by_x_strip(all_words, X_STRIP_TOL)
    text_parts = []
    for xkey in sorted(strips.keys()):
        strip_words = sorted(strips[xkey], key=lambda w: -w['top'])
        # Join dot-split tokens
        for w in strip_words:
            text_parts.append(w['text'])

    raw_text = ' '.join(text_parts)
    raw_text = re.sub(r'\.{2,}', ' ', raw_text)
    raw_text = re.sub(r'\s+', ' ', raw_text).strip()

    # Split into sentences
    sentences = re.split(r'(?<=[\.!?])\s+(?=[A-Z])', raw_text)

    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 15:
            continue

        name_m = re.match(r'^([A-Z][a-z]+\s+[a-z]+)', sent)
        if not name_m:
            continue
        current_name  = name_m.group(1)
        current_genus = current_name.split()[0]

        tf = TRANSFERRED_RE.search(sent)
        if tf:
            old_genus = tf.group(1)
            epithet   = current_name.split()[1]
            old_name  = f"{old_genus} {epithet}"
            if old_name != current_name and old_name not in valid_names:
                synonyms[old_name] = current_name

        rep = REPLACES_RE.search(sent)
        if rep:
            old_name = expand_abbrev(rep.group(1).strip(), current_genus)
            if old_name and old_name != current_name and old_name not in valid_names:
                synonyms[old_name] = current_name

        syn = SYNONYMIZED_RE.search(sent)
        if syn:
            new_name = expand_abbrev(syn.group(1).strip(), current_genus)
            if new_name and current_name not in valid_names:
                synonyms[current_name] = new_name

        form = FORMERLY_RE.search(sent)
        if form:
            old_name = form.group(1)
            if old_name not in valid_names:
                synonyms[old_name] = current_name

    synonyms = {k: v for k, v in synonyms.items() if k not in valid_names}
    return synonyms


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}")
        sys.exit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print(f"Opening {PDF_PATH} ...")
    with fitz.open(str(PDF_PATH)) as pdf:
        print(f"Total pages in PDF: {len(pdf)}")
        valid_names, genera = parse_species_pages(pdf)
        synonyms = parse_appendix_pages(pdf, valid_names)

    data = {
        "metadata": {
            "edition": 8,
            "year":    2023,
            "source":  "Common and Scientific Names of Fishes from the United States, Canada, and Mexico (AFS/ASIH)",
            "species_count": len(valid_names),
        },
        "valid_names": valid_names,
        "genera":      sorted(genera),
        "synonyms":    synonyms,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\nDone.  ({size_kb:.0f} KB written to {OUTPUT_PATH})")
    print(f"  Valid species : {len(valid_names)}")
    print(f"  Unique genera : {len(genera)}")
    print(f"  Synonyms      : {len(synonyms)}")


if __name__ == "__main__":
    main()
