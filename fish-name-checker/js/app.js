/**
 * Fish Name Checker — app.js
 * All processing is client-side. No server calls after initial JSON load.
 */
(function () {
  'use strict';

  // ── State ────────────────────────────────────────────────────────────────
  let db          = null;
  let validSet    = new Set();   // lowercase binomials → canonical form
  let validMap    = new Map();   // lowercase  → canonical cased binomial
  let synonymMap  = new Map();   // lowercase old name → canonical new name
  let generaSet   = new Set();   // lowercase genus strings
  let validList   = [];          // [{genus, species, binomial}] for fuzzy scan

  // ── DOM refs ─────────────────────────────────────────────────────────────
  const loadingEl      = document.getElementById('loading');
  const loadErrorEl    = document.getElementById('load-error');
  const checkBtn       = document.getElementById('check-btn');
  const clearBtn       = document.getElementById('clear-btn');
  const copyBtn        = document.getElementById('copy-btn');
  const textarea       = document.getElementById('manuscript-text');
  const resultsSection = document.getElementById('results-section');
  const highlightedEl  = document.getElementById('highlighted-text');
  const noIssuesEl     = document.getElementById('no-issues');
  const summaryTable   = document.getElementById('summary-table');
  const summaryTbody   = document.getElementById('summary-tbody');
  const issueBadge     = document.getElementById('issue-count');

  // ── Database loading ──────────────────────────────────────────────────────
  async function loadDatabase() {
    loadingEl.hidden   = false;
    loadErrorEl.hidden = true;
    checkBtn.disabled  = true;

    try {
      const resp = await fetch('data/fish_names.json');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      db = await resp.json();
    } catch (err) {
      loadingEl.hidden   = true;
      loadErrorEl.hidden = false;
      console.error('Failed to load fish_names.json:', err);
      return;
    }

    // Build lookup structures
    for (const [canonical, info] of Object.entries(db.valid_names)) {
      const lower = canonical.toLowerCase();
      validSet.add(lower);
      validMap.set(lower, canonical);

      const parts = canonical.split(' ');
      validList.push({
        genus:    parts[0],
        species:  parts.slice(1).join(' '),
        binomial: canonical,
        lGenus:   parts[0].toLowerCase(),
        lSpecies: parts.slice(1).join(' ').toLowerCase(),
      });
    }

    for (const [oldName, newName] of Object.entries(db.synonyms)) {
      synonymMap.set(oldName.toLowerCase(), newName);
    }

    for (const genus of db.genera) {
      generaSet.add(genus.toLowerCase());
    }

    loadingEl.hidden  = true;
    checkBtn.disabled = false;

    console.log(
      `Database loaded: ${validSet.size} valid names, ` +
      `${synonymMap.size} synonyms, ${generaSet.size} genera`
    );
  }

  // ── Levenshtein distance (Wagner-Fischer, with early-exit) ────────────────
  function levenshtein(a, b, maxDist) {
    if (Math.abs(a.length - b.length) > maxDist) return maxDist + 1;
    const m = a.length, n = b.length;
    // Use two rows
    let prev = new Uint16Array(n + 1);
    let curr = new Uint16Array(n + 1);
    for (let j = 0; j <= n; j++) prev[j] = j;

    for (let i = 1; i <= m; i++) {
      curr[0] = i;
      let rowMin = curr[0];
      for (let j = 1; j <= n; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        curr[j] = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost);
        if (curr[j] < rowMin) rowMin = curr[j];
      }
      if (rowMin > maxDist) return maxDist + 1; // prune
      [prev, curr] = [curr, prev];
    }
    return prev[n];
  }

  // ── Genus proximity check ──────────────────────────────────────────────────
  function isKnownGenus(genus) {
    const g = genus.toLowerCase();
    if (generaSet.has(g)) return true;
    if (g.length < 4) return false;
    for (const known of generaSet) {
      if (known[0] !== g[0]) continue;
      if (Math.abs(known.length - g.length) > 2) continue;
      if (levenshtein(g, known, 2) <= 2) return true;
    }
    return false;
  }

  // ── Find closest valid binomial ────────────────────────────────────────────
  function findClosestMatch(genus, species, maxDist) {
    const lg = genus.toLowerCase();
    const ls = species.toLowerCase();
    let bestDist   = maxDist + 1;
    let bestName   = null;

    for (const entry of validList) {
      // First-letter filter on genus (fast rejection)
      if (entry.lGenus[0] !== lg[0]) continue;
      // Length filter
      if (Math.abs(entry.lGenus.length  - lg.length) > maxDist) continue;

      const gd = levenshtein(lg, entry.lGenus, maxDist);
      if (gd > maxDist) continue;

      // First-letter filter on species
      if (entry.lSpecies[0] !== ls[0] &&
          Math.abs(entry.lSpecies.charCodeAt(0) - ls.charCodeAt(0)) > 2) continue;

      const sd = levenshtein(ls, entry.lSpecies, maxDist);
      const total = gd + sd;

      if (total < bestDist) {
        bestDist = total;
        bestName = entry.binomial;
        if (total === 0) break; // exact (shouldn't happen here but be safe)
      }
    }
    return bestName ? { name: bestName, dist: bestDist } : null;
  }

  // ── Classify a candidate binomial ──────────────────────────────────────────
  // Returns null if the name doesn't look like a fish name at all.
  function classifyName(genus, species) {
    const binomial = `${genus} ${species}`;
    const lower    = binomial.toLowerCase();

    // 1. Exact valid match
    if (validSet.has(lower)) {
      return { type: 'valid', canonical: validMap.get(lower), suggestion: null };
    }

    // 2. Known synonym / outdated name
    if (synonymMap.has(lower)) {
      return { type: 'outdated', canonical: binomial, suggestion: synonymMap.get(lower) };
    }

    // 3. Genus must be known (or close) — otherwise ignore as false positive
    if (!isKnownGenus(genus)) return null;

    // 4. Fuzzy match within edit distance 2
    const closest = findClosestMatch(genus, species, 2);
    if (closest && closest.dist <= 2) {
      return { type: 'misspelled', canonical: binomial, suggestion: closest.name };
    }

    // 5. Genus is fish-like but species has no close match
    return { type: 'unknown', canonical: binomial, suggestion: null };
  }

  // ── Extract candidate names from text ─────────────────────────────────────
  // Matches: Capitalized word (≥3 chars) followed by lowercase word (≥3 chars)
  // Optionally a second lowercase word (subspecies) is captured but the binomial
  // checked is always genus + species (first two words).
  const CANDIDATE_RE = /\b([A-Z][a-z]{2,})\s+([a-z]{2,})\b/g;

  function extractCandidates(text) {
    const hits = [];
    let m;
    CANDIDATE_RE.lastIndex = 0;
    while ((m = CANDIDATE_RE.exec(text)) !== null) {
      hits.push({
        genus:   m[1],
        species: m[2],
        text:    m[0],
        index:   m.index,
      });
    }
    return hits;
  }

  // ── HTML escaping ──────────────────────────────────────────────────────────
  function esc(str) {
    return str
      .replace(/&/g,  '&amp;')
      .replace(/</g,  '&lt;')
      .replace(/>/g,  '&gt;')
      .replace(/"/g,  '&quot;')
      .replace(/'/g,  '&#39;');
  }

  // ── Build highlighted HTML from findings ──────────────────────────────────
  function buildHighlightedHTML(text, findings) {
    if (!findings.length) return esc(text);

    // Sort by position
    findings.sort((a, b) => a.index - b.index);

    let html      = '';
    let lastIndex = 0;

    for (const f of findings) {
      // Text before this finding
      html += esc(text.slice(lastIndex, f.index));

      const title = f.suggestion ? `→ ${f.suggestion}` : f.type;
      html += `<span class="hl ${f.type}" title="${esc(title)}">${esc(f.text)}</span>`;

      lastIndex = f.index + f.text.length;
    }
    html += esc(text.slice(lastIndex));
    return html;
  }

  // ── Build corrected plain text (replace correctable names) ────────────────
  function buildCorrectedText(text, findings) {
    // Work backwards to preserve index positions
    const correctable = findings
      .filter(f => f.suggestion && (f.type === 'outdated' || f.type === 'misspelled'))
      .sort((a, b) => b.index - a.index);

    let out = text;
    for (const f of correctable) {
      out = out.slice(0, f.index) + f.suggestion + out.slice(f.index + f.text.length);
    }
    return out;
  }

  // ── Main check logic ───────────────────────────────────────────────────────
  function runCheck() {
    if (!db) return;

    const text = textarea.value;
    if (!text.trim()) {
      alert('Please paste some text to check.');
      return;
    }

    checkBtn.disabled    = true;
    checkBtn.textContent = 'Checking…';

    // Yield to browser to update button state, then process
    setTimeout(() => {
      const candidates = extractCandidates(text);
      const findings   = [];

      for (const cand of candidates) {
        const result = classifyName(cand.genus, cand.species);
        if (!result) continue;
        findings.push({
          text:       cand.text,
          binomial:   `${cand.genus} ${cand.species}`,
          index:      cand.index,
          type:       result.type,
          suggestion: result.suggestion,
        });
      }

      // ── Render highlighted preview
      highlightedEl.innerHTML = buildHighlightedHTML(text, findings);

      // ── Render summary table
      const issues = findings.filter(f => f.type !== 'valid');

      if (issues.length === 0) {
        noIssuesEl.hidden  = false;
        summaryTable.hidden = true;
        issueBadge.textContent = '';
      } else {
        noIssuesEl.hidden   = true;
        summaryTable.hidden = false;
        issueBadge.textContent = String(issues.length);

        // Deduplicate by binomial (keep first occurrence)
        const seen    = new Set();
        const deduped = [];
        for (const f of issues) {
          if (!seen.has(f.binomial)) {
            seen.add(f.binomial);
            deduped.push(f);
          }
        }

        const labels = {
          outdated:   'Outdated / Synonym',
          misspelled: 'Misspelled',
          unknown:    'Unknown fish name',
        };

        summaryTbody.innerHTML = '';
        for (const f of deduped) {
          const tr = document.createElement('tr');
          tr.innerHTML =
            `<td class="name-cell">${esc(f.binomial)}</td>` +
            `<td><span class="status-${f.type}">${labels[f.type] || f.type}</span></td>` +
            `<td>${f.suggestion ? `<em>${esc(f.suggestion)}</em>` : '—'}</td>`;
          summaryTbody.appendChild(tr);
        }
      }

      resultsSection.hidden = false;
      resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

      checkBtn.disabled    = false;
      checkBtn.textContent = 'Check Names';
    }, 10);
  }

  // ── Copy corrected text to clipboard ──────────────────────────────────────
  function copyText() {
    const text     = textarea.value;
    const findings = [];
    const cands    = extractCandidates(text);

    for (const cand of cands) {
      const result = classifyName(cand.genus, cand.species);
      if (!result) continue;
      findings.push({
        text:       cand.text,
        index:      cand.index,
        type:       result.type,
        suggestion: result.suggestion,
      });
    }

    const corrected = buildCorrectedText(text, findings);
    navigator.clipboard.writeText(corrected).then(() => {
      const prev = copyBtn.textContent;
      copyBtn.textContent = 'Copied!';
      setTimeout(() => { copyBtn.textContent = prev; }, 2000);
    }).catch(() => {
      // Fallback for browsers without clipboard API
      const ta = document.createElement('textarea');
      ta.value = corrected;
      ta.style.position = 'fixed';
      ta.style.opacity  = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      copyBtn.textContent = 'Copied!';
      setTimeout(() => { copyBtn.textContent = 'Copy corrected text'; }, 2000);
    });
  }

  // ── Event listeners ────────────────────────────────────────────────────────
  checkBtn.addEventListener('click', runCheck);

  clearBtn.addEventListener('click', () => {
    textarea.value        = '';
    resultsSection.hidden = true;
  });

  copyBtn.addEventListener('click', copyText);

  // Allow Ctrl/Cmd+Enter to trigger check
  textarea.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') runCheck();
  });

  // ── Bootstrap ─────────────────────────────────────────────────────────────
  loadDatabase();
}());
