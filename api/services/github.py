import asyncio
import logging

from models.rag import RagUnavailable
from repositories.github import GithubRepository, GithubSyncRepository


log = logging.getLogger(__name__)


class GithubService:
    def __init__(self, github: GithubRepository, sync: GithubSyncRepository):
        self.github = github
        self.sync = sync

    async def request_sync(self) -> None:
        await self.sync.request()

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
