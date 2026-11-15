import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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


class SupportRequest(Base):
    __tablename__ = "support_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    instance_id: Mapped[str] = mapped_column(Text, unique=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    category_id: Mapped[str | None] = mapped_column(String(100))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    is_resolved: Mapped[bool | None] = mapped_column(Boolean)
    close_reason: Mapped[str] = mapped_column(String(40))
    model_cost_rub: Mapped[Decimal | None] = mapped_column(Numeric(18, 9))


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), default="default")
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    system: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="created")
    support_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("support_requests.id"), unique=True,
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text)
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


class AwMockSample(Base):
    __tablename__ = "aw_mock_samples"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    series: Mapped[str] = mapped_column(String(50))
    value: Mapped[float] = mapped_column(Float)


class RagDocument(Base):
    __tablename__ = "rag_documents"

    source_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    index_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    active_version: Mapped[str] = mapped_column(String(36))


class RagVisualFile(Base):
    __tablename__ = "rag_visual_files"
    __table_args__ = (Index("ix_rag_visual_files_version", "index_key", "version"),)

    file_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    index_key: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(36))


class RagGithubSync(Base):
    __tablename__ = "rag_github_syncs"

    index_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
