import base64
import hmac
import io
import ipaddress
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.security import mask_mobile, sha256_hex
from app.core.time_utils import get_college_tz
from app.integrations.printers.escpos import (
    build_escpos_kot_bytes,
    build_escpos_receipt_bytes,
    build_escpos_receipt_segments,
    compute_escpos_checksum,
    send_escpos_network_tcp,
    send_escpos_segments_tcp,
)
from app.models.auth import User
from app.models.college import Canteen, Counter, KitchenStation
from app.models.order import Order, OrderItem
from app.models.payment import (
    OrderQRCode,
    Payment,
    PickupToken,
    PrinterDevice,
    Receipt,
    ReceiptPrintHistory,
    ReceiptPrintJob,
)
from app.schemas.payment import (
    AgentHeartbeatRequest,
    AgentJobCompleteRequest,
    AgentJobFailRequest,
    AgentJobPauseRequest,
    AgentJobProgressRequest,
    PrintJobOut,
    PrintReceiptRequest,
    PrinterDeviceCreateRequest,
    PrinterDeviceOut,
)
from app.services.audit_service import record_audit_log
from app.services.college_service import get_or_create_college_settings
from app.services.qr_location_service import render_qr_base64, render_qr_png_bytes

PICKUP_INSTRUCTIONS = [
    "Show this token at the pickup counter.",
    "Keep the QR code available.",
    "Collect food only after the order is marked READY.",
    "Each order can be handed over only once.",
]


def create_receipt_for_order(db: Session, order: Order, pickup_token: PickupToken, qr_row: OrderQRCode, payment: Payment) -> Receipt:
    """Create a complete immutable historical receipt snapshot strictly after payment confirmation."""
    if order.payment_status != "CONFIRMED" or payment.status != "CONFIRMED":
        raise HTTPException(
            status_code=409,
            detail="Digital customer receipt can only be generated after trusted payment verification",
        )
    existing = db.scalar(select(Receipt).where(Receipt.order_id == order.id))
    if existing:
        return existing

    college = get_or_create_college_settings(db)
    canteen = db.get(Canteen, order.canteen_id)
    counter = db.get(Counter, order.counter_id)
    customer = db.get(User, order.customer_id) if order.customer_id else None

    customer_name = order.guest_name if order.is_guest else (customer.full_name if customer else "Customer")
    raw_phone = order.guest_phone if order.is_guest else (customer.phone if customer else None)
    masked_phone = mask_mobile(raw_phone) if raw_phone else None

    loaded_items = db.scalars(
        select(OrderItem).options(selectinload(OrderItem.customizations)).where(OrderItem.order_id == order.id)
    ).all()

    items_snapshot: list[dict[str, Any]] = []
    for oi in loaded_items:
        items_snapshot.append({
            "item_name": oi.item_name,
            "variant_name": oi.variant_name,
            "quantity": oi.quantity,
            "unit_price": f"{oi.unit_price:.2f}",
            "addon_total_per_unit": f"{oi.addon_total_per_unit:.2f}",
            "line_subtotal": f"{oi.line_subtotal:.2f}",
            "tax_amount": f"{oi.tax_amount:.2f}",
            "line_total": f"{oi.line_total:.2f}",
            "special_instructions": oi.special_instructions,
            "customizations": [
                {
                    "customization_type": c.customization_type,
                    "option_name": c.option_name,
                    "option_value": c.option_value,
                    "quantity": c.quantity,
                    "unit_price": f"{c.unit_price:.2f}",
                    "total_price": f"{c.total_price:.2f}",
                }
                for c in oi.customizations
            ],
        })

    confirmed_ts = (payment.confirmed_at or datetime.now(timezone.utc)).astimezone(get_college_tz(college.college_timezone))
    est_pickup_ts = (order.estimated_pickup_at or payment.confirmed_at or datetime.now(timezone.utc)).astimezone(get_college_tz(college.college_timezone))
    receipt_number = f"REC-{order.order_number[3:]}" if order.order_number.startswith("CB-") else f"REC-{order.order_number}"

    snapshot: dict[str, Any] = {
        "brand": "COLLEGEBITES",
        "college_name": college.college_name,
        "college_short_code": college.college_short_code,
        "college_logo_url": college.logo_url or "/branding/collegebites-logo.png",
        "college_address": college.address,
        "college_phone": college.contact_phone,
        "college_email": college.contact_email,
        "canteen_name": canteen.name if canteen else "Main Canteen",
        "canteen_location": canteen.location if canteen else "",
        "canteen_contact": canteen.contact_phone if canteen else None,
        "counter_name": counter.name if counter else "Counter 1",
        "receipt_number": receipt_number,
        "order_number": order.order_number,
        "pickup_token": pickup_token.token_code,
        "qr_verification_path": qr_row.verification_path,
        "qr_payload": qr_row.qr_payload_encoded,
        "order_date": confirmed_ts.strftime("%d-%m-%Y"),
        "order_time": confirmed_ts.strftime("%I:%M %p"),
        "estimated_pickup_time": est_pickup_ts.strftime("%I:%M %p"),
        "payment_reference": payment.payment_reference or payment.provider_payment_id or f"PAY-{order.order_number}",
        "payment_method": payment.method or order.payment_method,
        "payment_status": "PAID",
        "order_type": order.order_type,
        "order_status": "CONFIRMED",
        "customer_name": customer_name or "Guest",
        "customer_type_label": "Guest" if order.is_guest else "Customer",
        "customer_mobile_masked": masked_phone,
        "items": items_snapshot,
        "subtotal_amount": f"{order.subtotal_amount:.2f}",
        "discount_amount": f"{order.discount_amount:.2f}",
        "tax_amount": f"{order.tax_amount:.2f}",
        "total_paid": f"{order.total_amount:.2f}",
        "tax_inclusive_notice": (
            "Listed prices inclusive of applicable statutory taxes. No additional checkout tax or extra charges."
            if order.tax_amount == Decimal("0.00")
            else None
        ),
        "currency_symbol": college.currency_symbol or "₹",
        "pickup_instructions": PICKUP_INSTRUCTIONS,
    }

    receipt = Receipt(
        order_id=order.id,
        user_id=order.customer_id,
        receipt_number=receipt_number,
        pickup_token_code=pickup_token.token_code,
        reprint_count=0,
        receipt_snapshot=snapshot,
    )
    db.add(receipt)
    db.flush()
    return receipt


def _resolve_order_and_receipt(
    db: Session,
    order_id_or_number: str,
    *,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    staff_canteen_id: Optional[UUID] = None,
    staff_counter_id: Optional[UUID] = None,
    guest_access_token: Optional[str] = None,
) -> tuple[Order, Receipt]:
    raw_ref = order_id_or_number.strip()
    order: Optional[Order] = None
    receipt: Optional[Receipt] = None

    try:
        ref_uuid = UUID(raw_ref)
        order = db.get(Order, ref_uuid)
        if not order:
            receipt = db.get(Receipt, ref_uuid)
            if receipt:
                order = db.get(Order, receipt.order_id)
    except ValueError:
        order = db.scalar(select(Order).where(Order.order_number == raw_ref))
        if not order:
            receipt = db.scalar(select(Receipt).where(Receipt.receipt_number == raw_ref))
            if receipt:
                order = db.get(Order, receipt.order_id)

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if is_staff:
        if staff_canteen_id and order.canteen_id != staff_canteen_id:
            raise HTTPException(status_code=403, detail="Staff user is not authorized for this canteen")
        if staff_counter_id and order.counter_id != staff_counter_id:
            raise HTTPException(status_code=403, detail="Counter staff user is not authorized for this counter")
    else:
        if order.is_guest:
            if not guest_access_token or order.guest_access_token_hash != sha256_hex(guest_access_token):
                if user_id is None and not guest_access_token:
                    raise HTTPException(status_code=401, detail="Authentication or valid guest token required")
                raise HTTPException(status_code=403, detail="Valid guest access token required")
        elif user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required to access this receipt")
        elif order.customer_id != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to access this receipt")

    if receipt is None:
        receipt = db.scalar(select(Receipt).where(Receipt.order_id == order.id))
    if not receipt:
        raise HTTPException(status_code=409, detail="Receipt is only available after payment confirmation")
    if not is_staff and not order.is_guest and receipt.user_id is not None and receipt.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this receipt")
    return order, receipt


def list_my_receipts(
    db: Session,
    *,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Strictly retrieve receipts owned by the authenticated user account only."""
    rows = db.execute(
        select(Receipt, Order)
        .join(Order, Order.id == Receipt.order_id)
        .where(
            Order.customer_id == user_id,
            Receipt.user_id == user_id,
            Order.is_guest.is_(False),
        )
        .order_by(Receipt.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    out: list[dict[str, Any]] = []
    for receipt, order in rows:
        snap = receipt.receipt_snapshot if isinstance(receipt.receipt_snapshot, dict) else {}
        out.append(
            {
                "receipt_id": str(receipt.id),
                "receipt_number": receipt.receipt_number,
                "order_id": str(order.id),
                "order_number": order.order_number,
                "canteen_name": snap.get("canteen_name", "Campus Canteen"),
                "counter_name": snap.get("counter_name", "Counter"),
                "order_status": order.status,
                "payment_status": order.payment_status,
                "payment_method": snap.get("payment_method", order.payment_method),
                "total_paid": f"{order.total_amount:.2f}",
                "pickup_token": receipt.pickup_token_code,
                "order_date": snap.get("order_date"),
                "order_time": snap.get("order_time"),
                "reprint_count": receipt.reprint_count,
                "items": snap.get("items", []),
                "created_at": receipt.created_at.isoformat() if receipt.created_at else None,
            }
        )
    return out


def get_receipt_payload(
    db: Session,
    order_id_or_number: str,
    *,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    staff_canteen_id: Optional[UUID] = None,
    staff_counter_id: Optional[UUID] = None,
    guest_access_token: Optional[str] = None,
) -> dict[str, Any]:
    order, receipt = _resolve_order_and_receipt(
        db,
        order_id_or_number,
        user_id=user_id,
        is_staff=is_staff,
        staff_canteen_id=staff_canteen_id,
        staff_counter_id=staff_counter_id,
        guest_access_token=guest_access_token,
    )
    snap = dict(receipt.receipt_snapshot)
    snap["order_status"] = order.status
    snap["receipt_id"] = str(receipt.id)
    snap["reprint_count"] = receipt.reprint_count
    snap["is_reprint"] = receipt.reprint_count > 0
    snap["reprint_label"] = f"REPRINT #{receipt.reprint_count}" if receipt.reprint_count > 0 else None
    snap["qr_image_base64"] = render_qr_base64(snap["qr_payload"], box_size=8)
    return snap


def generate_receipt_pdf_bytes(
    db: Session,
    order_id_or_number: str,
    *,
    paper_format: str = "a4",
    is_reprint_view: bool = False,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    staff_canteen_id: Optional[UUID] = None,
    staff_counter_id: Optional[UUID] = None,
    guest_access_token: Optional[str] = None,
) -> tuple[bytes, str]:
    snap = get_receipt_payload(
        db,
        order_id_or_number,
        user_id=user_id,
        is_staff=is_staff,
        staff_canteen_id=staff_canteen_id,
        staff_counter_id=staff_counter_id,
        guest_access_token=guest_access_token,
    )
    show_reprint = is_reprint_view or snap.get("reprint_count", 0) > 0

    buf = io.BytesIO()
    if paper_format == "58mm":
        page_w = 58 * mm
        est_lines = sum(3 + len(it.get("customizations", [])) for it in snap.get("items", []))
        page_h = max(210 * mm, (158 + est_lines * 5.5) * mm)
        c = canvas.Canvas(buf, pagesize=(page_w, page_h))
        margin = 3 * mm
    elif paper_format == "80mm":
        page_w = 80 * mm
        est_lines = sum(2 + len(it.get("customizations", [])) for it in snap.get("items", []))
        page_h = max(210 * mm, (158 + est_lines * 5.5) * mm)
        c = canvas.Canvas(buf, pagesize=(page_w, page_h))
        margin = 5 * mm
    else:
        page_w, page_h = A4
        c = canvas.Canvas(buf, pagesize=A4)
        margin = 18 * mm

    y = page_h - margin
    center_x = page_w / 2.0
    max_text_w = page_w - (margin * 2)

    def ensure_space(needed: float = 12 * mm):
        nonlocal y
        if paper_format == "a4" and y - needed < margin:
            c.showPage()
            y = page_h - margin

    def _split_pdf_text(text: str, font: str, size: float, limit_w: float) -> list[str]:
        if c.stringWidth(text, font, size) <= limit_w:
            return [text]
        words = text.split(" ")
        lines: list[str] = []
        cur = ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if c.stringWidth(cand, font, size) <= limit_w:
                cur = cand
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [text[:40]]

    def draw_center(text: str, font: str = "Helvetica-Bold", size: float = 11, dy: float = 4.8 * mm, color=colors.black):
        nonlocal y
        c.setFillColor(color)
        c.setFont(font, size)
        for line in _split_pdf_text(text, font, size, max_text_w):
            ensure_space(dy)
            c.drawCentredString(center_x, y, line)
            y -= dy

    def draw_lr(left: str, right: str, font: str = "Helvetica", size: float = 9, dy: float = 4.4 * mm):
        nonlocal y
        c.setFillColor(colors.black)
        c.setFont(font, size)
        right_w = c.stringWidth(right, font, size) if right else 0
        avail_left = max(16 * mm, max_text_w - right_w - 3 * mm)
        left_lines = _split_pdf_text(left, font, size, avail_left)
        for i, line in enumerate(left_lines):
            ensure_space(dy)
            c.drawString(margin, y, line)
            if i == 0 and right:
                c.drawRightString(page_w - margin, y, right)
            y -= dy

    def draw_sep():
        nonlocal y
        ensure_space(5 * mm)
        c.setStrokeColor(colors.grey)
        c.setLineWidth(0.5)
        c.line(margin, y, page_w - margin, y)
        y -= 4 * mm

    base_font_sz = 7.2 if paper_format == "58mm" else 8.5 if paper_format == "80mm" else 9
    logo_path = Path(__file__).resolve().parent.parent / "assets" / "collegebites-logo.png"
    if logo_path.is_file():
        logo_sz = 15 * mm if paper_format == "a4" else 11 * mm
        ensure_space(logo_sz + 3 * mm)
        c.drawImage(
            ImageReader(str(logo_path)),
            center_x - logo_sz / 2,
            y - logo_sz + 1.5 * mm,
            width=logo_sz,
            height=logo_sz,
            mask="auto",
        )
        y -= logo_sz + 2.5 * mm
    draw_center("COLLEGEBITES", "Helvetica-Bold", 14 if paper_format == "a4" else 10.5, 5.2 * mm)
    draw_center(snap["college_name"].upper(), "Helvetica-Bold", 10 if paper_format == "a4" else 8, 4.3 * mm)
    draw_center(f"{snap['canteen_name']} ({snap.get('canteen_location', '')})", "Helvetica", base_font_sz, 4 * mm)
    if show_reprint:
        draw_center(f"*** REPRINT #{max(1, snap.get('reprint_count', 1))} ***", "Helvetica-Bold", 9.5, 5 * mm, colors.red)
    draw_sep()

    draw_lr(f"ORDER NO: {snap['order_number']}", f"REC: {snap['receipt_number']}", "Helvetica-Bold", base_font_sz)
    draw_center("PICKUP TOKEN", "Helvetica-Bold", 8.5, 5.5 * mm)
    draw_center(snap["pickup_token"], "Helvetica-Bold", 24 if paper_format == "a4" else 17, 8.5 * mm)

    qr_png = render_qr_png_bytes(snap["qr_payload"], box_size=8)
    qr_size = 34 * mm if paper_format == "a4" else (24 * mm if paper_format == "58mm" else 28 * mm)
    ensure_space(qr_size + 5 * mm)
    c.drawImage(ImageReader(io.BytesIO(qr_png)), center_x - qr_size / 2, y - qr_size + 2 * mm, width=qr_size, height=qr_size)
    y -= qr_size + 3 * mm
    draw_sep()

    draw_lr(f"CUSTOMER: {snap['customer_name']} ({snap['customer_type_label']})", f"MOBILE: {snap.get('customer_mobile_masked') or 'N/A'}", "Helvetica", base_font_sz)
    draw_lr(f"DATE: {snap['order_date']}  TIME: {snap['order_time']}", f"EST PICKUP: {snap['estimated_pickup_time']}", "Helvetica", base_font_sz)
    draw_lr(f"COUNTER: {snap['counter_name']}", f"TYPE: {snap['order_type'].upper()}", "Helvetica-Bold", base_font_sz)
    draw_sep()

    draw_lr("ORDERED ITEMS", "QTY / AMOUNT", "Helvetica-Bold", base_font_sz)
    for idx, item in enumerate(snap.get("items", []), start=1):
        var_label = f" ({item['variant_name']})" if item.get("variant_name") else ""
        draw_lr(
            f"{idx}. {item['item_name']}{var_label}",
            f"{item['quantity']} x Rs.{Decimal(item['unit_price']):.2f} = Rs.{Decimal(item['line_subtotal']):.2f}",
            "Helvetica-Bold",
            base_font_sz,
            4.0 * mm,
        )
        for cust in item.get("customizations", []):
            price_txt = f"Rs.{Decimal(cust['total_price']):.2f}" if Decimal(cust["total_price"]) > 0 else "Included"
            draw_lr(f"    {cust['option_name']}: {cust['option_value']}", price_txt, "Helvetica", max(6.8, base_font_sz - 0.7), 3.6 * mm)
        if item.get("special_instructions"):
            draw_lr(f"    Note: {item['special_instructions']}", "", "Helvetica-Oblique", max(6.8, base_font_sz - 0.8), 3.6 * mm)

    draw_sep()
    draw_lr("SUBTOTAL", f"Rs.{Decimal(snap['subtotal_amount']):.2f}", "Helvetica", base_font_sz)
    if Decimal(snap.get("discount_amount", "0.00")) > Decimal("0.00"):
        draw_lr("DISCOUNT", f"-Rs.{Decimal(snap['discount_amount']):.2f}", "Helvetica", base_font_sz)
    if Decimal(snap.get("tax_amount", "0.00")) > Decimal("0.00"):
        draw_lr("TAX", f"Rs.{Decimal(snap['tax_amount']):.2f}", "Helvetica", base_font_sz)
    draw_lr("TOTAL PAID", f"Rs.{Decimal(snap['total_paid']):.2f}", "Helvetica-Bold", base_font_sz + 1.5, 5.2 * mm)
    if Decimal(snap.get("tax_amount", "0.00")) == Decimal("0.00"):
        draw_center("Prices inclusive of applicable statutory taxes.", "Helvetica-Oblique", max(6.4, base_font_sz - 1.0), 3.4 * mm)
    draw_lr(f"PAYMENT: {snap['payment_status']}", f"METHOD: {snap['payment_method'].upper()}", "Helvetica-Bold", base_font_sz)
    draw_lr(f"PAY REF: {snap['payment_reference']}", f"STATUS: {snap['order_status']}", "Helvetica", max(6.8, base_font_sz - 0.5))
    draw_sep()

    for line in snap.get("pickup_instructions", []):
        draw_center(line, "Helvetica", max(6.5, base_font_sz - 1), 3.5 * mm)
    draw_center("THANK YOU FOR ORDERING WITH COLLEGEBITES!", "Helvetica-Bold", base_font_sz, 4 * mm)

    c.showPage()
    c.save()
    return buf.getvalue(), snap["order_number"]


def get_escpos_payload(
    db: Session,
    order_id_or_number: str,
    *,
    paper_width: str = "80mm",
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    staff_canteen_id: Optional[UUID] = None,
    staff_counter_id: Optional[UUID] = None,
    guest_access_token: Optional[str] = None,
) -> dict[str, Any]:
    order, receipt = _resolve_order_and_receipt(
        db,
        order_id_or_number,
        user_id=user_id,
        is_staff=is_staff,
        staff_canteen_id=staff_canteen_id,
        staff_counter_id=staff_counter_id,
        guest_access_token=guest_access_token,
    )
    raw_bytes = build_escpos_receipt_bytes(
        receipt.receipt_snapshot,
        paper_width=paper_width,
        is_reprint=receipt.reprint_count > 0,
        reprint_number=receipt.reprint_count,
    )
    return {
        "order_number": order.order_number,
        "pickup_token": receipt.pickup_token_code,
        "paper_width": paper_width,
        "escpos_base64": base64.b64encode(raw_bytes).decode("ascii"),
        "byte_length": len(raw_bytes),
    }


def ensure_customer_receipt_print_job(
    db: Session,
    order: Order,
    receipt: Receipt,
    *,
    payment: Optional[Payment] = None,
    actor_user_id: Optional[UUID] = None,
) -> ReceiptPrintJob:
    """
    Idempotently create the customer receipt print job immediately after payment verification.
    Never increments `reprint_count`; network printer unreachable errors are recorded on the job
    without rolling back the verified payment.
    """
    existing_job = db.scalar(
        select(ReceiptPrintJob).where(
            ReceiptPrintJob.order_id == order.id,
            ReceiptPrintJob.job_type == "customer_receipt",
            ReceiptPrintJob.is_reprint.is_(False),
        )
    )
    if existing_job:
        return existing_job

    segments = build_escpos_receipt_segments(receipt.receipt_snapshot, paper_width="80mm", is_reprint=False, reprint_number=0)
    raw_bytes = b"".join(s["bytes"] for s in segments)
    checksum = compute_escpos_checksum(raw_bytes)
    target = "network_escpos" if settings.NETWORK_PRINTER_ENABLED else "browser"
    job = ReceiptPrintJob(
        receipt_id=receipt.id,
        order_id=order.id,
        canteen_id=order.canteen_id,
        payment_id=payment.id if payment else None,
        job_type="customer_receipt",
        idempotency_key=f"customer_receipt:{order.id}:{payment.id if payment else receipt.id}",
        printer_target=target,
        printer_name="Counter Receipt Printer" if settings.NETWORK_PRINTER_ENABLED else "Digital Customer Receipt",
        paper_width="80mm",
        network_host=settings.DEFAULT_PRINTER_IP if settings.NETWORK_PRINTER_ENABLED else None,
        network_port=settings.DEFAULT_PRINTER_PORT if settings.NETWORK_PRINTER_ENABLED else None,
        is_reprint=False,
        status="queued",
        payload_checksum=checksum,
        total_bytes=len(raw_bytes),
        total_segments=len(segments),
        requested_by_user_id=actor_user_id,
    )
    db.add(job)
    db.flush()

    if settings.NETWORK_PRINTER_ENABLED and settings.DEFAULT_PRINTER_IP:
        try:
            send_escpos_network_tcp(settings.DEFAULT_PRINTER_IP, settings.DEFAULT_PRINTER_PORT, raw_bytes)
            job.status = "completed"
            job.last_printed_segment_index = len(segments)
            job.last_printed_byte_offset = len(raw_bytes)
            job.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            job.status = "failed"
            job.error_message = f"Auto customer receipt print failed: {str(exc)[:200]}"
    return job


KOT_ALLOWED_STATUSES = ("ACCEPTED", "PREPARING", "READY", "COMPLETED")


def get_kitchen_ticket_escpos_payload(
    db: Session,
    order_id_or_number: str,
    *,
    paper_width: str = "80mm",
    station_id: Optional[UUID] = None,
    staff_canteen_id: Optional[UUID] = None,
) -> dict[str, Any]:
    stmt = select(Order).options(selectinload(Order.items).selectinload(OrderItem.customizations))
    try:
        oid = UUID(order_id_or_number)
        order = db.scalar(stmt.where(Order.id == oid))
    except ValueError:
        order = db.scalar(stmt.where(Order.order_number == order_id_or_number))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if staff_canteen_id and order.canteen_id != staff_canteen_id:
        raise HTTPException(status_code=403, detail="Staff user is not authorized for this canteen")
    if order.payment_status != "CONFIRMED":
        raise HTTPException(status_code=409, detail="Kitchen Order Ticket available only after payment confirmation")
    if order.status not in KOT_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Kitchen Order Ticket (KOT) is generated only after the order is accepted by the kitchen",
        )

    canteen = db.get(Canteen, order.canteen_id)
    counter = db.get(Counter, order.counter_id)
    tok = db.scalar(select(PickupToken).where(PickupToken.order_id == order.id))
    station_ids = {oi.station_id for oi in order.items if oi.station_id}
    if station_id:
        station_ids.add(station_id)
    station_names = (
        {st.id: st.name for st in db.scalars(select(KitchenStation).where(KitchenStation.id.in_(station_ids))).all()}
        if station_ids
        else {}
    )
    items = [oi for oi in order.items if not station_id or oi.station_id == station_id]
    local_ts = order.created_at.astimezone(get_college_tz())
    kot_payload = {
        "order_number": order.order_number,
        "pickup_token": tok.token_code if tok else order.order_number[-4:],
        "canteen_name": canteen.name if canteen else "CollegeBites",
        "counter_name": counter.name if counter else None,
        "order_type": order.order_type,
        "is_priority": bool(order.is_priority),
        "station_filter_name": station_names.get(station_id) if station_id else None,
        "order_time": local_ts.strftime("%d-%b %I:%M %p"),
        "notes": order.notes,
        "items": [
            {
                "item_name": oi.item_name,
                "variant_name": oi.variant_name,
                "quantity": oi.quantity,
                "station_name": station_names.get(oi.station_id) if oi.station_id else None,
                "special_instructions": oi.special_instructions,
                "customizations": [
                    {"option_name": c.option_name, "option_value": c.option_value}
                    for c in oi.customizations
                ],
            }
            for oi in items
        ],
    }
    raw_bytes = build_escpos_kot_bytes(kot_payload, paper_width=paper_width)
    return {
        "order_number": order.order_number,
        "pickup_token": kot_payload["pickup_token"],
        "paper_width": paper_width,
        "station_id": str(station_id) if station_id else None,
        "item_count": len(items),
        "escpos_base64": base64.b64encode(raw_bytes).decode("ascii"),
        "byte_length": len(raw_bytes),
    }


def ensure_kot_print_job_for_accepted_order(
    db: Session,
    order: Order,
    *,
    actor_user_id: Optional[UUID] = None,
) -> Optional[ReceiptPrintJob]:
    """
    Generate the Kitchen Order Ticket (KOT) print job ONLY after payment is CONFIRMED
    AND the order has been ACCEPTED by kitchen staff. Idempotent across retries.
    """
    if order.payment_status != "CONFIRMED" or order.status not in KOT_ALLOWED_STATUSES:
        return None

    existing_kot = db.scalar(
        select(ReceiptPrintJob).where(
            ReceiptPrintJob.order_id == order.id,
            ReceiptPrintJob.job_type == "kot",
            ReceiptPrintJob.is_reprint.is_(False),
        )
    )
    if existing_kot:
        return existing_kot

    receipt = db.scalar(select(Receipt).where(Receipt.order_id == order.id))
    if not receipt:
        return None

    target = "network_escpos" if settings.NETWORK_PRINTER_ENABLED else "80mm"
    kot_job = ReceiptPrintJob(
        receipt_id=receipt.id,
        order_id=order.id,
        job_type="kot",
        printer_target=target,
        printer_name="Kitchen Thermal KOT Printer",
        paper_width="80mm",
        network_host=settings.DEFAULT_PRINTER_IP if settings.NETWORK_PRINTER_ENABLED else None,
        network_port=settings.DEFAULT_PRINTER_PORT if settings.NETWORK_PRINTER_ENABLED else None,
        is_reprint=False,
        status="queued",
        requested_by_user_id=actor_user_id,
    )
    db.add(kot_job)
    db.flush()

    if settings.NETWORK_PRINTER_ENABLED and settings.DEFAULT_PRINTER_IP:
        try:
            kot_data = get_kitchen_ticket_escpos_payload(db, str(order.id), paper_width="80mm")
            raw_kot = base64.b64decode(kot_data["escpos_base64"])
            send_escpos_network_tcp(settings.DEFAULT_PRINTER_IP, settings.DEFAULT_PRINTER_PORT, raw_kot)
            kot_job.status = "completed"
        except Exception as exc:
            kot_job.status = "failed"
            kot_job.error_message = f"Auto KOT print failed: {str(exc)[:200]}"
    else:
        kot_job.status = "completed"

    record_audit_log(
        db,
        action="kitchen.kot_generated",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=actor_user_id,
        details={"print_job_id": str(kot_job.id), "status": kot_job.status},
    )
    return kot_job


def _validate_printer_host(host: str) -> str:
    clean = host.strip()
    if not clean or clean.lower() in ("localhost", "0.0.0.0"):
        raise HTTPException(status_code=400, detail="Disallowed printer host target")
    try:
        ip = ipaddress.ip_address(clean)
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
            raise HTTPException(status_code=400, detail="Disallowed printer IP range")
    except ValueError:
        pass
    return clean


def trigger_print_job(
    db: Session,
    order_id_or_number: str,
    payload: PrintReceiptRequest,
    *,
    actor_user_id: Optional[UUID],
    actor_label: str,
    is_staff: bool = False,
    staff_canteen_id: Optional[UUID] = None,
    staff_counter_id: Optional[UUID] = None,
    guest_access_token: Optional[str] = None,
) -> ReceiptPrintJob:
    order, receipt = _resolve_order_and_receipt(
        db,
        order_id_or_number,
        user_id=actor_user_id,
        is_staff=is_staff,
        staff_canteen_id=staff_canteen_id,
        staff_counter_id=staff_counter_id,
        guest_access_token=guest_access_token,
    )
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt.id).with_for_update())

    if payload.printer_target == "network_escpos" and not is_staff:
        raise HTTPException(status_code=403, detail="Only authorized canteen staff may dispatch jobs to network thermal printers")

    # First print is original if no prior completed print exists, otherwise automatically mark reprint
    prior_prints = (
        db.scalar(
            select(func.count(ReceiptPrintHistory.id)).where(
                ReceiptPrintHistory.receipt_id == receipt.id,
                ReceiptPrintHistory.status == "completed",
            )
        )
        or 0
    )
    is_reprint = payload.is_reprint or prior_prints > 0
    if is_reprint:
        receipt.reprint_count += 1

    resolved_host = _validate_printer_host(payload.network_host) if (payload.printer_target == "network_escpos" and payload.network_host) else None
    job_type = "kitchen_receipt" if payload.printer_target == "local_agent_escpos" else "customer_receipt"
    segments = build_escpos_receipt_segments(
        receipt.receipt_snapshot,
        paper_width="80mm" if payload.paper_width == "a4" else payload.paper_width,
        is_reprint=is_reprint,
        reprint_number=receipt.reprint_count,
    )
    raw_bytes = b"".join(s["bytes"] for s in segments)
    job = ReceiptPrintJob(
        receipt_id=receipt.id,
        order_id=order.id,
        canteen_id=order.canteen_id,
        job_type=job_type,
        printer_target=payload.printer_target,
        printer_name=payload.printer_name,
        paper_width=payload.paper_width,
        network_host=resolved_host,
        network_port=payload.network_port if payload.printer_target == "network_escpos" else None,
        is_reprint=is_reprint,
        status="pending" if payload.printer_target == "local_agent_escpos" else "queued",
        payload_checksum=compute_escpos_checksum(raw_bytes),
        total_bytes=len(raw_bytes),
        total_segments=len(segments),
        requested_by_user_id=actor_user_id,
    )
    db.add(job)
    db.flush()

    now = datetime.now(timezone.utc)
    if payload.printer_target == "network_escpos":
        host = resolved_host or settings.DEFAULT_PRINTER_IP
        port = payload.network_port or settings.DEFAULT_PRINTER_PORT
        if not settings.NETWORK_PRINTER_ENABLED and not payload.network_host:
            job.status = "failed"
            job.error_message = "Network thermal printer is not configured or disabled"
        else:
            try:
                send_escpos_network_tcp(host, port, raw_bytes)
                job.status = "completed"
                job.completed_at = now
                job.last_printed_segment_index = len(segments)
                job.last_printed_byte_offset = len(raw_bytes)
            except Exception as exc:
                job.status = "failed"
                job.error_message = f"Thermal printer unreachable at {host}:{port} ({exc})"
    elif payload.printer_target == "local_agent_escpos":
        job.status = "pending"
    else:
        job.status = "completed"
        job.completed_at = now

    db.add(
        ReceiptPrintHistory(
            receipt_id=receipt.id,
            print_job_id=job.id,
            printed_by_user_id=actor_user_id,
            printed_by_label=actor_label,
            printer_target=payload.printer_target,
            is_reprint=is_reprint,
            reprint_number=receipt.reprint_count if is_reprint else 0,
            status=job.status,
            printed_at=now,
        )
    )
    record_audit_log(
        db,
        action="receipt.reprinted" if is_reprint else "receipt.printed",
        entity_type="receipt",
        entity_id=receipt.receipt_number,
        actor_user_id=actor_user_id,
        details={
            "order_number": order.order_number,
            "pickup_token": receipt.pickup_token_code,
            "printer_target": payload.printer_target,
            "reprint_count": receipt.reprint_count,
            "status": job.status,
        },
    )
    db.commit()
    db.refresh(job)
    return job


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _select_kitchen_printer_for_order(db: Session, canteen_id: UUID, counter_id: Optional[UUID]) -> Optional[PrinterDevice]:
    printers = list(
        db.scalars(
            select(PrinterDevice)
            .where(PrinterDevice.canteen_id == canteen_id, PrinterDevice.department == "kitchen")
            .order_by(PrinterDevice.is_online.desc(), PrinterDevice.is_connected.desc(), PrinterDevice.created_at.asc())
        ).all()
    )
    if not printers:
        return None
    if counter_id:
        for p in printers:
            if p.counter_id == counter_id:
                return p
    return printers[0]


def ensure_kitchen_receipt_print_job(
    db: Session,
    order: Order,
    receipt: Receipt,
    *,
    payment: Optional[Payment] = None,
    actor_user_id: Optional[UUID] = None,
) -> ReceiptPrintJob:
    """
    Create ONE unique automatic kitchen thermal print job strictly after payment confirmation,
    using the EXACT SAME canonical `receipt.receipt_snapshot` (including original customer QR code).
    Never triggers for unpaid/pending/failed/cancelled orders and never duplicates across retries/webhooks.
    """
    if (
        order.payment_status != "CONFIRMED"
        or (payment is not None and payment.status != "CONFIRMED")
        or order.status in ("CREATED", "PAYMENT_PENDING", "PAYMENT_FAILED", "CANCELLED", "REJECTED")
    ):
        raise HTTPException(
            status_code=409,
            detail="Automatic kitchen printing requires verified payment confirmation",
        )

    idem_key = f"auto_kitchen_receipt:{order.id}:{payment.id if payment else receipt.id}"
    existing = db.scalar(
        select(ReceiptPrintJob).where(
            (ReceiptPrintJob.idempotency_key == idem_key)
            | (
                (ReceiptPrintJob.order_id == order.id)
                & (ReceiptPrintJob.job_type == "kitchen_receipt")
                & (ReceiptPrintJob.is_reprint.is_(False))
            )
        )
    )
    if existing:
        return existing

    printer = _select_kitchen_printer_for_order(db, order.canteen_id, order.counter_id)
    paper_width = printer.paper_width if printer else "80mm"
    segments = build_escpos_receipt_segments(
        receipt.receipt_snapshot,
        paper_width=paper_width,
        is_reprint=False,
        reprint_number=0,
    )
    raw_bytes = b"".join(s["bytes"] for s in segments)
    checksum = compute_escpos_checksum(raw_bytes)
    resume_mode = (
        "exact_offset"
        if (printer is None or printer.supports_resume_offset)
        else "controlled_reprint_continuation"
    )

    use_direct_tcp = bool(
        (printer and printer.connection_type == "network_escpos" and printer.network_host)
        or (not printer and settings.NETWORK_PRINTER_ENABLED and settings.DEFAULT_PRINTER_IP)
    )
    target = "network_escpos" if use_direct_tcp else "local_agent_escpos"
    host = (printer.network_host if printer else None) or (settings.DEFAULT_PRINTER_IP if use_direct_tcp else None)
    port = (printer.network_port if printer else None) or (settings.DEFAULT_PRINTER_PORT if use_direct_tcp else None)

    job = ReceiptPrintJob(
        receipt_id=receipt.id,
        order_id=order.id,
        canteen_id=order.canteen_id,
        payment_id=payment.id if payment else None,
        printer_device_id=printer.id if printer else None,
        job_type="kitchen_receipt",
        idempotency_key=idem_key,
        printer_target=target,
        printer_name=printer.device_name if printer else "Kitchen Thermal Printer (Auto Queue)",
        paper_width=paper_width,
        network_host=host,
        network_port=port,
        is_reprint=False,
        status="pending",
        max_retries=10,
        payload_checksum=checksum,
        total_bytes=len(raw_bytes),
        total_segments=len(segments),
        last_printed_byte_offset=0,
        last_printed_segment_index=0,
        resume_mode=resume_mode,
        requested_by_user_id=actor_user_id,
    )
    db.add(job)
    db.flush()

    now = datetime.now(timezone.utc)
    if use_direct_tcp and host:
        job.started_at = now
        try:
            tcp_res = send_escpos_segments_tcp(host, port or 9100, segments, start_segment_index=0)
            job.last_printed_segment_index = int(tcp_res.get("printed_segment_index", len(segments)))
            job.last_printed_byte_offset = int(tcp_res.get("printed_byte_offset", len(raw_bytes)))
            if tcp_res.get("status") == "paused":
                job.status = "paused"
                job.paused_reason = tcp_res.get("paused_reason", "out_of_paper")
                job.paused_at = now
                if printer:
                    printer.paper_status = "out_of_paper"
                    printer.is_online = False
                    printer.status = "paused"
                    printer.current_job_id = job.id
            else:
                job.status = "completed"
                job.completed_at = now
                if printer:
                    printer.is_connected = True
                    printer.is_online = True
                    printer.status = "online"
                    printer.current_job_id = None
                db.add(
                    ReceiptPrintHistory(
                        receipt_id=receipt.id,
                        print_job_id=job.id,
                        printed_by_user_id=actor_user_id,
                        printed_by_label=job.printer_name or "Auto Kitchen Printer",
                        printer_target=target,
                        is_reprint=False,
                        reprint_number=0,
                        status="completed",
                        printed_at=now,
                    )
                )
        except Exception as exc:
            # Keep safely retryable so paid receipt is never lost on offline printer
            job.status = "failed"
            job.error_message = f"Kitchen thermal printer unreachable at {host}:{port or 9100} ({str(exc)[:140]})"
            job.next_retry_at = now + timedelta(seconds=15)
            if printer:
                printer.is_online = False
                printer.status = "offline"
                printer.last_error = job.error_message

    record_audit_log(
        db,
        action="kitchen.receipt_auto_queued",
        entity_type="receipt",
        entity_id=receipt.receipt_number,
        actor_user_id=actor_user_id,
        details={
            "order_number": order.order_number,
            "print_job_id": str(job.id),
            "status": job.status,
            "payload_checksum": checksum,
        },
    )
    return job


def serialize_print_jobs_batch(db: Session, jobs: list[ReceiptPrintJob]) -> list[PrintJobOut]:
    if not jobs:
        return []
    order_ids = {j.order_id for j in jobs}
    receipt_ids = {j.receipt_id for j in jobs}
    orders = {o.id: o for o in db.scalars(select(Order).where(Order.id.in_(order_ids))).all()}
    receipts = {r.id: r for r in db.scalars(select(Receipt).where(Receipt.id.in_(receipt_ids))).all()}
    out: list[PrintJobOut] = []
    for j in jobs:
        o = orders.get(j.order_id)
        r = receipts.get(j.receipt_id)
        snap = r.receipt_snapshot if (r and isinstance(r.receipt_snapshot, dict)) else {}
        out.append(
            PrintJobOut(
                id=j.id,
                receipt_id=j.receipt_id,
                order_id=j.order_id,
                canteen_id=j.canteen_id or (o.canteen_id if o else None),
                payment_id=j.payment_id,
                printer_device_id=j.printer_device_id,
                order_number=o.order_number if o else snap.get("order_number"),
                pickup_token_code=(r.pickup_token_code if r else None) or snap.get("pickup_token"),
                customer_name=snap.get("customer_name"),
                total_amount=str(o.total_amount) if o else snap.get("total_paid"),
                job_type=j.job_type,
                idempotency_key=j.idempotency_key,
                printer_target=j.printer_target,
                printer_name=j.printer_name,
                paper_width=j.paper_width,
                is_reprint=j.is_reprint,
                status=j.status,
                retry_count=j.retry_count,
                max_retries=j.max_retries,
                payload_checksum=j.payload_checksum,
                total_bytes=j.total_bytes,
                total_segments=j.total_segments,
                last_printed_byte_offset=j.last_printed_byte_offset,
                last_printed_segment_index=j.last_printed_segment_index,
                resume_mode=j.resume_mode,
                paused_reason=j.paused_reason,
                paused_at=j.paused_at,
                started_at=j.started_at,
                completed_at=j.completed_at,
                next_retry_at=j.next_retry_at,
                claimed_by_agent=j.claimed_by_agent,
                error_message=j.error_message,
                created_at=j.created_at,
            )
        )
    return out


def serialize_print_job(db: Session, job: ReceiptPrintJob) -> PrintJobOut:
    return serialize_print_jobs_batch(db, [job])[0]


def register_printer_device(
    db: Session,
    payload: PrinterDeviceCreateRequest,
    *,
    actor_user_id: UUID,
) -> tuple[PrinterDeviceOut, str, str]:
    canteen = db.get(Canteen, payload.canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")
    if payload.connection_type == "network_escpos" and payload.network_host:
        _validate_printer_host(payload.network_host)

    agent_id = payload.agent_id or f"cb-kitchen-{canteen.slug}-{secrets.token_hex(4)}"
    if db.scalar(select(PrinterDevice).where(PrinterDevice.agent_id == agent_id)):
        raise HTTPException(status_code=409, detail=f"Printer agent_id '{agent_id}' is already registered")

    raw_token = f"cbpa_{secrets.token_urlsafe(32)}"
    printer = PrinterDevice(
        canteen_id=payload.canteen_id,
        counter_id=payload.counter_id,
        department=payload.department,
        device_name=payload.device_name.strip(),
        agent_id=agent_id,
        agent_token_hash=sha256_hex(raw_token),
        connection_type=payload.connection_type,
        network_host=payload.network_host,
        network_port=payload.network_port if payload.connection_type == "network_escpos" else None,
        paper_width=payload.paper_width,
        status="offline",
        is_connected=False,
        is_online=False,
        paper_status="unknown",
        supports_realtime_status=payload.supports_realtime_status,
        supports_resume_offset=payload.supports_resume_offset,
    )
    db.add(printer)
    db.flush()
    record_audit_log(
        db,
        action="printer.registered",
        entity_type="printer_device",
        entity_id=agent_id,
        actor_user_id=actor_user_id,
        details={"canteen_id": str(payload.canteen_id), "device_name": printer.device_name, "connection_type": printer.connection_type},
    )
    db.commit()
    db.refresh(printer)
    return _serialize_printer_device(db, printer), agent_id, raw_token


def authenticate_print_agent(db: Session, agent_id: Optional[str], agent_token: Optional[str]) -> PrinterDevice:
    if not agent_id or not agent_token:
        raise HTTPException(status_code=401, detail="Print agent credentials required (X-Print-Agent-Id & X-Print-Agent-Token)")
    printer = db.scalar(select(PrinterDevice).where(PrinterDevice.agent_id == agent_id.strip()))
    if not printer:
        raise HTTPException(status_code=401, detail="Unknown print agent")
    if not hmac.compare_digest(printer.agent_token_hash, sha256_hex(agent_token.strip())):
        raise HTTPException(status_code=401, detail="Invalid print agent token")
    return printer


def _serialize_printer_device(db: Session, printer: PrinterDevice) -> PrinterDeviceOut:
    now = datetime.now(timezone.utc)
    hb = _as_utc(printer.last_heartbeat_at)
    is_stale = bool(printer.connection_type != "network_escpos" and hb is not None and (now - hb) > timedelta(seconds=60))
    effective_connected = False if is_stale else bool(printer.is_connected)
    effective_online = False if is_stale else bool(printer.is_online)
    effective_status = "offline" if is_stale else printer.status

    current_order_no: Optional[str] = None
    if printer.current_job_id:
        cur_job = db.get(ReceiptPrintJob, printer.current_job_id)
        if cur_job:
            cur_ord = db.get(Order, cur_job.order_id)
            current_order_no = cur_ord.order_number if cur_ord else None

    return PrinterDeviceOut(
        id=printer.id,
        canteen_id=printer.canteen_id,
        counter_id=printer.counter_id,
        department=printer.department,
        device_name=printer.device_name,
        agent_id=printer.agent_id,
        connection_type=printer.connection_type,
        network_host=printer.network_host,
        network_port=printer.network_port,
        paper_width=printer.paper_width,
        status=effective_status,
        is_connected=effective_connected,
        is_online=effective_online,
        paper_status=printer.paper_status,
        supports_realtime_status=printer.supports_realtime_status,
        supports_resume_offset=printer.supports_resume_offset,
        current_job_id=printer.current_job_id,
        current_order_number=current_order_no,
        last_heartbeat_at=printer.last_heartbeat_at,
        last_error=printer.last_error,
        created_at=printer.created_at,
        updated_at=printer.updated_at,
    )


def _auto_restore_jobs_when_printer_ready(db: Session, printer: PrinterDevice, now: datetime) -> int:
    """When paper is reloaded or printer comes back online, auto-unlock paused/retryable kitchen jobs."""
    if not (printer.is_connected and printer.is_online and printer.paper_status in ("available", "low")):
        return 0
    restored = 0
    paused_jobs = db.scalars(
        select(ReceiptPrintJob).where(
            ReceiptPrintJob.canteen_id == printer.canteen_id,
            ReceiptPrintJob.job_type == "kitchen_receipt",
            ReceiptPrintJob.status == "paused",
        )
    ).all()
    for job in paused_jobs:
        job.status = "pending"
        job.paused_reason = None
        job.next_retry_at = now
        job.error_message = None
        restored += 1

    failed_jobs = db.scalars(
        select(ReceiptPrintJob).where(
            ReceiptPrintJob.canteen_id == printer.canteen_id,
            ReceiptPrintJob.job_type == "kitchen_receipt",
            ReceiptPrintJob.status == "failed",
            ReceiptPrintJob.retry_count < ReceiptPrintJob.max_retries,
        )
    ).all()
    for job in failed_jobs:
        job.next_retry_at = now
        restored += 1
    return restored


def process_agent_heartbeat(db: Session, printer: PrinterDevice, payload: AgentHeartbeatRequest) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    printer.is_connected = payload.is_connected
    printer.is_online = payload.is_online
    printer.paper_status = payload.paper_status
    if payload.supports_realtime_status is not None:
        printer.supports_realtime_status = payload.supports_realtime_status
    if payload.supports_resume_offset is not None:
        printer.supports_resume_offset = payload.supports_resume_offset
    if payload.current_job_id is not None:
        printer.current_job_id = payload.current_job_id
    printer.last_heartbeat_at = now
    printer.last_error = payload.last_error

    if payload.status:
        printer.status = payload.status
    elif payload.paper_status == "out_of_paper":
        printer.status = "paused"
    elif payload.is_connected and payload.is_online:
        printer.status = "online"
    else:
        printer.status = "offline"

    restored_count = _auto_restore_jobs_when_printer_ready(db, printer, now)
    db.commit()
    db.refresh(printer)
    return {
        "printer": _serialize_printer_device(db, printer).model_dump(mode="json"),
        "restored_jobs_count": restored_count,
        "server_time": now.isoformat(),
    }


def _build_agent_job_payload(db: Session, printer: PrinterDevice, job: ReceiptPrintJob) -> dict[str, Any]:
    receipt = db.get(Receipt, job.receipt_id)
    order = db.get(Order, job.order_id)
    if not receipt or not order:
        raise HTTPException(status_code=404, detail="Receipt or order missing for print job")
    if order.payment_status != "CONFIRMED":
        raise HTTPException(status_code=409, detail="Refusing to dispatch unpaid order receipt")

    paper_width = printer.paper_width or job.paper_width or "80mm"
    reprint_num = receipt.reprint_count if job.is_reprint else 0
    segments = build_escpos_receipt_segments(
        receipt.receipt_snapshot,
        paper_width=paper_width,
        is_reprint=bool(job.is_reprint),
        reprint_number=reprint_num,
    )
    raw_bytes = b"".join(s["bytes"] for s in segments)
    checksum = compute_escpos_checksum(raw_bytes)
    job.payload_checksum = checksum
    job.total_bytes = len(raw_bytes)
    job.total_segments = len(segments)

    supports_exact = bool(printer.supports_resume_offset and job.resume_mode == "exact_offset")
    if supports_exact and 0 <= job.last_printed_segment_index < len(segments):
        resume_seg = job.last_printed_segment_index
        resume_byte = job.last_printed_byte_offset
        effective_mode = "exact_offset"
    else:
        resume_seg = 0
        resume_byte = 0
        effective_mode = "controlled_reprint_continuation" if job.last_printed_segment_index > 0 else "exact_offset"

    return {
        "job": serialize_print_job(db, job).model_dump(mode="json"),
        "order_number": order.order_number,
        "pickup_token_code": receipt.pickup_token_code,
        "paper_width": paper_width,
        "payload_checksum": checksum,
        "receipt_snapshot": receipt.receipt_snapshot,
        "escpos_base64": base64.b64encode(raw_bytes).decode("ascii"),
        "segments": [
            {
                "index": s["index"],
                "name": s["name"],
                "byte_start": s["byte_start"],
                "byte_end": s["byte_end"],
                "byte_length": s["byte_length"],
                "base64_bytes": s["base64_bytes"],
            }
            for s in segments
        ],
        "resume_mode": effective_mode,
        "resume_from_segment_index": resume_seg,
        "resume_from_byte_offset": resume_byte,
    }


def claim_next_kitchen_print_job(db: Session, printer: PrinterDevice) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    printer.last_heartbeat_at = now
    if not (printer.is_connected and printer.is_online):
        db.commit()
        return {"claimed": False, "reason": "printer_offline"}
    if printer.paper_status == "out_of_paper":
        db.commit()
        return {"claimed": False, "reason": "out_of_paper"}

    stale_cutoff = now - timedelta(seconds=120)
    candidates = list(
        db.scalars(
            select(ReceiptPrintJob)
            .where(
                ReceiptPrintJob.canteen_id == printer.canteen_id,
                ReceiptPrintJob.job_type == "kitchen_receipt",
                ReceiptPrintJob.status.in_(("pending", "queued", "failed", "printing")),
            )
            .order_by(ReceiptPrintJob.created_at.asc())
            .with_for_update()
            .limit(20)
        ).all()
    )

    chosen: Optional[ReceiptPrintJob] = None
    for cand in candidates:
        if cand.status in ("pending", "queued"):
            chosen = cand
            break
        if cand.status == "printing":
            started = _as_utc(cand.started_at)
            if started and started <= stale_cutoff:
                cand.retry_count += 1
                chosen = cand
                break
        if cand.status == "failed" and cand.retry_count < cand.max_retries:
            nra = _as_utc(cand.next_retry_at)
            if nra is None or nra <= now:
                cand.retry_count += 1
                chosen = cand
                break

    if not chosen:
        db.commit()
        return {"claimed": False, "reason": "queue_empty"}

    ord_row = db.get(Order, chosen.order_id)
    if not ord_row or ord_row.payment_status != "CONFIRMED":
        chosen.status = "failed"
        chosen.error_message = "Blocked unpaid order from kitchen print dispatch"
        db.commit()
        return {"claimed": False, "reason": "unpaid_blocked"}

    chosen.status = "printing"
    chosen.started_at = now
    chosen.claimed_by_agent = printer.agent_id
    chosen.printer_device_id = printer.id
    chosen.error_message = None
    printer.current_job_id = chosen.id
    payload = _build_agent_job_payload(db, printer, chosen)
    db.commit()
    return {"claimed": True, **payload}


def checkpoint_agent_job_progress(
    db: Session, printer: PrinterDevice, job_id: UUID, payload: AgentJobProgressRequest
) -> PrintJobOut:
    job = db.get(ReceiptPrintJob, job_id)
    if not job or job.canteen_id != printer.canteen_id:
        raise HTTPException(status_code=404, detail="Print job not found")
    job.last_printed_segment_index = max(job.last_printed_segment_index, payload.printed_segment_index)
    job.last_printed_byte_offset = max(job.last_printed_byte_offset, payload.printed_byte_offset)
    if not payload.supports_resume_offset:
        job.resume_mode = "controlled_reprint_continuation"
    db.commit()
    db.refresh(job)
    return serialize_print_job(db, job)


def pause_agent_job(db: Session, printer: PrinterDevice, job_id: UUID, payload: AgentJobPauseRequest) -> PrintJobOut:
    now = datetime.now(timezone.utc)
    job = db.get(ReceiptPrintJob, job_id)
    if not job or job.canteen_id != printer.canteen_id:
        raise HTTPException(status_code=404, detail="Print job not found")

    job.status = "paused"
    job.paused_reason = payload.reason
    job.paused_at = now
    job.last_printed_segment_index = max(job.last_printed_segment_index, payload.printed_segment_index)
    job.last_printed_byte_offset = max(job.last_printed_byte_offset, payload.printed_byte_offset)
    if not payload.supports_resume_offset:
        job.resume_mode = "controlled_reprint_continuation"
    job.error_message = f"Paused: {payload.reason}"

    printer.is_connected = payload.is_connected
    printer.is_online = payload.is_online
    printer.paper_status = payload.paper_status
    printer.status = "paused"
    printer.current_job_id = job.id
    printer.last_heartbeat_at = now
    printer.last_error = job.error_message

    record_audit_log(
        db,
        action="kitchen.print_paused",
        entity_type="receipt_print_job",
        entity_id=str(job.id),
        details={
            "reason": payload.reason,
            "printed_segment_index": job.last_printed_segment_index,
            "printed_byte_offset": job.last_printed_byte_offset,
            "resume_mode": job.resume_mode,
        },
    )
    db.commit()
    db.refresh(job)
    return serialize_print_job(db, job)


def complete_agent_job(db: Session, printer: PrinterDevice, job_id: UUID, payload: AgentJobCompleteRequest) -> PrintJobOut:
    now = datetime.now(timezone.utc)
    job = db.get(ReceiptPrintJob, job_id)
    if not job or job.canteen_id != printer.canteen_id:
        raise HTTPException(status_code=404, detail="Print job not found")
    receipt = db.get(Receipt, job.receipt_id)

    job.status = "completed"
    job.completed_at = now
    job.paused_reason = None
    job.error_message = None
    job.last_printed_segment_index = (
        payload.printed_segment_index if payload.printed_segment_index is not None else job.total_segments
    )
    job.last_printed_byte_offset = (
        payload.printed_byte_offset if payload.printed_byte_offset is not None else job.total_bytes
    )
    if printer.current_job_id == job.id:
        printer.current_job_id = None
    printer.status = "online"
    printer.is_online = True
    printer.is_connected = True
    printer.last_heartbeat_at = now
    printer.last_error = None

    if receipt:
        db.add(
            ReceiptPrintHistory(
                receipt_id=receipt.id,
                print_job_id=job.id,
                printed_by_user_id=job.requested_by_user_id,
                printed_by_label=payload.printed_by_label or printer.device_name,
                printer_target=job.printer_target,
                is_reprint=job.is_reprint,
                reprint_number=receipt.reprint_count if job.is_reprint else 0,
                status="completed",
                printed_at=now,
            )
        )
    db.commit()
    db.refresh(job)
    return serialize_print_job(db, job)


def fail_agent_job(db: Session, printer: PrinterDevice, job_id: UUID, payload: AgentJobFailRequest) -> PrintJobOut:
    now = datetime.now(timezone.utc)
    job = db.get(ReceiptPrintJob, job_id)
    if not job or job.canteen_id != printer.canteen_id:
        raise HTTPException(status_code=404, detail="Print job not found")

    job.last_printed_segment_index = max(job.last_printed_segment_index, payload.printed_segment_index)
    job.last_printed_byte_offset = max(job.last_printed_byte_offset, payload.printed_byte_offset)
    job.error_message = payload.error_message[:255]

    if payload.printer_offline:
        # Keep in queue cleanly without wasting retry budget while offline
        job.status = "pending"
        job.next_retry_at = now + timedelta(seconds=payload.retry_delay_seconds)
        printer.is_online = False
        printer.status = "offline"
    else:
        job.status = "failed"
        job.next_retry_at = now + timedelta(seconds=payload.retry_delay_seconds)
        printer.status = "error"
    if printer.current_job_id == job.id:
        printer.current_job_id = None
    printer.last_heartbeat_at = now
    printer.last_error = job.error_message
    db.commit()
    db.refresh(job)
    return serialize_print_job(db, job)


def resume_paused_print_job(db: Session, job_id: UUID, actor_user_id: UUID, actor_label: str) -> PrintJobOut:
    job = db.get(ReceiptPrintJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Print job not found")
    return retry_print_job(db, job_id, actor_user_id, actor_label)


def trigger_kitchen_reprint(
    db: Session,
    order_id_or_number: str,
    *,
    actor_user_id: UUID,
    actor_label: str,
    staff_canteen_id: Optional[UUID] = None,
    paper_width: Optional[str] = None,
) -> PrintJobOut:
    """Controlled reprint of the EXACT SAME customer receipt for kitchen recovery."""
    order, receipt = _resolve_order_and_receipt(
        db,
        order_id_or_number,
        is_staff=True,
        staff_canteen_id=staff_canteen_id,
    )
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt.id).with_for_update())
    receipt.reprint_count += 1

    printer = _select_kitchen_printer_for_order(db, order.canteen_id, order.counter_id)
    width = paper_width or (printer.paper_width if printer else "80mm")
    segments = build_escpos_receipt_segments(
        receipt.receipt_snapshot,
        paper_width="80mm" if width == "a4" else width,
        is_reprint=True,
        reprint_number=receipt.reprint_count,
    )
    raw_bytes = b"".join(s["bytes"] for s in segments)
    checksum = compute_escpos_checksum(raw_bytes)
    use_direct_tcp = bool(
        (printer and printer.connection_type == "network_escpos" and printer.network_host)
        or (not printer and settings.NETWORK_PRINTER_ENABLED and settings.DEFAULT_PRINTER_IP)
    )
    target = "network_escpos" if use_direct_tcp else "local_agent_escpos"
    host = (printer.network_host if printer else None) or (settings.DEFAULT_PRINTER_IP if use_direct_tcp else None)
    port = (printer.network_port if printer else None) or (settings.DEFAULT_PRINTER_PORT if use_direct_tcp else None)

    job = ReceiptPrintJob(
        receipt_id=receipt.id,
        order_id=order.id,
        canteen_id=order.canteen_id,
        printer_device_id=printer.id if printer else None,
        job_type="kitchen_receipt",
        printer_target=target,
        printer_name=printer.device_name if printer else "Kitchen Thermal Printer",
        paper_width="80mm" if width == "a4" else width,
        network_host=host,
        network_port=port,
        is_reprint=True,
        status="pending",
        max_retries=10,
        payload_checksum=checksum,
        total_bytes=len(raw_bytes),
        total_segments=len(segments),
        resume_mode="exact_offset",
        requested_by_user_id=actor_user_id,
    )
    db.add(job)
    db.flush()

    now = datetime.now(timezone.utc)
    if use_direct_tcp and host:
        job.started_at = now
        try:
            tcp_res = send_escpos_segments_tcp(host, port or 9100, segments, start_segment_index=0)
            job.last_printed_segment_index = int(tcp_res.get("printed_segment_index", len(segments)))
            job.last_printed_byte_offset = int(tcp_res.get("printed_byte_offset", len(raw_bytes)))
            if tcp_res.get("status") == "paused":
                job.status = "paused"
                job.paused_reason = "out_of_paper"
                job.paused_at = now
            else:
                job.status = "completed"
                job.completed_at = now
                db.add(
                    ReceiptPrintHistory(
                        receipt_id=receipt.id,
                        print_job_id=job.id,
                        printed_by_user_id=actor_user_id,
                        printed_by_label=actor_label,
                        printer_target=target,
                        is_reprint=True,
                        reprint_number=receipt.reprint_count,
                        status="completed",
                        printed_at=now,
                    )
                )
        except Exception as exc:
            job.status = "failed"
            job.error_message = f"Controlled reprint queued/failed: {str(exc)[:180]}"
            job.next_retry_at = now + timedelta(seconds=15)

    record_audit_log(
        db,
        action="kitchen.receipt_reprinted",
        entity_type="receipt",
        entity_id=receipt.receipt_number,
        actor_user_id=actor_user_id,
        details={"order_number": order.order_number, "reprint_count": receipt.reprint_count, "print_job_id": str(job.id)},
    )
    db.commit()
    db.refresh(job)
    return serialize_print_job(db, job)


def process_retryable_network_print_jobs(db: Session) -> dict[str, int]:
    """Retry any pending/failed direct-TCP print jobs on cron/startup without losing paid orders."""
    now = datetime.now(timezone.utc)
    jobs = list(
        db.scalars(
            select(ReceiptPrintJob)
            .where(
                ReceiptPrintJob.printer_target == "network_escpos",
                ReceiptPrintJob.status.in_(("pending", "failed")),
                ReceiptPrintJob.retry_count < ReceiptPrintJob.max_retries,
            )
            .order_by(ReceiptPrintJob.created_at.asc())
            .limit(25)
        ).all()
    )
    completed = 0
    paused = 0
    failed = 0
    for job in jobs:
        nra = _as_utc(job.next_retry_at)
        if nra and nra > now:
            continue
        receipt = db.get(Receipt, job.receipt_id)
        order = db.get(Order, job.order_id)
        if not receipt or not order or order.payment_status != "CONFIRMED":
            continue
        host = job.network_host or settings.DEFAULT_PRINTER_IP
        port = job.network_port or settings.DEFAULT_PRINTER_PORT or 9100
        if not host:
            continue
        segments = build_escpos_receipt_segments(
            receipt.receipt_snapshot,
            paper_width="80mm" if job.paper_width == "a4" else job.paper_width,
            is_reprint=job.is_reprint,
            reprint_number=receipt.reprint_count if job.is_reprint else 0,
        )
        start_seg = job.last_printed_segment_index if job.resume_mode == "exact_offset" else 0
        job.retry_count += 1
        try:
            res = send_escpos_segments_tcp(host, port, segments, start_segment_index=start_seg)
            job.last_printed_segment_index = int(res.get("printed_segment_index", len(segments)))
            job.last_printed_byte_offset = int(res.get("printed_byte_offset", job.total_bytes))
            if res.get("status") == "paused":
                job.status = "paused"
                job.paused_reason = "out_of_paper"
                job.paused_at = now
                paused += 1
            else:
                job.status = "completed"
                job.completed_at = now
                job.error_message = None
                completed += 1
                db.add(
                    ReceiptPrintHistory(
                        receipt_id=receipt.id,
                        print_job_id=job.id,
                        printed_by_user_id=job.requested_by_user_id,
                        printed_by_label=job.printer_name or "Auto Retry Worker",
                        printer_target=job.printer_target,
                        is_reprint=job.is_reprint,
                        reprint_number=receipt.reprint_count if job.is_reprint else 0,
                        status="completed",
                        printed_at=now,
                    )
                )
        except Exception as exc:
            job.status = "failed"
            job.error_message = f"Auto-retry #{job.retry_count}: {str(exc)[:180]}"
            job.next_retry_at = now + timedelta(seconds=min(300, 15 * (2 ** min(job.retry_count, 4))))
            failed += 1
    return {"checked": len(jobs), "completed": completed, "paused": paused, "failed": failed}


def build_kitchen_print_dashboard(
    db: Session,
    canteen_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    limit: int = 100,
) -> dict[str, Any]:
    printer_stmt = select(PrinterDevice).where(PrinterDevice.department == "kitchen").order_by(PrinterDevice.created_at.asc())
    if canteen_id:
        printer_stmt = printer_stmt.where(PrinterDevice.canteen_id == canteen_id)
    printers = [_serialize_printer_device(db, p) for p in db.scalars(printer_stmt).all()]

    base_stmt = select(ReceiptPrintJob).where(ReceiptPrintJob.job_type == "kitchen_receipt")
    if canteen_id:
        base_stmt = base_stmt.where(ReceiptPrintJob.canteen_id == canteen_id)
    all_kitchen_jobs = list(db.scalars(base_stmt.order_by(ReceiptPrintJob.created_at.desc()).limit(250)).all())

    pending_cnt = sum(1 for j in all_kitchen_jobs if j.status in ("pending", "queued"))
    printing_cnt = sum(1 for j in all_kitchen_jobs if j.status == "printing")
    paused_cnt = sum(1 for j in all_kitchen_jobs if j.status == "paused")
    completed_cnt = sum(1 for j in all_kitchen_jobs if j.status == "completed")
    failed_cnt = sum(1 for j in all_kitchen_jobs if j.status == "failed")

    printing_job = next((j for j in all_kitchen_jobs if j.status == "printing"), None)
    cur_order_no = None
    cur_token = None
    if printing_job:
        co = db.get(Order, printing_job.order_id)
        cr = db.get(Receipt, printing_job.receipt_id)
        cur_order_no = co.order_number if co else None
        cur_token = cr.pickup_token_code if cr else None

    filtered_jobs = [j for j in all_kitchen_jobs if not status_filter or j.status == status_filter][: max(1, min(limit, 200))]
    return {
        "canteen_id": canteen_id,
        "printers": printers,
        "summary": {
            "total_jobs": len(all_kitchen_jobs),
            "pending_count": pending_cnt,
            "printing_count": printing_cnt,
            "paused_count": paused_cnt,
            "completed_count": completed_cnt,
            "failed_count": failed_cnt,
            "currently_printing_order": cur_order_no,
            "currently_printing_token": cur_token,
            "online_printers": sum(1 for p in printers if p.is_online),
            "total_printers": len(printers),
            "out_of_paper_printers": sum(1 for p in printers if p.paper_status == "out_of_paper"),
        },
        "jobs": serialize_print_jobs_batch(db, filtered_jobs),
    }


def retry_print_job(db: Session, job_id: UUID, actor_user_id: UUID, actor_label: str) -> PrintJobOut:
    job = db.get(ReceiptPrintJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Print job not found")
    receipt = db.get(Receipt, job.receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")
    order = db.get(Order, job.order_id)
    if not order or order.payment_status != "CONFIRMED":
        raise HTTPException(status_code=409, detail="Cannot retry print job for an unpaid order")

    now = datetime.now(timezone.utc)
    job.retry_count += 1

    if job.printer_target == "network_escpos":
        host = job.network_host or settings.DEFAULT_PRINTER_IP
        port = job.network_port or settings.DEFAULT_PRINTER_PORT or 9100
        try:
            segments = build_escpos_receipt_segments(
                receipt.receipt_snapshot,
                paper_width="80mm" if job.paper_width == "a4" else job.paper_width,
                is_reprint=job.is_reprint,
                reprint_number=receipt.reprint_count if job.is_reprint else 0,
            )
            start_seg = job.last_printed_segment_index if (job.resume_mode == "exact_offset" and job.last_printed_segment_index > 0) else 0
            tcp_res = send_escpos_segments_tcp(host, port, segments, start_segment_index=start_seg)
            job.last_printed_segment_index = int(tcp_res.get("printed_segment_index", len(segments)))
            job.last_printed_byte_offset = int(tcp_res.get("printed_byte_offset", job.total_bytes))
            if tcp_res.get("status") == "paused":
                job.status = "paused"
                job.paused_reason = "out_of_paper"
                job.paused_at = now
                job.error_message = "Paused: out of paper"
            else:
                job.status = "completed"
                job.completed_at = now
                job.paused_reason = None
                job.error_message = None
        except Exception as exc:
            job.status = "failed"
            job.error_message = f"Retry #{job.retry_count} failed: {str(exc)[:180]}"
            job.next_retry_at = now + timedelta(seconds=15)
    elif job.printer_target == "local_agent_escpos":
        # Re-queue cleanly for the kitchen local print agent, preserving exact checkpoint offset
        job.status = "pending"
        job.paused_reason = None
        job.error_message = None
        job.next_retry_at = now
    else:
        job.status = "completed"
        job.completed_at = now
        job.error_message = None

    if job.status == "completed":
        db.add(
            ReceiptPrintHistory(
                receipt_id=receipt.id,
                print_job_id=job.id,
                printed_by_user_id=actor_user_id,
                printed_by_label=actor_label,
                printer_target=job.printer_target,
                is_reprint=job.is_reprint,
                reprint_number=receipt.reprint_count if job.is_reprint else 0,
                status="completed",
                printed_at=now,
            )
        )
    db.commit()
    db.refresh(job)
    return serialize_print_job(db, job)
