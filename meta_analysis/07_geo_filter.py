#!/usr/bin/env python3
"""
Step 7 (round-2 revision): rank analyzed papers by how likely their STUDY REGION
is outside North America, to strengthen the non-NA filter Reviewer 1 flagged.

The only geographic gate at discovery time is author-institution country, which
is a weak proxy (a US-based coauthor on a European study passes). Here we mine
the paper's own text — title, abstract, author affiliations, and study-area /
methods statements — for geographic cues, and combine that with the existing
`unknown`-species signal (non-AFS congeners ⇒ likely non-NA fauna).

Output: cache/geo_review.csv, ranked most-likely-non-NA first. This is a WORKLIST:
Claude reads the flagged papers' text and proposes an include/exclude decision
per paper; the user approves; decisions are recorded in paper_review.json.

Study region is judged relative to the Names of Fishes area = USA + Canada +
Mexico. Central America (Guatemala southward), the Caribbean, and everywhere else
count as non-NA.

Usage:  uv run python 07_geo_filter.py
"""
import csv
import json
import re
import glob
from pathlib import Path
from config import PAPERS_CACHE, RESULTS_DIR, TEXT_DIR, CACHE_DIR

# ── Gazetteers ────────────────────────────────────────────────────────────────
US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Idaho", "Illinois", "Indiana",
    "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
    "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
    "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
    "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
    "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
    "Washington", "West Virginia", "Wisconsin", "Wyoming",
]  # 'Georgia' omitted (collides with the country)
NA_OTHER = [
    "United States", "U.S.", "U.S.A", "USA", "North America", "North American",
    "Canada", "Canadian", "Ontario", "Quebec", "British Columbia", "Alberta",
    "Manitoba", "Saskatchewan", "Nova Scotia", "New Brunswick", "Newfoundland",
    "Labrador", "Yukon", "Nunavut", "Mexico", "Mexican", "Sonora", "Chihuahua",
    "Baja California", "Jalisco", "Veracruz", "Yucatan", "Oaxaca", "Chiapas",
    "Tamaulipas", "Sinaloa", "Great Lakes", "Lake Superior", "Lake Michigan",
    "Lake Huron", "Lake Erie", "Lake Ontario", "Mississippi River", "Missouri River",
    "Ohio River", "Colorado River", "Rio Grande", "Columbia River", "Chesapeake",
    "Gulf of Mexico", "Appalachian", "Appalachia", "Sonoran", "Chihuahuan",
    "Puget Sound", "Everglades", "Laurentian", "Great Plains",
]
NA_TERMS = US_STATES + NA_OTHER

FOREIGN = [
    # Europe
    "United Kingdom", "England", "Scotland", "Wales", "Ireland", "France", "Spain",
    "Portugal", "Italy", "Germany", "Netherlands", "Belgium", "Switzerland",
    "Austria", "Poland", "Czech", "Slovakia", "Hungary", "Romania", "Bulgaria",
    "Greece", "Turkey", "Turkish", "Serbia", "Croatia", "Slovenia", "Bosnia",
    "Ukraine", "Russia", "Russian", "Belarus", "Lithuania", "Latvia", "Estonia",
    "Finland", "Sweden", "Norway", "Denmark", "Iceland", "Moldova", "Albania",
    "Europe", "European", "Mediterranean", "Adriatic", "Aegean", "Baltic",
    "Black Sea", "North Sea", "Iberian", "Balkan", "Danube", "Rhine", "Elbe",
    "Rhone", "Ebro", "Volga", "Dnieper", "Thames", "Vistula",
    # Africa
    "Africa", "African", "Nigeria", "Egypt", "Kenya", "Tanzania", "Uganda",
    "Ethiopia", "Ghana", "Morocco", "Algeria", "Tunisia", "South Africa",
    "Zimbabwe", "Zambia", "Mozambique", "Angola", "Cameroon", "Senegal",
    "Congo", "Sudan", "Libya", "Malawi", "Lake Victoria", "Lake Tanganyika",
    "Lake Malawi", "Zambezi", "Sahara", "Sahel",
    # Asia
    "China", "Chinese", "India", "Japan", "Japanese", "Korea", "Korean",
    "Vietnam", "Thailand", "Thai", "Indonesia", "Malaysia", "Philippines",
    "Bangladesh", "Pakistan", "Sri Lanka", "Myanmar", "Cambodia", "Laos",
    "Nepal", "Iran", "Iraq", "Saudi Arabia", "Israel", "Lebanon", "Syria",
    "Yemen", "Oman", "Qatar", "Kuwait", "Taiwan", "Mongolia", "Kazakhstan",
    "Yangtze", "Mekong", "Ganges", "Brahmaputra", "Indus", "Yellow River",
    "South China Sea", "Persian Gulf", "Arabian", "Bay of Bengal", "Indo-Pacific",
    # South & Central America / Caribbean (extralimital to Names of Fishes)
    "South America", "South American", "Brazil", "Brazilian", "Argentina",
    "Chile", "Peru", "Colombia", "Venezuela", "Ecuador", "Bolivia", "Paraguay",
    "Uruguay", "Guyana", "Suriname", "French Guiana", "Amazon", "Amazonian",
    "Orinoco", "Parana", "Patagonia", "Andes", "Andean", "Neotropical",
    "Guatemala", "Belize", "Honduras", "El Salvador", "Nicaragua", "Costa Rica",
    "Panama", "Cuba", "Jamaica", "Haiti", "Dominican Republic", "Puerto Rico",
    "Trinidad",
    # Oceania / poles
    "Australia", "Australian", "New Zealand", "Great Barrier Reef", "Tasmania",
    "Fiji", "Papua New Guinea", "Coral Sea", "Antarctic", "Antarctica",
]
# Note: 'Jordan', bare 'Indian'/'Asian' deliberately omitted — collide with the
# ichthyologist D.S. Jordan, "Indian reservation/Creek", and "Asian carp" (a US
# invasive), which would create false non-NA hits.

STUDY_KW = [
    "study area", "study site", "study region", "sampling", "sampled",
    "was conducted", "were conducted", "located in", "located at",
    "collected from", "collected in", "fish were", "we sampled", "sites in",
    "river basin", "watershed", "reservoir", "catchment", "lagoon", "estuary",
]


def compile_gaz(terms):
    pat = "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True))
    return re.compile(r"\b(" + pat + r")\b", re.IGNORECASE)


NA_RE = compile_gaz(NA_TERMS)
FOREIGN_RE = compile_gaz(FOREIGN)


def geo_text(text):
    """Title/abstract/affiliation header + windows around study-area statements.
    Avoids the reference list (full of foreign place names in citations)."""
    low = text.lower()
    windows = [text[:2800]]  # title, authors, affiliations, abstract
    for kw in STUDY_KW:
        start = 0
        while len(windows) < 80:
            idx = low.find(kw, start)
            if idx < 0:
                break
            windows.append(text[max(0, idx - 200):idx + 320])
            start = idx + len(kw)
    return " ".join(windows)


def hits(regex, s):
    found = [m.group(0) for m in regex.finditer(s)]
    uniq = sorted(set(x.title() for x in found))
    return len(found), uniq


def main():
    cache = json.load(open(PAPERS_CACHE, encoding="utf-8"))
    lookup = {p["pdf_file"]: p for p in cache.get("papers", {}).values() if p.get("pdf_file")}

    rows = []
    for fp in glob.glob(str(RESULTS_DIR / "*.json")):
        h = Path(fp).stem
        res = json.load(open(fp, encoding="utf-8"))
        meta = lookup.get(h, {})
        cls = res.get("classifications", {})
        n_unknown = cls.get("unknown", 0)
        na_types = ("valid", "changed", "outdated", "misspelled")
        n_afs = sum(cls.get(t, 0) for t in na_types)
        unk_ratio = round(n_unknown / (n_afs + n_unknown), 2) if (n_afs + n_unknown) else 0.0
        unknown_sp = [d["binomial"] for d in res.get("details", []) if d.get("type") == "unknown"]

        txt_path = TEXT_DIR / f"{h}.txt"
        gtext = geo_text(txt_path.read_text(encoding="utf-8", errors="replace")) if txt_path.exists() else ""
        title = meta.get("title", "") or ""
        blob = title + "\n" + gtext
        na_n, na_terms = hits(NA_RE, blob)
        fr_n, fr_terms = hits(FOREIGN_RE, blob)

        # Suspicion score: foreign lean + unknown-fauna signal, minus NA anchoring.
        score = fr_n - na_n + (4 if unk_ratio >= 0.5 and n_unknown >= 4 else
                               2 if unk_ratio >= 0.35 and n_unknown >= 3 else 0)
        flag = "non-NA?" if (fr_n > 0 and na_n == 0) or score >= 3 else \
               "check" if fr_n > na_n or (unk_ratio >= 0.4 and n_unknown >= 3) else "NA"

        rows.append({
            "hash": h, "flag": flag, "score": score,
            "doi": meta.get("doi", ""), "journal": (meta.get("journal", "") or "")[:40],
            "title": title[:90],
            "na_hits": na_n, "foreign_hits": fr_n,
            "unknown_ratio": unk_ratio, "n_unknown": n_unknown,
            "foreign_terms": "; ".join(fr_terms[:8]),
            "na_terms": "; ".join(na_terms[:6]),
            "top_unknown_species": "; ".join(unknown_sp[:6]),
        })

    rows.sort(key=lambda r: (r["flag"] != "non-NA?", r["flag"] != "check", -r["score"], -r["foreign_hits"]))
    out = CACHE_DIR / "geo_review.csv"
    cols = ["hash", "flag", "score", "doi", "journal", "title", "na_hits",
            "foreign_hits", "unknown_ratio", "n_unknown", "foreign_terms",
            "na_terms", "top_unknown_species"]
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    tally = Counter(r["flag"] for r in rows)
    print(f"Wrote {out}  ({len(rows)} papers)")
    print(f"Flags: {dict(tally)}")
    print(f"\nMost-likely non-NA (top 25):")
    print(f"{'flag':8s} {'sc':>3s} {'fr':>3s} {'na':>3s} {'unk%':>5s} {'journal':40s} title")
    for r in rows[:25]:
        print(f"{r['flag']:8s} {r['score']:3d} {r['foreign_hits']:3d} {r['na_hits']:3d} "
              f"{r['unknown_ratio']:5.2f} {r['journal']:40s} {r['title'][:70]}")


if __name__ == "__main__":
    main()
