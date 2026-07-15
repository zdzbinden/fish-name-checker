#!/usr/bin/env python3
"""
Step 3b (round-2 revision): split each extracted text into BODY and REFERENCES.

Reviewer 1 noted that real misspellings in the analysis (e.g. Pomoxis anularis,
Lepomis macrohirus) come from the TITLE of a cited reference, not the authors'
own usage. FISHFINDER validates the whole PDF, so reference-list names are
counted as errors. Here we locate the reference/bibliography section and split
it off so the headline analysis runs on body text only; names appearing solely
in references are tabulated separately.

Detection: find the LAST reference-heading occurrence that (a) falls past ~50%
of the document and (b) is followed by a high density of citation markers
(years-in-parens, DOIs, "et al."). If no confident split is found, the whole
text is treated as body (fail-safe = the previous behaviour) and recorded as
`references_split: "none"`.

Outputs:  cache/texts_body/<hash>.txt, cache/texts_refs/<hash>.txt
          cache/reference_split_report.json
Usage:    uv run python 03b_split_references.py
"""
import json
import re
from pathlib import Path
from config import TEXT_DIR, CACHE_DIR

BODY_DIR = CACHE_DIR / "texts_body"
REFS_DIR = CACHE_DIR / "texts_refs"
REPORT = CACHE_DIR / "reference_split_report.json"

HEAD_RE = re.compile(
    r'(?im)(?:^|\n)[ \t]*(?:\d+\.?[ \t]*)?'
    r'(references|references and notes|literature cited|works cited|bibliography|'
    r'references cited)[ \t]*(?:\n|$)')

CITATION_MARKERS = re.compile(r'\(\d{4}[a-z]?\)|(?<!\d)\d{4}[a-z]?\.|\bet al\.?|10\.\d{4,}/',
                              re.IGNORECASE)


def citation_density(chunk):
    """Citation markers per 1000 chars in the chunk."""
    if not chunk:
        return 0.0
    return len(CITATION_MARKERS.findall(chunk)) / (len(chunk) / 1000)


def split_text(text):
    """Return (body, refs, method_dict)."""
    n = len(text)
    candidates = [m for m in HEAD_RE.finditer(text) if m.start() > 0.50 * n]
    # Try each candidate from the LAST backward; accept the first with dense tail.
    for m in reversed(candidates):
        pos = m.start()
        tail = text[m.end(): m.end() + 2500]
        dens = citation_density(tail)
        if dens >= 4.0 and len(text[pos:]) > 400:
            return (text[:pos].rstrip(), text[pos:].strip(),
                    {"references_split": "heading", "split_offset": pos,
                     "heading": m.group(1).strip(), "tail_density": round(dens, 1),
                     "refs_frac": round((n - pos) / n, 2)})
    return text, "", {"references_split": "none", "split_offset": None}


def main():
    BODY_DIR.mkdir(parents=True, exist_ok=True)
    REFS_DIR.mkdir(parents=True, exist_ok=True)
    report = {}
    split = nosplit = 0
    for txt in sorted(TEXT_DIR.glob("*.txt")):
        h = txt.stem
        text = txt.read_text(encoding="utf-8", errors="replace")
        body, refs, info = split_text(text)
        (BODY_DIR / f"{h}.txt").write_text(body, encoding="utf-8")
        (REFS_DIR / f"{h}.txt").write_text(refs, encoding="utf-8")
        report[h] = info
        if info["references_split"] == "heading":
            split += 1
        else:
            nosplit += 1
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Split {split + nosplit} texts: {split} with a references section, "
          f"{nosplit} kept whole (no confident split).")
    print(f"  body -> {BODY_DIR}")
    print(f"  refs -> {REFS_DIR}")
    print(f"  report -> {REPORT}")


if __name__ == "__main__":
    main()
