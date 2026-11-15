from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from urllib.parse import quote


GITHUB_REPOSITORY = "skyywhyy/barsdocs"
GITHUB_BRANCH = "main"
GITHUB_SOURCE_PREFIX = "github:"


@dataclass(frozen=True)
class GithubDocument:
    path: str
    commit: str
    revision: str
    format: str
    size_bytes: int

    @property
    def source_id(self) -> str:
        key = f"{GITHUB_REPOSITORY}:{GITHUB_BRANCH}:{self.path}"
        return GITHUB_SOURCE_PREFIX + sha256(key.encode()).hexdigest()

    @property
    def title(self) -> str:
        return PurePosixPath(self.path).name[:250]

    @property
    def url(self) -> str:
        return f"https://github.com/{GITHUB_REPOSITORY}/blob/{self.commit}/{quote(self.path)}"
