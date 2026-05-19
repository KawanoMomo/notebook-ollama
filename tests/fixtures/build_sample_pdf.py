"""Run once to create tests/fixtures/sample.pdf."""
from pathlib import Path

import pymupdf

def main() -> None:
    out = Path(__file__).parent / "sample.pdf"
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Chapter One\n\nThis is page one body text.")
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Chapter Two\n\nThis is page two body text.")
    doc.save(str(out))

if __name__ == "__main__":
    main()
