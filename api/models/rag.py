from dataclasses import dataclass
from typing import Literal
from uuid import UUID


BlockKind = Literal["text", "heading", "table_row", "visual", "scan"]
Rectangle = tuple[float, float, float, float]


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


class InvalidDocument(ValueError):
    pass


class RagUnavailable(RuntimeError):
    pass


class RagQueueUnavailable(RagUnavailable):
    pass
