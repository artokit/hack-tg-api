from datetime import datetime

from pydantic import BaseModel, Field


class ConfluenceBodyRead(BaseModel):
    value: str


class ConfluencePageBodyRead(BaseModel):
    view: ConfluenceBodyRead


class ConfluenceVersionRead(BaseModel):
    number: int
    created_at: datetime = Field(alias="createdAt")


class ConfluencePageData(BaseModel):
    id: str = Field(pattern=r"^[1-9][0-9]*$")
    space_id: str = Field(alias="spaceId", pattern=r"^[1-9][0-9]*$")
    title: str
    status: str
    body: ConfluencePageBodyRead
    version: ConfluenceVersionRead


class ConfluenceSpaceData(BaseModel):
    id: str
    key: str


class ConfluencePageRead(BaseModel):
    page_id: str
    space_id: str
    space_key: str
    title: str
    status: str
    content_html: str
    version: int
    updated_at: datetime
    url: str
