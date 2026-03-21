"""Quick diagnostic: compare pdfplumber vs PyMuPDF extraction on page 52."""
import sys
from pathlib import Path

PDF_PATH = Path(__file__).parent / "names_of_fishes" / "NAMES OF FISHES 8th.pdf"
PAGE_IDX = 51  # 0-indexed

try:
    import fitz
    print("=== PyMuPDF (fitz) ===")
    with fitz.open(str(PDF_PATH)) as pdf:
        page = pdf[PAGE_IDX]
        print(f"Page rotation: {page.rotation}")
        print(f"Page size: {page.rect.width:.1f} x {page.rect.height:.1f}")

        words = page.get_text("words")
        print(f"\nFirst 20 words (x0, y0, text):")
        for w in words[:20]:
            x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
            print(f"  x0={x0:6.1f}  y0={y0:6.1f}  text={repr(text)}")
except ImportError:
    print("pymupdf not available")

try:
    import pdfplumber
    print("\n=== pdfplumber ===")
    with pdfplumber.open(PDF_PATH) as pdf:
        page = pdf.pages[PAGE_IDX]
        words = page.extract_words(x_tolerance=3, y_tolerance=3)
        print(f"\nFirst 20 words (x0, top, text, reversed):")
        for w in words[:20]:
            rev = w['text'][::-1]
            print(f"  x0={w['x0']:6.1f}  top={w['top']:6.1f}  raw={repr(w['text']):30s}  rev={repr(rev)}")
except ImportError:
    print("pdfplumber not available")
