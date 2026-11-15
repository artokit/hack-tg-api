from docx.opc.exceptions import PackageNotFoundError

from models.rag import DocumentTooLarge, InvalidDocument
from repositories.rag_extract import extract_blocks


MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_CHARS = 12_000


def read_attachment_text(format: str, data: bytes) -> tuple[str, bool]:
    if format not in ("pdf", "docx", "txt", "md", "markdown"):
        raise InvalidDocument("unsupported_format")
    try:
        if format in ("pdf", "docx"):
            blocks = extract_blocks(data, format, include_images=False)
            text = "\n".join(block.text for block in blocks if block.text).strip()
        else:
            text = data.decode("utf-8-sig").strip()
            if "\x00" in text:
                raise InvalidDocument("invalid_file")
    except InvalidDocument as error:
        if str(error) == "document_too_large":
            raise DocumentTooLarge("document_too_large") from error
        raise
    except (ValueError, OSError, RuntimeError, PackageNotFoundError) as error:
        raise InvalidDocument("invalid_file") from error
    if not text:
        raise InvalidDocument("empty_document")
    return text[:MAX_ATTACHMENT_CHARS], len(text) > MAX_ATTACHMENT_CHARS
