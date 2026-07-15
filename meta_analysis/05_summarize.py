#!/usr/bin/env python3
"""
Step 5: Aggregate FISHFINDER analysis results into summary statistics.

Round-2 revision (Reviewer 1) changes:
  * Geographic scope is now enforced by an explicit, human-approved include/
    exclude list (paper_review.json), not the old automated NA-ratio heuristic.
  * The headline analysis runs on BODY text only (cache/results_body); names
    that appear solely in reference lists are tabulated separately and excluded.
  * Reports a TRUE globally-deduplicated distinct-species count, and relabels
    the previous per-paper sum as "name detections" (it is not a species count).

Reads cache/results_body/ (+ cache/results_refs/) and produces:
  - cache/summary.json (structured data)
  - cache/summary.md  (formatted report for manuscript insertion)
"""

import json
from collections import Counter
from config import (
    PAPERS_CACHE, RESULTS_BODY_DIR, RESULTS_REFS_DIR, PAPER_REVIEW,
    SUMMARY_FILE, SUMMARY_MD,
)

ISSUE_TYPES = ('outdated', 'misspelled')
SPECIES_TYPES = ('valid', 'changed', 'outdated', 'misspelled')


def load_papers():
    if not PAPERS_CACHE.exists():
        return {'papers': {}}
    with open(PAPERS_CACHE, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_results(results_dir):
    results = {}
    if not results_dir.exists():
        return results
    for f in results_dir.glob('*.json'):
        with open(f, 'r', encoding='utf-8') as fp:
            results[f.stem] = json.load(fp)
    return results


def build_paper_lookup(cache):
    """filename-hash -> paper metadata."""
    lookup = {}
    for paper in cache.get('papers', {}).values():
        pf = paper.get('pdf_file', '')
        if pf:
            lookup[pf] = paper
    return lookup


def load_review():
    if not PAPER_REVIEW.exists():
        return {}
    with open(PAPER_REVIEW, 'r', encoding='utf-8') as f:
        return json.load(f)


def canonical(detail):
    """Current valid name a detection resolves to (folds synonyms/misspellings)."""
    return (detail.get('suggestion') or detail.get('binomial') or '').strip()


def summarize():
    cache = load_papers()
    paper_lookup = build_paper_lookup(cache)
    review = load_review()
    body = load_results(RESULTS_BODY_DIR)
    refs = load_results(RESULTS_REFS_DIR)

    if not body:
        print('No body results found. Run steps 3b + 4 (--batch cache/texts_body) first.')
        return

    print(f'Summarizing {len(body)} analyzed papers against {len(review)} decisions.\n')

    # ── Apply the approved geographic include/exclude list, then drop papers
    #    in which FISHFINDER detected no scientific names in the body text — a
    #    paper that uses no binomials cannot be assessed for naming errors, and
    #    this also removes non-article content (wrong/corrupt PDFs). ──────────
    BINOMIAL_TYPES = ('valid', 'changed', 'outdated', 'misspelled', 'unknown')
    included, excluded_papers, excluded_no_names = {}, [], []
    for file_hash, result in body.items():
        meta = paper_lookup.get(file_hash, {})
        doi = meta.get('doi', '')
        dec = review.get(doi, {})
        if dec.get('decision') == 'exclude':
            excluded_papers.append({
                'file_hash': file_hash, 'doi': doi,
                'title': meta.get('title', 'Unknown'),
                'reason': dec.get('reason', 'excluded'),
            })
            continue
        cls = result.get('classifications', {})
        if sum(cls.get(t, 0) for t in BINOMIAL_TYPES) == 0:
            excluded_no_names.append({
                'file_hash': file_hash, 'doi': doi,
                'title': meta.get('title', 'Unknown'),
            })
            continue
        included[file_hash] = result

    print(f'Included: {len(included)}   Excluded (out-of-scope): {len(excluded_papers)}   '
          f'Excluded (no scientific names): {len(excluded_no_names)}')

    # ── Aggregate included body results ──────────────────────────────────────
    total_papers = len(included)
    papers_with_issues = papers_with_outdated = papers_with_misspelled = 0
    papers_with_changed = papers_with_unknown = 0
    total_detections = 0
    total_by_type = Counter()
    outdated_names, misspelled_names, changed_names = Counter(), Counter(), Counter()
    all_species = Counter()          # canonical name -> detection count (papers)
    distinct_species = set()         # globally deduplicated valid-species set
    journal_counts = Counter()
    paper_details = []

    for file_hash, result in included.items():
        meta = paper_lookup.get(file_hash, {})
        cls = result.get('classifications', {})
        details = result.get('details', [])
        total_detections += result.get('unique_binomials', 0)
        for dtype, count in cls.items():
            total_by_type[dtype] += count

        n_out, n_mis = cls.get('outdated', 0), cls.get('misspelled', 0)
        n_chg, n_unk = cls.get('changed', 0), cls.get('unknown', 0)
        has_issues = (n_out + n_mis) > 0
        papers_with_issues += has_issues
        papers_with_outdated += n_out > 0
        papers_with_misspelled += n_mis > 0
        papers_with_changed += n_chg > 0
        papers_with_unknown += n_unk > 0

        for d in details:
            dtype, binomial = d.get('type', ''), d.get('binomial', '')
            if dtype == 'outdated':
                outdated_names[binomial] += 1
            elif dtype == 'misspelled':
                misspelled_names[binomial] += 1
            elif dtype == 'changed':
                changed_names[binomial] += 1
            if dtype in SPECIES_TYPES:
                canon = canonical(d)
                all_species[canon] += 1
                distinct_species.add(canon.lower())

        journal = meta.get('journal', 'Unknown')
        journal_counts[journal] += 1
        paper_details.append({
            'file_hash': file_hash, 'doi': meta.get('doi', ''),
            'title': meta.get('title', 'Unknown'), 'year': meta.get('year', 0),
            'journal': journal, 'species_found': result.get('unique_binomials', 0),
            'outdated': n_out, 'misspelled': n_mis, 'changed': n_chg,
            'unknown': n_unk, 'has_issues': has_issues,
        })

    paper_details.sort(key=lambda p: p['outdated'] + p['misspelled'], reverse=True)

    # ── Reference-only errors (excluded from the headline) ───────────────────
    # For each INCLUDED paper, issue-names present in its reference list but NOT
    # in its body — these were formerly counted as author errors (Reviewer 1).
    ref_only_names = Counter()
    papers_with_ref_only = 0
    for file_hash in included:
        body_issue = {d['binomial'] for d in included[file_hash].get('details', [])
                      if d.get('type') in ISSUE_TYPES}
        refs_res = refs.get(file_hash, {})
        refs_issue = {d['binomial'] for d in refs_res.get('details', [])
                      if d.get('type') in ISSUE_TYPES}
        only = refs_issue - body_issue
        if only:
            papers_with_ref_only += 1
            for name in only:
                ref_only_names[name] += 1

    # ── Build summary ────────────────────────────────────────────────────────
    pct = lambda n: round(n / total_papers * 100, 1) if total_papers else 0
    n_common = total_by_type.get('common', 0)
    n_unknown = total_by_type.get('unknown', 0)

    summary = {
        'total_papers_analyzed': total_papers,
        'papers_excluded_non_na': len(excluded_papers),
        'papers_with_naming_errors': papers_with_issues,
        'papers_with_outdated_names': papers_with_outdated,
        'papers_with_misspelled_names': papers_with_misspelled,
        'papers_with_changed_names': papers_with_changed,
        'papers_with_unknown_names': papers_with_unknown,
        'pct_with_errors': pct(papers_with_issues),
        'pct_with_outdated': pct(papers_with_outdated),
        'pct_with_misspelled': pct(papers_with_misspelled),
        'pct_with_changed': pct(papers_with_changed),
        'pct_with_unknown': pct(papers_with_unknown),
        # Distinct valid species (globally deduplicated) — the defensible headline.
        'distinct_species': len(distinct_species),
        # The previous "unique species names" number: a SUM of per-paper counts
        # (double-counts species used in multiple papers; includes common/unknown).
        'total_name_detections': total_detections,
        'common_name_detections': n_common,
        'unknown_detections': n_unknown,
        'classification_totals': dict(total_by_type),
        'top_outdated_names': outdated_names.most_common(20),
        'top_misspelled_names': misspelled_names.most_common(20),
        'top_changed_names': changed_names.most_common(20),
        'top_species': all_species.most_common(30),
        'journals_represented': len(journal_counts),
        'top_journals': journal_counts.most_common(15),
        'top_issue_papers': paper_details[:10],
        'reference_only_error_names': ref_only_names.most_common(20),
        'n_papers_with_reference_only_errors': papers_with_ref_only,
        'papers_excluded_no_names': len(excluded_no_names),
        'excluded_no_names': excluded_no_names,
        'excluded_papers': excluded_papers,
    }

    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY_FILE, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f'Summary JSON written to {SUMMARY_FILE}')

    SUMMARY_MD.write_text(generate_markdown_report(summary), encoding='utf-8')
    print(f'Summary report written to {SUMMARY_MD}')

    # ── Highlights ───────────────────────────────────────────────────────────
    print(f'\n{"=" * 60}\nFISHFINDER Meta-Analysis Summary (round-2)\n{"=" * 60}')
    print(f'Papers analyzed (in scope):  {total_papers}')
    print(f'Papers excluded (out-of-scope): {len(excluded_papers)}')
    print(f'Papers excluded (no scientific names): {len(excluded_no_names)}')
    print(f'Papers with naming errors:   {papers_with_issues} ({pct(papers_with_issues)}%)')
    print(f'  - with outdated names:     {papers_with_outdated} ({pct(papers_with_outdated)}%)')
    print(f'  - with misspelled names:   {papers_with_misspelled} ({pct(papers_with_misspelled)}%)')
    print(f'Distinct species (dedup):    {len(distinct_species)}')
    print(f'Total name detections (sum): {total_detections}')
    print(f'Reference-only error names excluded: {sum(ref_only_names.values())} '
          f'across {papers_with_ref_only} papers')
    if outdated_names:
        print('\nTop outdated names:')
        for name, count in outdated_names.most_common(6):
            print(f'  {name}: {count}')
    if misspelled_names:
        print('\nTop misspellings:')
        for name, count in misspelled_names.most_common(6):
            print(f'  {name}: {count}')


def generate_markdown_report(s):
    L = [
        '# FISHFINDER Meta-Analysis: Fish Naming Errors in Recent Literature',
        '', '## Overview', '',
        f'We analyzed **{s["total_papers_analyzed"]}** recent open-access papers on '
        f'North American fish, retrieved from OpenAlex and filtered to English-language '
        f'articles. Each paper\'s study region was verified (title, abstract, methods) '
        f'and papers outside the *Names of Fishes* area (USA, Canada, Mexico) were '
        f'excluded; **{s["papers_excluded_non_na"]}** papers were removed on this basis, and '
        f'a further **{s["papers_excluded_no_names"]}** in which no scientific names were '
        f'detected in the body text (e.g. common-name-only studies, or non-article content) '
        f'were excluded as unassessable. Names appearing only in reference lists were '
        f'tabulated separately and excluded from error counts.',
        '', '## Key Findings', '',
        f'- **{s["pct_with_errors"]}%** of papers contained at least one naming error '
        f'(outdated synonym or misspelling)',
        f'- **{s["pct_with_outdated"]}%** used at least one outdated species name',
        f'- **{s["pct_with_misspelled"]}%** contained at least one misspelled species name',
        f'- **{s["pct_with_changed"]}%** referenced species whose names changed between '
        f'the 7th and 8th editions (not errors, but worth verifying)',
        f'- **{s["distinct_species"]}** distinct species (globally deduplicated) were '
        f'detected across all papers',
        f'- These arose from **{s["total_name_detections"]}** total name detections '
        f'(a paper-level sum; a species used in *n* papers counts *n* times, and this '
        f'figure also includes {s["common_name_detections"]} common-name and '
        f'{s["unknown_detections"]} unrecognized/out-of-scope detections)',
        '', '## Classification Breakdown', '',
        '| Classification | Detections | Description |',
        '|---------------|-------|-------------|',
    ]
    desc = {
        'valid': 'Exact match in Names of Fishes 8th edition',
        'changed': 'Valid but updated from 7th edition',
        'common': 'Matched via common name',
        'outdated': 'Pre-8th-edition synonym',
        'misspelled': 'Levenshtein distance 1-2 from a valid name',
        'unknown': 'Recognized genus, species not in the AFS list (often extralimital)',
    }
    for cls in ['valid', 'changed', 'common', 'outdated', 'misspelled', 'unknown']:
        L.append(f'| {cls.title()} | {s["classification_totals"].get(cls, 0)} | {desc[cls]} |')

    if s['top_outdated_names']:
        L += ['', '## Most Common Outdated Names', '', '| Outdated Name | Papers |',
              '|---------------|--------|']
        L += [f'| *{n}* | {c} |' for n, c in s['top_outdated_names'][:12]]
    if s['top_misspelled_names']:
        L += ['', '## Most Common Misspellings', '', '| Misspelled Name | Papers |',
              '|-----------------|--------|']
        L += [f'| *{n}* | {c} |' for n, c in s['top_misspelled_names'][:12]]
    if s['reference_only_error_names']:
        L += ['', '## Names Found Only in Reference Lists (Excluded)', '',
              f'{s["n_papers_with_reference_only_errors"]} papers contained '
              f'outdated/misspelled names that appeared **only** in cited reference '
              f'titles (not the authors\' own usage); these were excluded from the '
              f'error counts above.', '', '| Name (in references) | Papers |',
              '|----------------------|--------|']
        L += [f'| *{n}* | {c} |' for n, c in s['reference_only_error_names'][:12]]

    L += ['', '## Journals Represented', '',
          f'The analysis covered papers from **{s["journals_represented"]}** journals.', '']
    return '\n'.join(L)


if __name__ == '__main__':
    summarize()
