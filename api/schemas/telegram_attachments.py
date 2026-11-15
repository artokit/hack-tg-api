from pydantic import BaseModel


class TelegramAttachmentTextRead(BaseModel):
    text: str
    truncated: bool
