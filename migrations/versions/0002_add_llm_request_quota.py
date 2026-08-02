from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_llm_request_quota"
down_revision: str | None = "0001_create_mortals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mortals",
        sa.Column(
            "llm_requests_remaining",
            sa.Integer(),
            nullable=False,
        ),
    )
    op.create_table(
        "llm_request_consumptions",
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("mortal_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["mortal_id"], ["mortals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("request_id"),
    )


def downgrade() -> None:
    op.drop_table("llm_request_consumptions")
    op.drop_column("mortals", "llm_requests_remaining")
