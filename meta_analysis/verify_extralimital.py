#!/usr/bin/env python3
"""
verify_extralimital.py — Round-2 revision (Reviewer 1).

For each "outdated" name flagged by the meta-analysis, decide whether it is a
LEGITIMATE outdated name (a genuine junior synonym / genus transfer of the AFS
target) or a spurious mapping of a DISTINCT valid species (the extralimital
false-synonym bug Reviewer 1 identified).

Method (per flagged old_name -> target):
  1. Query Eschmeyer's Catalog for old_name and read the species-level
     "Current status:" line(s).
       - "Valid as <target>" or "Synonym of <target>"          -> KEEP
       - "Valid as <old_name>" (valid as itself)               -> REMOVE
       - "Valid as/Synonym of <third species>" (!= target)     -> REVIEW
  2. If old_name does not resolve under its (old) genus (Eschmeyer files names
     under the ORIGINAL genus, so later combinations like Stizostedion vitreum
     return an empty page), fall back to eschmeyer_cache.json: if old_name is a
     synonym of target there, the original scrape legitimately linked them -> KEEP.
       - otherwise -> REVIEW.

REMOVE names are written to extralimital_valids.json (repo root), consumed by
the corrected safety filter in scrape_eschmeyer.py / rescrape_transfers.py.
REVIEW names are surfaced for manual (taxonomist) confirmation.

Usage:
  uv run --with requests --with beautifulsoup4 python verify_extralimital.py [--names "Genus sp,Genus sp"]
"""
import json
import re
import sys
import time
import glob
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
import scrape_eschmeyer as esch  # noqa: E402

CACHE_RESULTS = HERE / "cache" / "results"
ESCH_CACHE = ROOT / "eschmeyer_cache.json"
DIAG_OUT = HERE / "cache" / "extralimital_check.json"
REMOVE_OUT = ROOT / "extralimital_valids.json"

STATUS_RE = re.compile(
    r'Current status:\s*(Valid as|Synonym of|Uncertain as)\s+([A-Z][a-z]+ [a-z]+)')


def flagged_outdated():
    mapping = {}
    for fp in glob.glob(str(CACHE_RESULTS / "*.json")):
        d = json.load(open(fp, encoding="utf-8"))
        for det in d.get("details", []):
            if det.get("type") == "outdated":
                mapping[det["binomial"]] = det.get("suggestion")
    return dict(sorted(mapping.items()))


def norm(s):
    return " ".join((s or "").split()).strip()


def page_statuses(html):
    text = re.sub(r'\s+', ' ', BeautifulSoup(html, "html.parser").get_text(separator=" "))
    text = re.sub(r'\s+,', ',', text)
    valid_as, synonym_of, uncertain = [], [], []
    for kind, binom in STATUS_RE.findall(text):
        b = norm(binom)
        if kind == "Valid as":
            valid_as.append(b)
        elif kind == "Synonym of":
            synonym_of.append(b)
        else:
            uncertain.append(b)
    return valid_as, synonym_of, uncertain, len(text)


def classify(old_name, target, valid_as, synonym_of, uncertain, cache):
    o, t = norm(old_name), norm(target)
    resolved = valid_as + synonym_of
    if t in resolved:
        return "KEEP", f"Eschmeyer: old_name resolves to target ({t})"
    if o in valid_as:
        return "REMOVE", f"valid as itself ({o}); distinct species, not a synonym of {t}"
    if resolved:
        return "REMOVE", f"Eschmeyer resolves old_name to '{resolved[0]}', not target '{t}'"
    if o in uncertain:
        return "REVIEW", f"Eschmeyer 'Uncertain as {o}'"
    # No species-level status parsed (later combination filed under original genus).
    syns = cache.get(t, {}).get("synonyms", []) if cache else []
    if o in syns:
        return "KEEP", "no direct record; original scrape lists old_name as synonym of target"
    return "REVIEW", "no Eschmeyer status and not in target's cached synonyms"


def main():
    names_arg = None
    if "--names" in sys.argv:
        names_arg = sys.argv[sys.argv.index("--names") + 1]

    mapping = flagged_outdated()
    if names_arg:
        want = {norm(n) for n in names_arg.split(",")}
        mapping = {k: v for k, v in mapping.items() if norm(k) in want}

    cache = json.load(open(ESCH_CACHE, encoding="utf-8")) if ESCH_CACHE.exists() else {}
    print(f"Verifying {len(mapping)} flagged outdated names against Eschmeyer "
          f"(cache: {len(cache)} entries)...\n")

    session = requests.Session()
    diag = {}
    for i, (old_name, target) in enumerate(mapping.items(), 1):
        genus, _, species = old_name.partition(" ")
        html = esch.fetch_species(genus, species, session)
        if html is None:
            va = so = un = []
            plen = 0
            verdict, note = "REVIEW", "fetch failed"
        else:
            va, so, un, plen = page_statuses(html)
            verdict, note = classify(old_name, target, va, so, un, cache)
        diag[old_name] = {
            "target": target, "verdict": verdict, "note": note,
            "valid_as": va, "synonym_of": so, "uncertain_as": un, "page_len": plen,
        }
        vshow = (va + so) or (["(none)"])
        print(f"[{i:2d}/{len(mapping)}] {verdict:6s}  {old_name:28s} -> {target:26s} | Eschmeyer: {', '.join(vshow)[:45]}")
        time.sleep(esch.DELAY)
        if i % esch.PAUSE_EVERY == 0:
            time.sleep(esch.PAUSE_SECS)

    DIAG_OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(diag, open(DIAG_OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    remove = {k: v for k, v in diag.items() if v["verdict"] == "REMOVE"}
    review = {k: v for k, v in diag.items() if v["verdict"] == "REVIEW"}
    keep = {k: v for k, v in diag.items() if v["verdict"] == "KEEP"}
    if not names_arg:
        json.dump(remove, open(REMOVE_OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    print(f"\n=== SUMMARY ===  KEEP: {len(keep)}  REMOVE: {len(remove)}  REVIEW: {len(review)}")
    if remove:
        print("\nREMOVE (distinct valid species wrongly mapped as synonyms):")
        for k, v in remove.items():
            print(f"  {k:28s} (mapped -> {v['target']}) | {v['note']}")
    if review:
        print("\nREVIEW (needs taxonomist confirmation):")
        for k, v in review.items():
            print(f"  {k:28s} (mapped -> {v['target']}) | valid_as={v['valid_as']} syn_of={v['synonym_of']} | {v['note']}")
    print(f"\nDiagnostic: {DIAG_OUT}")
    if not names_arg:
        print(f"Remove list: {REMOVE_OUT}  ({len(remove)} names)")


if __name__ == "__main__":
    main()
