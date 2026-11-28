from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http_cache import set_private_no_store
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_KITCHEN_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_optional_principal,
    require_roles,
    scoped_canteen_for_principal,
    scoped_counter_for_principal,
)
from app.models.order import Order
from app.models.payment import ReceiptPrintHistory, ReceiptPrintJob
from app.schemas.payment import (
    AgentHeartbeatRequest,
    AgentJobCompleteRequest,
    AgentJobFailRequest,
    AgentJobPauseRequest,
    AgentJobProgressRequest,
    KitchenPrintDashboardOut,
    PrintHistoryOut,
    PrintJobOut,
    PrintReceiptRequest,
    PrinterDeviceCreateRequest,
    PrinterRegistrationOut,
)
from app.services import receipt_service

router = APIRouter(prefix="/printing", tags=["Receipt & Thermal Printing"])

STAFF_PRINT_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_CASHIER, ROLE_KITCHEN_STAFF)
KOT_PRINT_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER, ROLE_KITCHEN_STAFF, ROLE_CASHIER)


def _print_staff_cid(principal: Optional[AuthenticatedPrincipal]) -> Optional[UUID]:
    if not principal or not principal.has_role(*STAFF_PRINT_ROLES):
        return None
    if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        return None
    return principal.assigned_canteen_id


@router.get("/receipts/{order_id_or_number}/escpos")
def get_escpos_receipt(
    order_id_or_number: str,
    response: Response,
    width: str = Query(default="80mm", pattern="^(58mm|80mm)$"),
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    set_private_no_store(response)
    is_staff = bool(principal and principal.has_role(*STAFF_PRINT_ROLES))
    return receipt_service.get_escpos_payload(
        db,
        order_id_or_number,
        paper_width=width,
        user_id=principal.user.id if principal else None,
        is_staff=is_staff,
        staff_canteen_id=_print_staff_cid(principal),
        staff_counter_id=scoped_counter_for_principal(principal) if is_staff else None,
        guest_access_token=guest_token or x_guest_token,
    )


@router.get("/kitchen-ticket/{order_id_or_number}/escpos")
def get_escpos_kitchen_ticket(
    order_id_or_number: str,
    response: Response,
    width: str = Query(default="80mm", pattern="^(58mm|80mm)$"),
    station_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*KOT_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    set_private_no_store(response)
    scoped_cid = scoped_canteen_for_principal(principal, None)
    return receipt_service.get_kitchen_ticket_escpos_payload(
        db,
        order_id_or_number,
        paper_width=width,
        station_id=station_id,
        staff_canteen_id=scoped_cid,
    )


@router.post("/receipts/{order_id_or_number}/print", response_model=PrintJobOut)
def print_receipt(
    order_id_or_number: str,
    payload: PrintReceiptRequest,
    response: Response,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    set_private_no_store(response)
    is_staff = bool(principal and principal.has_role(*STAFF_PRINT_ROLES))
    actor_label = principal.user.full_name if principal else "Guest/Customer"
    job = receipt_service.trigger_print_job(
        db,
        order_id_or_number,
        payload,
        actor_user_id=principal.user.id if principal else None,
        actor_label=actor_label,
        is_staff=is_staff,
        staff_canteen_id=_print_staff_cid(principal),
        staff_counter_id=scoped_counter_for_principal(principal) if is_staff else None,
        guest_access_token=guest_token or x_guest_token,
    )
    return receipt_service.serialize_print_job(db, job)


@router.post("/jobs/{job_id}/retry", response_model=PrintJobOut)
def retry_print_job(
    job_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*STAFF_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    job = db.get(ReceiptPrintJob, job_id)
    if job:
        ord_row = db.get(Order, job.order_id)
        if ord_row:
            enforce_canteen_scope(principal, ord_row.canteen_id)
    return receipt_service.retry_print_job(db, job_id, principal.user.id, principal.user.full_name)


@router.post("/kitchen/jobs/{job_id}/resume", response_model=PrintJobOut)
def resume_kitchen_print_job(
    job_id: UUID,
    principal: AuthenticatedPrincipal = Depends(require_roles(*KOT_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    job = db.get(ReceiptPrintJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Print job not found")
    ord_row = db.get(Order, job.order_id)
    if ord_row:
        enforce_canteen_scope(principal, ord_row.canteen_id)
    return receipt_service.resume_paused_print_job(db, job_id, principal.user.id, principal.user.full_name)


@router.post("/kitchen/receipts/{order_id_or_number}/reprint", response_model=PrintJobOut)
def reprint_kitchen_receipt(
    order_id_or_number: str,
    paper_width: Optional[str] = Query(default=None, pattern="^(58mm|80mm)$"),
    principal: AuthenticatedPrincipal = Depends(require_roles(*KOT_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    return receipt_service.trigger_kitchen_reprint(
        db,
        order_id_or_number,
        actor_user_id=principal.user.id,
        actor_label=principal.user.full_name,
        staff_canteen_id=scoped_canteen_for_principal(principal, None),
        paper_width=paper_width,
    )


@router.get("/kitchen/dashboard", response_model=KitchenPrintDashboardOut)
def get_kitchen_printer_dashboard(
    canteen_id: Optional[UUID] = Query(default=None),
    status: Optional[str] = Query(default=None, pattern="^(pending|queued|printing|paused|completed|failed)$"),
    limit: int = Query(default=100, ge=1, le=200),
    principal: AuthenticatedPrincipal = Depends(require_roles(*KOT_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    return receipt_service.build_kitchen_print_dashboard(db, canteen_id=scoped_cid, status_filter=status, limit=limit)


@router.post("/kitchen/printers/register", response_model=PrinterRegistrationOut, status_code=201)
def register_kitchen_printer(
    payload: PrinterDeviceCreateRequest,
    principal: AuthenticatedPrincipal = Depends(
        require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    ),
    db: Session = Depends(get_db),
):
    enforce_canteen_scope(principal, payload.canteen_id)
    printer_out, agent_id, raw_token = receipt_service.register_printer_device(
        db, payload, actor_user_id=principal.user.id
    )
    return {"printer": printer_out, "agent_id": agent_id, "agent_token": raw_token}


@router.get("/jobs", response_model=list[PrintJobOut])
def list_print_jobs(
    job_type: Optional[str] = Query(default=None, pattern="^(customer_receipt|kitchen_receipt|kot)$"),
    status: Optional[str] = Query(default=None, pattern="^(pending|queued|printing|paused|completed|failed)$"),
    order_id: Optional[UUID] = Query(default=None),
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(*KOT_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    stmt = select(ReceiptPrintJob).order_by(ReceiptPrintJob.created_at.desc()).limit(100)
    if scoped_cid:
        stmt = stmt.join(Order, Order.id == ReceiptPrintJob.order_id).where(Order.canteen_id == scoped_cid)
    if job_type:
        stmt = stmt.where(ReceiptPrintJob.job_type == job_type)
    if status:
        stmt = stmt.where(ReceiptPrintJob.status == status)
    if order_id:
        stmt = stmt.where(ReceiptPrintJob.order_id == order_id)
    jobs = list(db.scalars(stmt).all())
    return receipt_service.serialize_print_jobs_batch(db, jobs)


@router.get("/history/{order_id_or_number}", response_model=list[PrintHistoryOut])
def get_print_history(
    order_id_or_number: str,
    principal: AuthenticatedPrincipal = Depends(require_roles(*STAFF_PRINT_ROLES)),
    db: Session = Depends(get_db),
):
    _order, receipt = receipt_service._resolve_order_and_receipt(
        db, order_id_or_number, is_staff=True, staff_canteen_id=_print_staff_cid(principal)
    )
    return list(
        db.scalars(
            select(ReceiptPrintHistory)
            .where(ReceiptPrintHistory.receipt_id == receipt.id)
            .order_by(ReceiptPrintHistory.printed_at.desc())
        ).all()
    )


# ---------------- Authenticated Local Kitchen Print Agent Endpoints ----------------


@router.post("/agent/heartbeat")
def agent_heartbeat(
    payload: AgentHeartbeatRequest,
    x_print_agent_id: Optional[str] = Header(default=None),
    x_print_agent_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    printer = receipt_service.authenticate_print_agent(db, x_print_agent_id, x_print_agent_token)
    return receipt_service.process_agent_heartbeat(db, printer, payload)


@router.post("/agent/jobs/claim")
def agent_claim_next_job(
    x_print_agent_id: Optional[str] = Header(default=None),
    x_print_agent_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    printer = receipt_service.authenticate_print_agent(db, x_print_agent_id, x_print_agent_token)
    return receipt_service.claim_next_kitchen_print_job(db, printer)


@router.post("/agent/jobs/{job_id}/progress", response_model=PrintJobOut)
def agent_job_progress(
    job_id: UUID,
    payload: AgentJobProgressRequest,
    x_print_agent_id: Optional[str] = Header(default=None),
    x_print_agent_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    printer = receipt_service.authenticate_print_agent(db, x_print_agent_id, x_print_agent_token)
    return receipt_service.checkpoint_agent_job_progress(db, printer, job_id, payload)


@router.post("/agent/jobs/{job_id}/pause", response_model=PrintJobOut)
def agent_job_pause(
    job_id: UUID,
    payload: AgentJobPauseRequest,
    x_print_agent_id: Optional[str] = Header(default=None),
    x_print_agent_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    printer = receipt_service.authenticate_print_agent(db, x_print_agent_id, x_print_agent_token)
    return receipt_service.pause_agent_job(db, printer, job_id, payload)


@router.post("/agent/jobs/{job_id}/complete", response_model=PrintJobOut)
def agent_job_complete(
    job_id: UUID,
    payload: AgentJobCompleteRequest,
    x_print_agent_id: Optional[str] = Header(default=None),
    x_print_agent_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    printer = receipt_service.authenticate_print_agent(db, x_print_agent_id, x_print_agent_token)
    return receipt_service.complete_agent_job(db, printer, job_id, payload)


@router.post("/agent/jobs/{job_id}/fail", response_model=PrintJobOut)
def agent_job_fail(
    job_id: UUID,
    payload: AgentJobFailRequest,
    x_print_agent_id: Optional[str] = Header(default=None),
    x_print_agent_token: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    printer = receipt_service.authenticate_print_agent(db, x_print_agent_id, x_print_agent_token)
    return receipt_service.fail_agent_job(db, printer, job_id, payload)
