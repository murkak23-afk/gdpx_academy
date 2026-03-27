"""submission phone_normalized, is_duplicate, last_status_change

Revision ID: 20260327_0017
Revises: 2368fc78c9d8
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision = "20260327_0017"
down_revision = "2368fc78c9d8"
branch_labels = None
depends_on = None


def _normalize_phone_key(desc: str | None) -> str | None:
    d = "".join(c for c in (desc or "") if c.isdigit())
    if not d:
        return None
    if d.startswith("8") and len(d) == 11:
        d = "7" + d[1:]
    if len(d) == 10:
        d = "7" + d
    return d


def upgrade() -> None:
    op.add_column("submissions", sa.Column("phone_normalized", sa.String(length=32), nullable=True))
    op.add_column("submissions", sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("submissions", sa.Column("last_status_change", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_submissions_phone_normalized", "submissions", ["phone_normalized"], unique=False)

    conn = op.get_bind()
    rows = conn.execute(text("SELECT id, description_text FROM submissions")).fetchall()
    for row in rows:
        sid, desc = int(row[0]), row[1]
        key = _normalize_phone_key(str(desc) if desc is not None else "")
        conn.execute(
            text("UPDATE submissions SET phone_normalized = :pn WHERE id = :id"),
            {"pn": key, "id": sid},
        )

    conn.execute(
        text(
            "UPDATE submissions SET last_status_change = COALESCE(assigned_at, reviewed_at, created_at) "
            "WHERE last_status_change IS NULL"
        )
    )

    conn.execute(text("UPDATE submissions SET is_duplicate = false"))
    conn.execute(
        text(
            """
            UPDATE submissions s SET is_duplicate = true
            WHERE s.phone_normalized IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM submissions s2
                WHERE s2.phone_normalized = s.phone_normalized AND s2.id < s.id
            )
            """
        )
    )

    op.alter_column("submissions", "is_duplicate", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_submissions_phone_normalized", table_name="submissions")
    op.drop_column("submissions", "last_status_change")
    op.drop_column("submissions", "is_duplicate")
    op.drop_column("submissions", "phone_normalized")
