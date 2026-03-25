"""Show lines with dot leaders that the parser is currently rejecting."""
import re
from pathlib import Path
import fitz

PDF = Path(__file__).parent / "names_of_fishes" / "Names-of-Fishes-8-Table1.pdf"

HAS_DOTS_RE = re.compile(r'\.{4,}')
GENUS_RE    = re.compile(r'^[A-Z][a-z]{2,}$')
SPECIES_RE  = re.compile(r'^[a-z]{3,}$')
SKIP_RE = re.compile(
    r'^\d+$|^NAMES OF FISHES$|^SCIENTIFIC NAME|^\s*OCCURRENCE|^COMMON NAME'
    r'|^TABLE\s+1\.|^A\s*=|^[*^]\s+indicates|^Common names'
    r'|^the exclusive|^added to the|^in French|^En-,\s*Sp-'
)

rejected = []

with fitz.open(str(PDF)) as pdf:
    for page_idx in range(1, len(pdf)):
        for line in pdf[page_idx].get_text("text").splitlines():
            stripped = line.strip()
            if not stripped or SKIP_RE.match(stripped):
                continue
            if not HAS_DOTS_RE.search(line):
                continue

            # This line has dots — try to parse it
            parts = re.split(r'\.{2,}', line)
            col0 = parts[0]
            text = col0.lstrip('\t ')
            flag_m = re.match(r'^([*^&+]+)\s*', text)
            if flag_m:
                text = text[flag_m.end():]
            text = text.strip()
            tokens = text.split()

            reason = None
            if len(parts) < 2:
                reason = "fewer than 2 dot-separated parts"
            elif len(tokens) < 3:
                reason = f"fewer than 3 tokens in name col: {repr(text)}"
            elif not GENUS_RE.match(tokens[0]):
                reason = f"genus fails regex: {repr(tokens[0])}"
            elif not SPECIES_RE.match(tokens[1].rstrip('.,')):
                reason = f"epithet fails regex: {repr(tokens[1])}"
            elif not re.match(r'^[APFarCMU]', re.sub(r'\s+', '', parts[1])):
                reason = f"bad occurrence: {repr(parts[1].strip())}"

            if reason:
                rejected.append((page_idx + 1, reason, line.strip()[:120]))

print(f"Total rejected dot-lines: {len(rejected)}\n")
# Group by reason
from collections import Counter
counts = Counter(r for _, r, _ in rejected)
for reason, n in counts.most_common():
    print(f"  {n:4d}  {reason}")

print("\nFirst 30 rejected lines:")
for page, reason, line in rejected[:30]:
    print(f"  p{page:3d}  [{reason}]")
    print(f"         {line}")
