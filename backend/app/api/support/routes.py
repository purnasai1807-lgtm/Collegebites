from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import invalidate_reports
from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_current_principal,
    get_optional_principal,
    require_roles,
    scoped_canteen_for_principal,
)
from app.core.time_utils import today_college
from app.models.engagement import Rating, Review, SupportMessage, SupportTicket
from app.models.menu import FoodItem
from app.models.order import Order
from app.services.audit_service import record_audit_log

router = APIRouter(prefix="/support", tags=["Reviews & Support (No Refunds)"])


class ReviewCreateIn(BaseModel):
    food_item_id: UUID
    order_id: Optional[UUID] = None
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


class TicketCreateIn(BaseModel):
    order_id: Optional[UUID] = None
    canteen_id: Optional[UUID] = None
    guest_name: Optional[str] = None
    guest_phone: Optional[str] = None
    category: str = Field(
        pattern="^(food_quality|missing_item|incorrect_order|payment_issue|order_issue|app_help|other)$"
    )
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=5, max_length=2000)
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")


class TicketStatusUpdateIn(BaseModel):
    status: str = Field(pattern="^(open|in_progress|assigned|resolved|closed)$")
    note: Optional[str] = Field(default=None, max_length=500)


class TicketMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    is_internal: bool = False


class TicketAssignIn(BaseModel):
    assigned_to_user_id: UUID


class ReviewVisibilityIn(BaseModel):
    is_visible: bool


class GuestTicketLookupIn(BaseModel):
    ticket_number: str = Field(min_length=4, max_length=48)
    guest_phone: str = Field(min_length=7, max_length=24)


class GuestTicketMessageIn(BaseModel):
    ticket_number: str = Field(min_length=4, max_length=48)
    guest_phone: str = Field(min_length=7, max_length=24)
    message: str = Field(min_length=1, max_length=2000)


def _serialize_ticket(t: SupportTicket) -> dict:
    res_mins: Optional[int] = None
    if t.resolved_at and t.created_at:
        res_mins = max(0, int((t.resolved_at - t.created_at).total_seconds() // 60))
    return {
        "id": str(t.id),
        "ticket_number": t.ticket_number,
        "user_id": str(t.user_id) if t.user_id else None,
        "guest_name": t.guest_name,
        "guest_phone": t.guest_phone,
        "order_id": str(t.order_id) if t.order_id else None,
        "canteen_id": str(t.canteen_id) if t.canteen_id else None,
        "category": t.category,
        "subject": t.subject,
        "description": t.description,
        "priority": t.priority,
        "status": t.status,
        "assigned_to_user_id": str(t.assigned_to_user_id) if t.assigned_to_user_id else None,
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "resolution_minutes": res_mins,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _recompute_food_rating(db: Session, food_item_id: UUID) -> None:
    food = db.get(FoodItem, food_item_id)
    if not food:
        return
    visible_ratings = db.scalars(
        select(Review.rating).where(Review.food_item_id == food_item_id, Review.is_visible.is_(True))
    ).all()
    agg = db.scalar(select(Rating).where(Rating.food_item_id == food_item_id).with_for_update())
    if not agg:
        agg = Rating(food_item_id=food_item_id, rating_sum=0, rating_count=0, average_score=0)
        db.add(agg)
        db.flush()
    agg.rating_count = len(visible_ratings)
    agg.rating_sum = int(sum(visible_ratings))
    if agg.rating_count > 0:
        avg = Decimal(agg.rating_sum) / Decimal(agg.rating_count)
        agg.average_score = int((avg * 100).quantize(Decimal("1")))
        food.average_rating = avg.quantize(Decimal("0.01"))
    else:
        agg.average_score = 0
        food.average_rating = Decimal("0.00")
    food.rating_count = agg.rating_count


def _enforce_ticket_manager_scope(principal: AuthenticatedPrincipal, ticket: SupportTicket) -> None:
    if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        return
    if not ticket.canteen_id:
        raise HTTPException(status_code=403, detail="Ticket is not scoped to your assigned canteen")
    enforce_canteen_scope(principal, ticket.canteen_id)


@router.post("/reviews", status_code=status.HTTP_201_CREATED)
def create_review(
    payload: ReviewCreateIn,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    food = db.get(FoodItem, payload.food_item_id)
    if not food:
        raise HTTPException(status_code=404, detail="Food item not found")
    if payload.order_id:
        order = db.get(Order, payload.order_id)
        if not order or (order.customer_id and order.customer_id != principal.user.id):
            raise HTTPException(status_code=403, detail="Order does not belong to customer")
    rev = Review(
        user_id=principal.user.id,
        order_id=payload.order_id,
        food_item_id=food.id,
        canteen_id=food.canteen_id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(rev)
    db.flush()
    _recompute_food_rating(db, food.id)
    db.commit()
    db.refresh(rev)
    invalidate_reports(food.canteen_id)
    return rev


@router.patch("/reviews/{review_id}/visibility")
def moderate_review_visibility(
    review_id: UUID,
    payload: ReviewVisibilityIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    rev = db.get(Review, review_id)
    if not rev:
        raise HTTPException(status_code=404, detail="Review not found")
    enforce_canteen_scope(principal, rev.canteen_id)
    rev.is_visible = payload.is_visible
    db.flush()
    _recompute_food_rating(db, rev.food_item_id)
    record_audit_log(
        db,
        action="support.review_moderated",
        entity_type="review",
        entity_id=str(rev.id),
        actor_user_id=principal.user.id,
        details={"is_visible": payload.is_visible},
    )
    db.commit()
    db.refresh(rev)
    invalidate_reports(rev.canteen_id)
    return rev


@router.get("/items/{food_item_id}/reviews")
def list_item_reviews(food_item_id: UUID, db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(Review)
            .where(Review.food_item_id == food_item_id, Review.is_visible.is_(True))
            .order_by(Review.created_at.desc())
            .limit(50)
        ).all()
    )


@router.post("/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreateIn,
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    canteen_id = payload.canteen_id
    if payload.order_id and not canteen_id:
        order = db.get(Order, payload.order_id)
        if order:
            canteen_id = order.canteen_id
    tnum = f"SUP-{today_college().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
    ticket = SupportTicket(
        ticket_number=tnum,
        user_id=principal.user.id if principal else None,
        guest_name=payload.guest_name or (principal.user.full_name if principal else "Guest"),
        guest_phone=payload.guest_phone or (principal.user.phone if principal else None),
        order_id=payload.order_id,
        canteen_id=canteen_id,
        category=payload.category,
        subject=payload.subject,
        description=payload.description,
        priority=payload.priority,
        status="open",
    )
    db.add(ticket)
    db.flush()
    db.add(
        SupportMessage(
            ticket_id=ticket.id,
            sender_user_id=principal.user.id if principal else None,
            sender_role="customer",
            message=payload.description,
        )
    )
    db.commit()
    db.refresh(ticket)
    invalidate_reports(ticket.canteen_id)
    return _serialize_ticket(ticket)


@router.get("/tickets/my")
def my_tickets(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(SupportTicket).where(SupportTicket.user_id == principal.user.id).order_by(SupportTicket.created_at.desc())
    ).all()
    return [_serialize_ticket(t) for t in rows]


def _guest_contact_candidates(raw: str) -> set[str]:
    clean = raw.strip()
    candidates = {clean, clean.lower()}
    digits = "".join(ch for ch in clean if ch.isdigit())
    if len(digits) == 10:
        candidates.add(digits)
        candidates.add(f"+91{digits}")
    elif len(digits) == 12 and digits.startswith("91"):
        candidates.add(digits[2:])
        candidates.add(f"+{digits}")
    return {c for c in candidates if c}


@router.post("/tickets/guest/lookup")
def lookup_guest_tickets(
    payload: GuestTicketLookupIn,
    db: Session = Depends(get_db),
):
    clean_phone = payload.guest_phone.strip()
    clean_num = payload.ticket_number.strip().upper()
    candidates = _guest_contact_candidates(clean_phone)
    rows = db.scalars(
        select(SupportTicket)
        .where(SupportTicket.ticket_number == clean_num, SupportTicket.guest_phone.in_(candidates))
        .order_by(SupportTicket.created_at.desc())
        .limit(10)
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No matching guest ticket found for this ticket number and mobile")
    return [_serialize_ticket(t) for t in rows]


@router.post("/tickets/{ticket_id}/guest-thread")
def get_guest_ticket_thread(
    ticket_id: UUID,
    payload: GuestTicketLookupIn,
    db: Session = Depends(get_db),
):
    clean_phone = payload.guest_phone.strip()
    clean_num = payload.ticket_number.strip().upper()
    candidates = _guest_contact_candidates(clean_phone)
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket or ticket.ticket_number != clean_num or (ticket.guest_phone or "").strip() not in candidates:
        raise HTTPException(status_code=404, detail="Guest ticket not found")
    msgs = list(
        db.scalars(
            select(SupportMessage)
            .where(SupportMessage.ticket_id == ticket.id, SupportMessage.is_internal.is_(False))
            .order_by(SupportMessage.created_at.asc())
        ).all()
    )
    return {"ticket": _serialize_ticket(ticket), "messages": msgs}


@router.post("/tickets/{ticket_id}/guest-messages")
def add_guest_ticket_message(
    ticket_id: UUID,
    payload: GuestTicketMessageIn,
    db: Session = Depends(get_db),
):
    clean_phone = payload.guest_phone.strip()
    clean_num = payload.ticket_number.strip().upper()
    candidates = _guest_contact_candidates(clean_phone)
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket or ticket.ticket_number != clean_num or (ticket.guest_phone or "").strip() not in candidates:
        raise HTTPException(status_code=404, detail="Guest ticket not found")
    msg = SupportMessage(
        ticket_id=ticket.id,
        sender_user_id=None,
        sender_role="customer",
        message=payload.message,
        is_internal=False,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@router.get("/tickets")
def list_all_tickets(
    status_filter: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    effective_cid = scoped_canteen_for_principal(principal, canteen_id)
    stmt = select(SupportTicket).order_by(SupportTicket.created_at.desc())
    if effective_cid:
        stmt = stmt.where(SupportTicket.canteen_id == effective_cid)
    if status_filter and status_filter != "all":
        stmt = stmt.where(SupportTicket.status == status_filter)
    if category and category != "all":
        stmt = stmt.where(SupportTicket.category == category)
    if priority and priority != "all":
        stmt = stmt.where(SupportTicket.priority == priority)
    rows = list(db.scalars(stmt.limit(200)).all())
    if search and search.strip():
        q = search.strip().lower()
        rows = [
            r
            for r in rows
            if q in (r.ticket_number or "").lower()
            or q in (r.subject or "").lower()
            or q in (r.description or "").lower()
            or q in (r.guest_name or "").lower()
        ]
    return [_serialize_ticket(t) for t in rows]


@router.patch("/tickets/{ticket_id}/status")
def update_ticket_status(
    ticket_id: UUID,
    payload: TicketStatusUpdateIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _enforce_ticket_manager_scope(principal, ticket)
    ticket.status = payload.status
    if payload.status in ("resolved", "closed") and not ticket.resolved_at:
        ticket.resolved_at = datetime.now(timezone.utc)
    if payload.note:
        db.add(
            SupportMessage(
                ticket_id=ticket.id,
                sender_user_id=principal.user.id,
                sender_role="admin",
                message=f"[{payload.status.upper()}] {payload.note}",
            )
        )
    record_audit_log(
        db,
        action=f"support.ticket_{payload.status}",
        entity_type="support_ticket",
        entity_id=ticket.ticket_number,
        actor_user_id=principal.user.id,
    )
    db.commit()
    db.refresh(ticket)
    invalidate_reports(ticket.canteen_id)
    return _serialize_ticket(ticket)


@router.get("/reports/summary")
def get_support_report_summary(
    canteen_id: Optional[UUID] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    effective_cid = scoped_canteen_for_principal(principal, canteen_id)
    stmt = select(SupportTicket)
    if effective_cid:
        stmt = stmt.where(SupportTicket.canteen_id == effective_cid)
    rows = list(db.scalars(stmt).all())
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    res_times: list[int] = []
    for t in rows:
        by_status[t.status] = by_status.get(t.status, 0) + 1
        by_category[t.category] = by_category.get(t.category, 0) + 1
        by_priority[t.priority] = by_priority.get(t.priority, 0) + 1
        if t.resolved_at and t.created_at:
            res_times.append(max(0, int((t.resolved_at - t.created_at).total_seconds() // 60)))
    avg_res = round(sum(res_times) / len(res_times), 1) if res_times else 0.0
    return {
        "total_tickets": len(rows),
        "open_count": by_status.get("open", 0),
        "in_progress_count": by_status.get("in_progress", 0) + by_status.get("assigned", 0),
        "resolved_count": by_status.get("resolved", 0),
        "closed_count": by_status.get("closed", 0),
        "avg_resolution_minutes": avg_res,
        "by_status": by_status,
        "by_category": by_category,
        "by_priority": by_priority,
    }


@router.get("/tickets/{ticket_id}/messages")
def get_ticket_messages(
    ticket_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    is_admin = principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    if is_admin:
        _enforce_ticket_manager_scope(principal, ticket)
    elif ticket.user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    stmt = select(SupportMessage).where(SupportMessage.ticket_id == ticket.id).order_by(SupportMessage.created_at.asc())
    if not is_admin:
        stmt = stmt.where(SupportMessage.is_internal.is_(False))
    return list(db.scalars(stmt).all())


@router.post("/tickets/{ticket_id}/messages")
def add_ticket_message(
    ticket_id: UUID,
    payload: TicketMessageIn,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    is_admin = principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)
    if is_admin:
        _enforce_ticket_manager_scope(principal, ticket)
    elif ticket.user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    msg = SupportMessage(
        ticket_id=ticket.id,
        sender_user_id=principal.user.id,
        sender_role="admin" if is_admin else "customer",
        message=payload.message,
        is_internal=payload.is_internal and is_admin,
    )
    db.add(msg)
    if is_admin and ticket.status == "open":
        ticket.status = "in_progress"
    db.commit()
    db.refresh(msg)
    return msg


@router.post("/tickets/{ticket_id}/assign")
def assign_ticket(
    ticket_id: UUID,
    payload: TicketAssignIn,
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _enforce_ticket_manager_scope(principal, ticket)
    ticket.assigned_to_user_id = payload.assigned_to_user_id
    if ticket.status == "open":
        ticket.status = "assigned"
    db.commit()
    db.refresh(ticket)
    invalidate_reports(ticket.canteen_id)
    return _serialize_ticket(ticket)


@router.post("/tickets/{ticket_id}/resolve")
def resolve_ticket(
    ticket_id: UUID,
    resolution_note: Optional[str] = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)),
    db: Session = Depends(get_db),
):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _enforce_ticket_manager_scope(principal, ticket)
    ticket.status = "resolved"
    ticket.resolved_at = datetime.now(timezone.utc)
    if resolution_note:
        db.add(
            SupportMessage(
                ticket_id=ticket.id,
                sender_user_id=principal.user.id,
                sender_role="admin",
                message=f"Resolved: {resolution_note}",
            )
        )
    record_audit_log(db, action="support.ticket_resolved", entity_type="support_ticket", entity_id=ticket.ticket_number, actor_user_id=principal.user.id)
    db.commit()
    db.refresh(ticket)
    invalidate_reports(ticket.canteen_id)
    return _serialize_ticket(ticket)
