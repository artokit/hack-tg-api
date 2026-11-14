from dataclasses import dataclass


@dataclass
class FileResponse:
    id: str
    name: str
    extension: str | None
    url: str
