"""Initial local content-agent schema.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
from app import models  # noqa: F401
from app.database import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())
    try:
        op.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS source_blocks_fts "
            "USING fts5(block_id UNINDEXED, project_id UNINDEXED, text, tokenize='trigram')"
        )
    except Exception:
        op.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS source_blocks_fts "
            "USING fts5(block_id UNINDEXED, project_id UNINDEXED, text)"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS source_blocks_fts")
    Base.metadata.drop_all(bind=op.get_bind())
