import asyncio
import hmac
import logging

from models.github import GITHUB_BRANCH, GITHUB_REPOSITORY
from models.rag import RagUnavailable
from repositories.github import GithubRepository, GithubSyncRepository
from schemas.github import GithubDelivery


log = logging.getLogger(__name__)


class GithubService:
    def __init__(self, github: GithubRepository, sync: GithubSyncRepository, secret: str):
        self.github = github
        self.sync = sync
        self.secret = secret.encode()

    def verify(self, body: bytes | bytearray, signature: str) -> bool:
        digest = hmac.digest(self.secret, body, "sha256").hex()
        return hmac.compare_digest(f"sha256={digest}".encode(), signature.encode())

    async def accept(self, event: str, delivery: GithubDelivery) -> bool:
        if delivery.repository.full_name.casefold() != GITHUB_REPOSITORY:
            return False
        if event != "ping" and (delivery.ref != f"refs/heads/{GITHUB_BRANCH}" or delivery.deleted):
            return False
        await self.sync.request()
        return True

    async def sync_pending(self) -> None:
        request_id = await self.sync.pending()
        if request_id is None:
            return
        try:
            async with asyncio.timeout(30):
                documents = await self.github.snapshot()
        except (RagUnavailable, TimeoutError) as error:
            log.warning("GitHub RAG sync %s delayed (%s)", request_id, str(error) or "github_timeout")
            await self.sync.retry(request_id)
            return
        enqueued = await self.sync.reconcile(request_id, documents)
        log.info("GitHub RAG sync %s queued %d of %d documents", request_id, enqueued, len(documents))
