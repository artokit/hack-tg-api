from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID


BlockKind = Literal["text", "heading", "table_row", "visual", "scan"]
Rectangle = tuple[float, float, float, float]
RETIRED_VERSION_GRACE = timedelta(minutes=2)


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str = ""
    page: int | None = None
    box: Rectangle | None = None
    section: tuple[str, ...] = ()
    cells: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()
    table_id: str | None = None
    image: bytes | None = None
    label: str = ""
    identifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Chunk:
    blocks: tuple[int, ...]
    related: tuple[int, ...]


@dataclass(frozen=True)
class RagImport:
    id: UUID
    source_id: str
    title: str
    source_url: str | None
    format: str
    version: str
    resumed: bool
    file_id: UUID | None = None
    confluence_space_id: str | None = None
    confluence_version: int | None = None


class InvalidDocument(ValueError):
    pass


class DocumentTooLarge(InvalidDocument):
    pass


class RagDocumentNotFound(LookupError):
    pass


class RagUnavailable(RuntimeError):
    pass


class RagQueueUnavailable(RagUnavailable):
    pass
