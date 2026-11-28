"""Add direct user_id ownership foreign key and index to receipts table.

Revision ID: 1f9a2b3c4d5e
Revises: c3d4e5f6a7b8
Create Date: 2026-11-28 17:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "1f9a2b3c4d5e"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str, *, default_when_offline: bool = False) -> bool:
    if context.is_offline_mode():
        return default_when_offline
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table_name: str, col_name: str, *, default_when_offline: bool = False) -> bool:
    if context.is_offline_mode():
        return default_when_offline
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table_name):
        return False
    return any(c["name"] == col_name for c in insp.get_columns(table_name))


def _has_index(table_name: str, idx_name: str, *, default_when_offline: bool = False) -> bool:
    if context.is_offline_mode():
        return default_when_offline
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table_name):
        return False
    return any(idx["name"] == idx_name for idx in insp.get_indexes(table_name))


def upgrade() -> None:
    if _has_table("receipts") and not _has_column("receipts", "user_id"):
        with op.batch_alter_table("receipts") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "user_id",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", name="fk_receipts_user_id", ondelete="SET NULL"),
                    nullable=True,
                )
            )
    if _has_table("receipts") and not _has_index("receipts", "ix_receipts_user_id"):
        op.create_index("ix_receipts_user_id", "receipts", ["user_id"])
    if _has_table("receipts") and not _has_index("receipts", "ix_receipts_user_created"):
        op.create_index("ix_receipts_user_created", "receipts", ["user_id", "created_at"])

    op.execute(
        """
        UPDATE receipts
        SET user_id = (
            SELECT orders.customer_id
            FROM orders
            WHERE orders.id = receipts.order_id
        )
        WHERE user_id IS NULL
        """
    )


def downgrade() -> None:
    for idx_name in ("ix_receipts_user_created", "ix_receipts_user_id"):
        if _has_index("receipts", idx_name, default_when_offline=True):
            op.drop_index(idx_name, table_name="receipts")

    if _has_column("receipts", "user_id", default_when_offline=True):
        with op.batch_alter_table("receipts") as batch_op:
            batch_op.drop_column("user_id")
