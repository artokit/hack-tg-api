import uuid
from typing import Sequence, Union

import bcrypt
import sqlalchemy as sa
from alembic import op


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    admins = op.create_table(
        "admins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
    )
    op.create_index("ix_admins_email", "admins", ["email"], unique=True)
    op.bulk_insert(
        admins,
        [
            {
                "id": uuid.uuid4(),
                "email": "admin@example.com",
                "hashed_password": bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode(),
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_admins_email", table_name="admins")
    op.drop_table("admins")
