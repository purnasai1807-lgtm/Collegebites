"""Automatic kitchen receipt printing, printer devices, and intelligent pause/resume queue.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-25 22:15:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
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
    if not _has_table("printer_devices"):
        op.create_table(
            "printer_devices",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False),
            sa.Column("counter_id", sa.Uuid(), sa.ForeignKey("counters.id", ondelete="SET NULL"), nullable=True),
            sa.Column("department", sa.String(length=32), nullable=False, server_default="kitchen"),
            sa.Column("device_name", sa.String(length=120), nullable=False),
            sa.Column("agent_id", sa.String(length=120), nullable=False, unique=True),
            sa.Column("agent_token_hash", sa.String(length=128), nullable=False),
            sa.Column("connection_type", sa.String(length=32), nullable=False, server_default="local_usb"),
            sa.Column("network_host", sa.String(length=120), nullable=True),
            sa.Column("network_port", sa.Integer(), nullable=True),
            sa.Column("paper_width", sa.String(length=16), nullable=False, server_default="80mm"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="offline"),
            sa.Column("is_connected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("paper_status", sa.String(length=32), nullable=False, server_default="unknown"),
            sa.Column("supports_realtime_status", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("supports_resume_offset", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("current_job_id", sa.Uuid(), nullable=True),
            sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_printer_devices_canteen_id", "printer_devices", ["canteen_id"])
        op.create_index("ix_printer_devices_agent_id", "printer_devices", ["agent_id"], unique=True)
        op.create_index("ix_printer_devices_canteen_dept", "printer_devices", ["canteen_id", "department"])
        op.create_index("ix_printer_devices_online", "printer_devices", ["is_connected", "is_online", "paper_status"])

    add_cols: list[sa.Column] = [
        sa.Column("canteen_id", sa.Uuid(), sa.ForeignKey("canteens.id", name="fk_receipt_print_jobs_canteen_id", ondelete="CASCADE"), nullable=True),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id", name="fk_receipt_print_jobs_payment_id", ondelete="SET NULL"), nullable=True),
        sa.Column("printer_device_id", sa.Uuid(), sa.ForeignKey("printer_devices.id", name="fk_receipt_print_jobs_printer_device_id", ondelete="SET NULL"), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("payload_checksum", sa.String(length=64), nullable=True),
        sa.Column("total_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_segments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_printed_byte_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_printed_segment_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resume_mode", sa.String(length=32), nullable=False, server_default="exact_offset"),
        sa.Column("paused_reason", sa.String(length=255), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by_agent", sa.String(length=120), nullable=True),
    ]
    cols_to_add = [col for col in add_cols if not _has_column("receipt_print_jobs", col.name)]
    if cols_to_add:
        with op.batch_alter_table("receipt_print_jobs") as batch_op:
            for col in cols_to_add:
                batch_op.add_column(col)

    if not _has_index("receipt_print_jobs", "ix_receipt_print_jobs_canteen_id"):
        op.create_index("ix_receipt_print_jobs_canteen_id", "receipt_print_jobs", ["canteen_id"])
    if not _has_index("receipt_print_jobs", "ix_receipt_print_jobs_payment_id"):
        op.create_index("ix_receipt_print_jobs_payment_id", "receipt_print_jobs", ["payment_id"])
    if not _has_index("receipt_print_jobs", "ix_receipt_print_jobs_printer_device_id"):
        op.create_index("ix_receipt_print_jobs_printer_device_id", "receipt_print_jobs", ["printer_device_id"])
    if not _has_index("receipt_print_jobs", "uq_receipt_print_jobs_idempotency_key"):
        op.create_index("uq_receipt_print_jobs_idempotency_key", "receipt_print_jobs", ["idempotency_key"], unique=True)
    if not _has_index("receipt_print_jobs", "ix_print_jobs_status_created"):
        op.create_index("ix_print_jobs_status_created", "receipt_print_jobs", ["status", "created_at"])
    if not _has_index("receipt_print_jobs", "ix_print_jobs_canteen_status_created"):
        op.create_index("ix_print_jobs_canteen_status_created", "receipt_print_jobs", ["canteen_id", "status", "created_at"])


def downgrade() -> None:
    for idx_name in (
        "ix_print_jobs_canteen_status_created",
        "ix_print_jobs_status_created",
        "uq_receipt_print_jobs_idempotency_key",
        "ix_receipt_print_jobs_printer_device_id",
        "ix_receipt_print_jobs_payment_id",
        "ix_receipt_print_jobs_canteen_id",
    ):
        if _has_index("receipt_print_jobs", idx_name, default_when_offline=True):
            op.drop_index(idx_name, table_name="receipt_print_jobs")

    drop_cols = [
        "claimed_by_agent",
        "next_retry_at",
        "completed_at",
        "started_at",
        "paused_at",
        "paused_reason",
        "resume_mode",
        "last_printed_segment_index",
        "last_printed_byte_offset",
        "total_segments",
        "total_bytes",
        "payload_checksum",
        "max_retries",
        "idempotency_key",
        "printer_device_id",
        "payment_id",
        "canteen_id",
    ]
    if _has_table("receipt_print_jobs", default_when_offline=True):
        with op.batch_alter_table("receipt_print_jobs") as batch_op:
            for cname in drop_cols:
                if _has_column("receipt_print_jobs", cname, default_when_offline=True):
                    batch_op.drop_column(cname)

    if _has_table("printer_devices", default_when_offline=True):
        op.drop_table("printer_devices")
