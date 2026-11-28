from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http_cache import set_private_no_store
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_current_principal,
    get_optional_principal,
    require_roles,
)
from app.core.security import sha256_hex
from app.models.order import Order
from app.services import invoice_service

router = APIRouter(prefix="/invoices", tags=["Billing & Tax Invoices"])

INVOICE_STAFF_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER)


@router.get("")
def list_all_invoices(
    canteen_id: Optional[UUID] = Query(default=None),
    invoice_type: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*INVOICE_STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    if canteen_id:
        enforce_canteen_scope(principal, canteen_id)
    elif principal.assigned_canteen_id and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        canteen_id = principal.assigned_canteen_id
    return invoice_service.list_invoices(db, canteen_id=canteen_id, invoice_type=invoice_type)


@router.get("/my")
def list_my_invoices(
    response: Response,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    set_private_no_store(response)
    return invoice_service.list_invoices(db, customer_user_id=principal.user.id)


def _authorize_invoice_access(
    db: Session,
    inv,
    principal: Optional[AuthenticatedPrincipal],
    guest_access_token: Optional[str],
) -> None:
    if principal:
        if principal.has_role(*INVOICE_STAFF_ROLES):
            if principal.assigned_canteen_id and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
                if inv.canteen_id and inv.canteen_id != principal.assigned_canteen_id:
                    raise HTTPException(status_code=403, detail="Invoice belongs to a different canteen")
            return
        if inv.customer_user_id and inv.customer_user_id == principal.user.id:
            return
        raise HTTPException(status_code=403, detail="Not authorized to access this invoice")
    if inv.order_id and guest_access_token:
        order = db.get(Order, inv.order_id)
        if order and order.is_guest and order.guest_access_token_hash == sha256_hex(guest_access_token):
            return
        raise HTTPException(status_code=403, detail="Valid guest access token required")
    raise HTTPException(status_code=401, detail="Authentication required to access this invoice")


@router.get("/{id_or_number}")
def get_invoice(
    id_or_number: str,
    response: Response,
    guest_access_token: Optional[str] = Query(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    set_private_no_store(response)
    inv = invoice_service.resolve_invoice(db, id_or_number)
    _authorize_invoice_access(db, inv, principal, guest_access_token)
    return invoice_service.serialize_invoice(inv)


@router.get("/{id_or_number}/pdf")
def download_invoice_pdf(
    id_or_number: str,
    guest_access_token: Optional[str] = Query(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    inv = invoice_service.resolve_invoice(db, id_or_number)
    _authorize_invoice_access(db, inv, principal, guest_access_token)
    pdf_bytes = invoice_service.render_invoice_pdf(db, inv)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{inv.invoice_number}.pdf"',
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )
