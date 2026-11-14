import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_parsed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), default="default")
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    system: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="created")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint("count_of_use > 0", name="ck_invites_positive_count_of_use"),
        CheckConstraint(
            "count_of_use = 1 OR (first_name IS NULL AND last_name IS NULL)",
            name="ck_invites_single_use_names",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    count_of_use: Mapped[int] = mapped_column(Integer, default=1)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class RagDocument(Base):
    __tablename__ = "rag_documents"

    source_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    index_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    active_version: Mapped[str] = mapped_column(String(36))


class RagJob(Base):
    __tablename__ = "rag_jobs"
    __table_args__ = (
        Index("ix_rag_jobs_index_status_created", "index_key", "status", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(100))
    index_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(250))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(String(32))
    source_locator: Mapped[dict[str, str] | None] = mapped_column(JSONB(none_as_null=True))
    source_revision: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    size_bytes: Mapped[int | None] = mapped_column()
    format: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error_code: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[str | None] = mapped_column(String(36))
    chunk_count: Mapped[int | None] = mapped_column()
    cleanup: Mapped[list[dict]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
