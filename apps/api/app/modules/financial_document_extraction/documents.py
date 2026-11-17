import warnings
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.modules.financial_document_extraction.exceptions import (
    DocumentComplexityError,
    DocumentExtractionError,
    DocumentTooLargeError,
    UnsupportedDocumentError,
)

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_PDF_PAGES = 20


def validate_document(data: bytes) -> str:
    if not data:
        raise DocumentExtractionError()
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLargeError()
    if data.startswith(b"%PDF-"):
        try:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise DocumentComplexityError()
            if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
                raise DocumentComplexityError()
            for page in reader.pages:
                if page.mediabox.width <= 0 or page.mediabox.height <= 0:
                    raise DocumentExtractionError()
        except (
            PyPdfError,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            RecursionError,
        ) as exc:
            raise DocumentExtractionError() from exc
        return "application/pdf"
    if not data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
        raise UnsupportedDocumentError()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in ("PNG", "JPEG"):
                    raise UnsupportedDocumentError()
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise DocumentComplexityError()
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
                return "image/png" if image.format == "PNG" else "image/jpeg"
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise DocumentComplexityError() from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise DocumentExtractionError() from exc
