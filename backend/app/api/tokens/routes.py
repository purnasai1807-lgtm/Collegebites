from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.http_cache import set_private_no_store
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_current_principal,
    get_optional_principal,
    require_roles,
    scoped_counter_for_principal,
)
from app.core.security import generate_signed_qr_token
from app.models.order import Order
from app.models.payment import OrderQRCode, PickupToken, Receipt
from app.services import receipt_service
from app.services.audit_service import record_audit_log
from app.services.qr_location_service import render_qr_png_bytes

router = APIRouter(prefix="/tokens", tags=["Tokens, QR & Receipts"])

STAFF_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
)


def _staff_cid(principal: Optional[AuthenticatedPrincipal]) -> Optional[UUID]:
    if not principal or not principal.has_role(*STAFF_ROLES):
        return None
    if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        return None
    return principal.assigned_canteen_id


@router.get("/receipts/my")
def list_my_receipts(
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    set_private_no_store(response)
    return receipt_service.list_my_receipts(
        db,
        user_id=principal.user.id,
        limit=limit,
        offset=offset,
    )


@router.get("/receipts/{order_id_or_number}")
def get_receipt(
    order_id_or_number: str,
    response: Response,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    set_private_no_store(response)
    is_staff = bool(principal and principal.has_role(*STAFF_ROLES))
    return receipt_service.get_receipt_payload(
        db,
        order_id_or_number,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        staff_canteen_id=_staff_cid(principal),
        staff_counter_id=scoped_counter_for_principal(principal) if is_staff else None,
        guest_access_token=guest_token or x_guest_token,
    )


@router.get("/receipts/{order_id_or_number}/pdf")
def download_receipt_pdf(
    order_id_or_number: str,
    format: str = Query(default="a4", pattern="^(a4|80mm|58mm)$"),
    reprint: bool = Query(default=False),
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(*STAFF_ROLES))
    pdf_bytes, order_num = receipt_service.generate_receipt_pdf_bytes(
        db,
        order_id_or_number,
        paper_format=format,
        is_reprint_view=reprint,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        staff_canteen_id=_staff_cid(principal),
        staff_counter_id=scoped_counter_for_principal(principal) if is_staff else None,
        guest_access_token=guest_token or x_guest_token,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=CollegeBites-{order_num}.pdf",
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.get("/receipts/{order_id_or_number}/qr.png")
def download_order_qr_png(
    order_id_or_number: str,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    is_staff = bool(principal and principal.has_role(*STAFF_ROLES))
    snap = receipt_service.get_receipt_payload(
        db,
        order_id_or_number,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        staff_canteen_id=_staff_cid(principal),
        staff_counter_id=scoped_counter_for_principal(principal) if is_staff else None,
        guest_access_token=guest_token or x_guest_token,
    )
    png_bytes = render_qr_png_bytes(snap["qr_payload"], box_size=10)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache"},
    )


class RevokeOrderQRIn(BaseModel):
    reason: str = Field(default="Revoked by canteen administration", min_length=3, max_length=255)
    reissue: bool = True


@router.post("/orders/{order_id}/revoke-qr")
def revoke_or_reissue_order_qr(
    order_id: UUID,
    payload: RevokeOrderQRIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    enforce_canteen_scope(principal, order.canteen_id)
    qr_row = db.scalar(select(OrderQRCode).where(OrderQRCode.order_id == order.id).with_for_update())
    if not qr_row:
        raise HTTPException(status_code=404, detail="Order QR not found")

    if payload.reissue:
        raw_qr, tok_hash = generate_signed_qr_token()
        vpath = f"/pickup/verify#token={raw_qr}"
        qr_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}{vpath}"
        qr_row.token_hash = tok_hash
        qr_row.verification_path = vpath
        qr_row.qr_payload_encoded = qr_url
        qr_row.revoked_at = None
        qr_row.revocation_reason = f"Reissued: {payload.reason}"
        receipt = db.scalar(select(Receipt).where(Receipt.order_id == order.id))
        if receipt and isinstance(receipt.receipt_snapshot, dict):
            snap = dict(receipt.receipt_snapshot)
            snap["qr_verification_path"] = vpath
            snap["qr_payload"] = qr_url
            receipt.receipt_snapshot = snap
    else:
        qr_row.revoked_at = datetime.now(timezone.utc)
        qr_row.revocation_reason = payload.reason
        tok = db.scalar(select(PickupToken).where(PickupToken.order_id == order.id))
        if tok:
            tok.status = "REVOKED"

    record_audit_log(
        db,
        action="order_qr.reissued" if payload.reissue else "order_qr.revoked",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=principal.user.id,
        details={"reason": payload.reason},
    )
    db.commit()
    from app.websockets import emit_order_event_sync
    emit_order_event_sync(
        str(order.canteen_id),
        str(order.id),
        "order.qr_updated",
        {"order_number": order.order_number, "reissued": payload.reissue},
    )
    return {"order_number": order.order_number, "reissued": payload.reissue, "qr_payload": qr_row.qr_payload_encoded}
