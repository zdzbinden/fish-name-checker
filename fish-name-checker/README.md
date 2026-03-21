# Fish Name Checker

A static web app that validates scientific fish names in manuscript text against
*Common and Scientific Names of Fishes from the United States, Canada, and Mexico*,
8th edition (Page et al., 2023), published by the American Fisheries Society (AFS)
and the American Society of Ichthyologists and Herpetologists (ASIH).

**Scientific names only** — common names are not checked.

---

## How to use

1. Visit the deployed URL (GitHub Pages).
2. Paste your manuscript text into the text box.
3. Click **Check Names** (or press Ctrl/⌘+Enter).
4. Review the highlighted preview and the issues table.
5. Click **Copy corrected text** to copy the text with outdated/misspelled names
   automatically replaced by the suggested corrections.

### Color coding

| Color  | Meaning |
|--------|---------|
| Green  | Valid — exact match in the 8th edition |
| Orange | Outdated or synonym — replaced by a different name in the 8th edition |
| Red    | Misspelled — close match found; check the suggestion |
| Purple | Unknown — genus looks fish-like but no close species match |

---

## Running locally

The app loads `data/fish_names.json` via `fetch()`, so it must be served over HTTP
(opening `index.html` directly as a `file://` URL will fail in most browsers).

```bash
cd fish-name-checker
python -m http.server 8080
# then open http://localhost:8080
```

---

## Updating the data (new edition)

When a new edition of *Names of Fishes* is published:

1. Replace `../names_of_fishes/NAMES OF FISHES 8th.pdf` with the new PDF.
2. Update the page-range constants at the top of `parse_pdf.py`
   (`SPECIES_START`, `SPECIES_END`, `APPENDIX_START`, `APPENDIX_END`) to match
   the new edition's layout.
3. Re-run the parser:

```bash
pip install pdfplumber   # first time only
python ../parse_pdf.py
```

4. Commit and push `data/fish_names.json`.

---

## GitHub Pages deployment

1. Push the repository to GitHub.
2. Go to **Settings → Pages**, set Source to the branch and `/ (root)` or the
   `fish-name-checker/` folder, depending on your repo layout.
3. The `.nojekyll` file in this directory prevents GitHub Pages from running
   Jekyll, which would interfere with the `data/` directory.

---

## Citation

Page, L. M., H. Espinosa-Pérez, L. T. Findley, C. R. Gilbert, R. N. Lea,
N. E. Mandrak, R. L. Mayden, and J. S. Nelson. 2023.
*Common and Scientific Names of Fishes from the United States, Canada, and Mexico*,
8th edition. American Fisheries Society, Special Publication 36, Bethesda, Maryland.
