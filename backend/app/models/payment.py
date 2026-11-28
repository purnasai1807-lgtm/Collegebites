import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Money, TimestampMixin, UUIDPrimaryKeyMixin


class Payment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Payment aggregate for an order. Strictly no refund state or refund processing."""

    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_order_status", "order_id", "status"),
        Index("ix_payments_order_created", "order_id", "created_at"),
        Index("ix_payments_status_created", "status", "created_at"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False, default="razorpay")  # razorpay | counter_pos
    method: Mapped[Optional[str]] = mapped_column(String(48))  # upi | card | netbanking | wallet | upi_pos | card_pos
    provider_order_id: Mapped[Optional[str]] = mapped_column(String(120), unique=True, index=True)
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(120), unique=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), unique=True)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")  # PENDING | CONFIRMED | FAILED
    payment_reference: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    recorded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    gateway_metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


class PaymentTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "payment_transactions"

    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)  # initiate | authorize | capture | cash_collect | fail
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    external_reference: Mapped[Optional[str]] = mapped_column(String(120))
    raw_summary: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)  # Never store card numbers/CVV


class PaymentWebhookEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_webhook_provider_event_id"),)

    provider: Mapped[str] = mapped_column(String(48), nullable=False, default="razorpay")
    event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processing_error: Mapped[Optional[str]] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ReconciliationRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "reconciliation_runs"

    trigger: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    total_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discrepancy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_verified_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    run_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    summary_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


class PaymentReconciliation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "payment_reconciliation"
    __table_args__ = (UniqueConstraint("payment_id", name="uq_reconcil_payment_id"),)

    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("reconciliation_runs.id", ondelete="SET NULL"), index=True)
    gateway_provider: Mapped[str] = mapped_column(String(48), nullable=False, default="razorpay")
    gateway_settlement_id: Mapped[Optional[str]] = mapped_column(String(120))
    gateway_reference: Mapped[Optional[str]] = mapped_column(String(120))
    expected_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    settled_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    discrepancy_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    gateway_fee: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    tax_on_fee: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # matched | discrepancy | pending | failed
    reconciliation_source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    discrepancy_type: Mapped[str] = mapped_column(String(48), nullable=False, default="none")
    reconciled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reconciled_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[Optional[str]] = mapped_column(Text)


class OrderTokenSequence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "order_token_sequences"
    __table_args__ = (
        UniqueConstraint("canteen_id", "service_date", "prefix", name="uq_token_seq_canteen_date_prefix"),
    )

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    prefix: Mapped[str] = mapped_column(String(8), nullable=False, default="A")
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PickupToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "pickup_tokens"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_pickup_token_order"),
        UniqueConstraint("canteen_id", "service_date", "token_code", name="uq_pickup_token_scope"),
        Index("ix_pickup_tokens_lookup", "token_code", "service_date"),
        Index("ix_pickup_tokens_date_canteen_seq", "service_date", "canteen_id", "sequence_number"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False)
    counter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("counters.id", ondelete="RESTRICT"), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    token_code: Mapped[str] = mapped_column(String(16), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")  # ACTIVE | HANDED_OVER | REVOKED


class OrderQRCode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "order_qr_codes"
    __table_args__ = (UniqueConstraint("order_id", name="uq_order_qr_order"),)

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    pickup_token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pickup_tokens.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    verification_path: Mapped[str] = mapped_column(String(255), nullable=False)
    qr_payload_encoded: Mapped[str] = mapped_column(String(512), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[Optional[str]] = mapped_column(String(255))


class QRVerificationEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "qr_verification_events"

    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), index=True)
    pickup_token_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("pickup_tokens.id", ondelete="SET NULL"), index=True
    )
    staff_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"))
    counter_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("counters.id", ondelete="SET NULL"))
    verification_method: Mapped[str] = mapped_column(String(32), nullable=False)  # qr_scan | manual_token | order_number
    presented_code_masked: Mapped[Optional[str]] = mapped_column(String(64))
    result_code: Mapped[str] = mapped_column(String(48), nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    details: Mapped[Optional[str]] = mapped_column(String(255))


class OrderHandoverRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "order_handover_records"
    __table_args__ = (UniqueConstraint("order_id", name="uq_handover_order_once"),)

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    pickup_token_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pickup_tokens.id", ondelete="RESTRICT"), nullable=False
    )
    counter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("counters.id", ondelete="RESTRICT"), nullable=False)
    handed_over_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    verification_method: Mapped[str] = mapped_column(String(32), nullable=False, default="qr_scan")
    handed_over_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(255))


class Receipt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "receipts"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_receipts_order"),
        Index("ix_receipts_user_created", "user_id", "created_at"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", name="fk_receipts_user_id", ondelete="SET NULL"), nullable=True, index=True
    )
    receipt_number: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    pickup_token_code: Mapped[str] = mapped_column(String(16), nullable=False)
    reprint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    receipt_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)


class PrinterDevice(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Registered kitchen/counter thermal printer & local print agent metadata."""

    __tablename__ = "printer_devices"
    __table_args__ = (
        Index("ix_printer_devices_canteen_dept", "canteen_id", "department"),
        Index("ix_printer_devices_online", "is_connected", "is_online", "paper_status"),
    )

    canteen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), nullable=False, index=True)
    counter_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("counters.id", ondelete="SET NULL"))
    department: Mapped[str] = mapped_column(String(32), nullable=False, default="kitchen")  # kitchen | counter
    device_name: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    agent_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_type: Mapped[str] = mapped_column(String(32), nullable=False, default="local_usb")  # local_usb | local_serial | network_escpos | os_spooler
    network_host: Mapped[Optional[str]] = mapped_column(String(120))
    network_port: Mapped[Optional[int]] = mapped_column(Integer)
    paper_width: Mapped[str] = mapped_column(String(16), nullable=False, default="80mm")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="offline")  # online | offline | paused | error
    is_connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    paper_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")  # available | low | out_of_paper | unknown
    supports_realtime_status: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supports_resume_offset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    current_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(String(255))


class ReceiptPrintJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "receipt_print_jobs"
    __table_args__ = (
        Index("ix_print_jobs_status_created", "status", "created_at"),
        Index("ix_print_jobs_canteen_status_created", "canteen_id", "status", "created_at"),
    )

    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="CASCADE"), index=True)
    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"), index=True)
    printer_device_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("printer_devices.id", ondelete="SET NULL"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, default="customer_receipt")  # customer_receipt | kitchen_receipt | kot
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), unique=True)
    printer_target: Mapped[str] = mapped_column(String(64), nullable=False, default="browser")  # browser | 58mm | 80mm | a4_pdf | network_escpos | usb | bluetooth | local_agent_escpos
    printer_name: Mapped[Optional[str]] = mapped_column(String(120))
    paper_width: Mapped[str] = mapped_column(String(16), nullable=False, default="80mm")
    network_host: Mapped[Optional[str]] = mapped_column(String(120))
    network_port: Mapped[Optional[int]] = mapped_column(Integer)
    is_reprint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")  # pending | queued | printing | paused | completed | failed
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    payload_checksum: Mapped[Optional[str]] = mapped_column(String(64))
    total_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_segments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_printed_byte_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_printed_segment_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resume_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="exact_offset")  # exact_offset | controlled_reprint_continuation
    paused_reason: Mapped[Optional[str]] = mapped_column(String(255))
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    claimed_by_agent: Mapped[Optional[str]] = mapped_column(String(120))
    error_message: Mapped[Optional[str]] = mapped_column(String(255))
    requested_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ReceiptPrintHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "receipt_print_history"

    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, index=True)
    print_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("receipt_print_jobs.id", ondelete="SET NULL"))
    printed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    printed_by_label: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    printer_target: Mapped[str] = mapped_column(String(64), nullable=False)
    is_reprint: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reprint_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="printed")
    printed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Invoice(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "invoices"

    invoice_number: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    invoice_type: Mapped[str] = mapped_column(String(32), nullable=False, default="order", index=True)  # order | event_bulk | meal_plan
    order_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), unique=True)
    bulk_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("event_bulk_orders.id", ondelete="CASCADE"), unique=True)
    subscription_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("student_meal_subscriptions.id", ondelete="CASCADE"), unique=True)
    canteen_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("canteens.id", ondelete="SET NULL"), index=True)
    customer_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reference_number: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(140), nullable=False)
    customer_contact: Mapped[Optional[str]] = mapped_column(String(140))
    subtotal_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_breakdown_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    items_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_reference: Mapped[Optional[str]] = mapped_column(String(128))
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="CONFIRMED")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

