from pydantic import BaseModel


class GithubWebhookRepository(BaseModel):
    full_name: str


class GithubDelivery(BaseModel):
    repository: GithubWebhookRepository
    ref: str | None = None
    deleted: bool = False
