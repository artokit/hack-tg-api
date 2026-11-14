from sqlalchemy import Column, String, Uuid
from sqlalchemy.orm import MappedColumn

from db.db import Base


class File(Base):
    __tablename__ = "files"

    id: MappedColumn[str] = Column(Uuid, primary_key=True)
    name: MappedColumn[str] = Column(String, nullable=False)
    extension: MappedColumn[str] = Column(String, nullable=True)
