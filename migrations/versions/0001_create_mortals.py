from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_create_mortals"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mortals",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column(
            "locale",
            sa.String(length=16),
            nullable=True,
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "notification_cron",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column("death_date", sa.Date(), nullable=True),
        sa.Column("telegram_unreachable_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("mortals")
