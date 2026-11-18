
"""Extract readable text and locations from TXT, PDF, and DOCX documents."""

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB
MAX_EXTRACTED_CHARS = 50_000

SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}

LOCATION_LABELS = {"GPE", "LOC", "FAC"}


def extract_document_text(filename: str, content: bytes) -> str:
    """Extract readable text from a supported document."""

    extension = Path(filename).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            "Unsupported file type. Please upload TXT, PDF, or DOCX."
        )

    if not content:
        raise ValueError("The uploaded file is empty.")

    if len(content) > MAX_FILE_SIZE:
        raise ValueError("File size exceeds the 15 MB limit.")

    try:
        if extension == ".txt":
            text = _extract_txt(content)
        elif extension == ".pdf":
            text = _extract_pdf(content)
        else:
            text = _extract_docx(content)

    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"Could not read the document: {exc}"
        ) from exc

    text = text.strip()

    if not text:
        raise ValueError(
            "No readable text was found in this document."
        )

    return text[:MAX_EXTRACTED_CHARS]


def extract_locations(text: str) -> list[str]:
    """
    Detect geographical locations using spaCy named entity recognition.

    Detects entities labelled GPE, LOC, and FAC.
    Returns unique location names while preserving their original order.
    """

    if not text or not text.strip():
        return []

    try:
        nlp = _load_location_model()
        doc = nlp(text[:MAX_EXTRACTED_CHARS])

    except Exception:
        # Document upload should still work if the NLP model
        # is unavailable. In that case, no locations are returned.
        return []

    locations = []
    seen = set()

    for entity in doc.ents:
        if entity.label_ not in LOCATION_LABELS:
            continue

        location = " ".join(entity.text.split()).strip()

        if not location:
            continue

        normalized = location.casefold()

        if normalized not in seen:
            seen.add(normalized)
            locations.append(location)

    return locations


@lru_cache(maxsize=1)
def _load_location_model():
    """Load the English spaCy model once and reuse it."""

    import spacy

    return spacy.load("en_core_web_sm")


def _extract_txt(content: bytes) -> str:
    """Decode a UTF-8 text file."""

    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "TXT file must use UTF-8 encoding."
        ) from exc


def _extract_pdf(content: bytes) -> str:
    """Extract text from every page of a PDF."""

    reader = PdfReader(BytesIO(content))

    if reader.is_encrypted:
        raise ValueError(
            "Password-protected PDFs are not supported."
        )

    pages = []

    for page in reader.pages:
        pages.append(page.extract_text() or "")

    return "\n".join(pages)


def _extract_docx(content: bytes) -> str:
    """Extract paragraphs and table content from a DOCX file."""

    document = Document(BytesIO(content))
    parts = []

    for paragraph in document.paragraphs:
        if paragraph.text.strip():
            parts.append(paragraph.text)

    for table in document.tables:
        for row in table.rows:
            cells = [
                cell.text.strip()
                for cell in row.cells
                if cell.text.strip()
            ]

            if cells:
                parts.append(" | ".join(cells))

    return "\n".join(parts)
