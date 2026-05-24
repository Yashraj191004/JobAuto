"""Extract plain text from your resume PDF; cache the result as resume.txt."""
from __future__ import annotations
from .config import RESUME_PDF, RESUME_TXT


def get_resume_text() -> str:
    """Return the resume as plain text.

    If `knowledge/resume.txt` exists and is at least as fresh as the source PDF
    (or there is no PDF), use the cached text. Otherwise extract from the PDF
    via pypdf, cache the result, and return it.
    """
    if RESUME_TXT.exists() and (
        not RESUME_PDF.exists()
        or RESUME_TXT.stat().st_mtime >= RESUME_PDF.stat().st_mtime
    ):
        return RESUME_TXT.read_text()
    if not RESUME_PDF.exists():
        raise FileNotFoundError(f"Drop your resume PDF at: {RESUME_PDF}")
    from pypdf import PdfReader

    reader = PdfReader(str(RESUME_PDF))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    RESUME_TXT.write_text(text)
    return text
