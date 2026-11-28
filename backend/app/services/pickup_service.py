from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.cache import NS_BOARD, cache_manager
from app.core.security import sha256_hex, verify_signed_qr_token_format
from app.core.time_utils import today_college
from app.models.auth import User
from app.models.college import Canteen, Counter, KitchenStation
from app.models.order import Order, OrderItem, SlotReservation
from app.models.payment import (
    OrderHandoverRecord,
    OrderQRCode,
    Payment,
    PickupToken,
    QRVerificationEvent,
)
from app.schemas.operations import (
    DigitalBoardResponse,
    HandoverConfirmRequest,
    OperationalTokenBoardResponse,
    OperationalTokenCard,
    PickupVerifyRequest,
    PickupVerifyResponse,
    TokenBoardItem,
    TokenBoardOrderItemDetail,
)
from app.services import security_service
from app.services.audit_service import record_audit_log
from app.services.order_service import transition_order_status
from app.websockets import emit_order_event_sync


def _extract_qr_token(raw_payload: str) -> str:
    txt = raw_payload.strip()
    if "#token=" in txt:
        return txt.split("#token=", 1)[1].split("&", 1)[0].strip()
    if "token=" in txt:
        return txt.split("token=", 1)[1].split("&", 1)[0].strip()
    return txt


def _log_verification(
    db: Session,
    *,
    order: Optional[Order],
    token_row: Optional[PickupToken],
    staff_user_id: UUID,
    canteen_id: Optional[UUID],
    counter_id: Optional[UUID],
    method: str,
    presented: Optional[str],
    result_code: str,
    is_valid: bool,
    details: str,
) -> None:
    masked = (presented[:12] + "...") if presented and len(presented) > 12 else presented
    db.add(
        QRVerificationEvent(
            order_id=order.id if order else None,
            pickup_token_id=token_row.id if token_row else None,
            staff_user_id=staff_user_id,
            canteen_id=canteen_id,
            counter_id=counter_id,
            verification_method=method,
            presented_code_masked=masked,
            result_code=result_code,
            is_valid=is_valid,
            details=details,
        )
    )
    if not is_valid:
        security_service.record_qr_fraud_if_applicable(
            db,
            order=order,
            canteen_id=canteen_id,
            staff_user_id=staff_user_id,
            method=method,
            presented=presented,
            result_code=result_code,
        )
    db.commit()


def verify_pickup(db: Session, payload: PickupVerifyRequest, staff_user_id: UUID) -> PickupVerifyResponse:
    """
    Verify QR code, manual pickup token, or order number WITHOUT marking the order completed.
    Never exposes private order details for invalid/unrecognized QR codes.
    """
    order: Optional[Order] = None
    token_row: Optional[PickupToken] = None
    method = "qr_scan"
    presented = ""

    if payload.qr_payload:
        method = "qr_scan"
        raw_token = _extract_qr_token(payload.qr_payload)
        presented = raw_token
        if not verify_signed_qr_token_format(raw_token):
            _log_verification(
                db,
                order=None,
                token_row=None,
                staff_user_id=staff_user_id,
                canteen_id=payload.canteen_id,
                counter_id=payload.counter_id,
                method=method,
                presented=presented,
                result_code="INVALID_QR",
                is_valid=False,
                details="QR token signature format failed",
            )
            return PickupVerifyResponse(
                valid=False,
                can_handover=False,
                result_code="INVALID_QR",
                message="Invalid or tampered QR code.",
            )
        token_hash = sha256_hex(raw_token)
        qr_rec = db.scalar(select(OrderQRCode).where(OrderQRCode.token_hash == token_hash))
        if not qr_rec or qr_rec.revoked_at is not None or (qr_rec.expires_at and qr_rec.expires_at <= datetime.now(timezone.utc)):
            _log_verification(
                db,
                order=None,
                token_row=None,
                staff_user_id=staff_user_id,
                canteen_id=payload.canteen_id,
                counter_id=payload.counter_id,
                method=method,
                presented=presented,
                result_code="INVALID_QR",
                is_valid=False,
                details="QR token not found, revoked, or expired",
            )
            return PickupVerifyResponse(
                valid=False,
                can_handover=False,
                result_code="INVALID_QR",
                message="QR code is invalid, expired, or revoked.",
            )
        order = db.scalar(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.customizations))
            .where(Order.id == qr_rec.order_id)
        )
        token_row = db.get(PickupToken, qr_rec.pickup_token_id)

    elif payload.pickup_token:
        method = "manual_token"
        presented = payload.pickup_token.strip().upper()
        stmt = select(PickupToken).where(PickupToken.token_code == presented, PickupToken.service_date == today_college())
        if payload.canteen_id:
            stmt = stmt.where(PickupToken.canteen_id == payload.canteen_id)
        token_row = db.scalar(stmt.order_by(PickupToken.created_at.desc()))
        if token_row:
            order = db.scalar(
                select(Order)
                .options(selectinload(Order.items).selectinload(OrderItem.customizations))
                .where(Order.id == token_row.order_id)
            )
    elif payload.order_number:
        method = "order_number"
        presented = payload.order_number.strip().upper()
        order = db.scalar(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.customizations))
            .where(Order.order_number == presented)
        )
        if order:
            token_row = db.scalar(select(PickupToken).where(PickupToken.order_id == order.id))
    else:
        raise HTTPException(status_code=400, detail="Provide qr_payload, pickup_token, or order_number")

    if not order:
        _log_verification(
            db,
            order=None,
            token_row=None,
            staff_user_id=staff_user_id,
            canteen_id=payload.canteen_id,
            counter_id=payload.counter_id,
            method=method,
            presented=presented,
            result_code="INVALID_QR",
            is_valid=False,
            details="No matching order found",
        )
        return PickupVerifyResponse(
            valid=False,
            can_handover=False,
            result_code="INVALID_QR",
            message="Order or token not found.",
        )

    canteen = db.get(Canteen, order.canteen_id)
    counter = db.get(Counter, order.counter_id)
    items_list = [
        {
            "item_name": it.item_name,
            "variant_name": it.variant_name,
            "quantity": it.quantity,
            "special_instructions": it.special_instructions,
            "customizations": [f"{c.option_name}: {c.option_value}" for c in it.customizations],
        }
        for it in order.items
    ]

    def _resp(valid: bool, can_handover: bool, code: str, msg: str, prev_ho: Optional[datetime] = None) -> PickupVerifyResponse:
        _log_verification(
            db,
            order=order,
            token_row=token_row,
            staff_user_id=staff_user_id,
            canteen_id=order.canteen_id,
            counter_id=payload.counter_id or order.counter_id,
            method=method,
            presented=presented,
            result_code=code,
            is_valid=valid,
            details=msg,
        )
        return PickupVerifyResponse(
            valid=valid,
            can_handover=can_handover,
            result_code=code,
            message=msg,
            order_id=order.id,
            order_number=order.order_number,
            pickup_token=token_row.token_code if token_row else None,
            order_status=order.status,
            payment_status=order.payment_status,
            canteen_name=canteen.name if canteen else None,
            counter_id=order.counter_id,
            counter_name=counter.name if counter else None,
            previous_handover_at=prev_ho,
            items=items_list if valid or code in ("ORDER_NOT_READY", "WRONG_COUNTER", "ALREADY_COLLECTED") else [],
        )

    if order.status in ("CANCELLED", "REJECTED"):
        return _resp(False, False, "CANCELLED_OR_REJECTED", f"Order has been {order.status.lower()}. Reject pickup.")

    if order.payment_status != "CONFIRMED":
        return _resp(False, False, "PAYMENT_NOT_CONFIRMED", "Payment is not confirmed. Reject pickup.")

    existing_ho = db.scalar(select(OrderHandoverRecord).where(OrderHandoverRecord.order_id == order.id))
    if order.status == "COMPLETED" or existing_ho:
        prev_time = existing_ho.handed_over_at if existing_ho else order.completed_at
        return _resp(False, False, "ALREADY_COLLECTED", "Order already collected. Duplicate handover rejected.", prev_ho=prev_time)

    if payload.canteen_id and payload.canteen_id != order.canteen_id:
        return _resp(False, False, "WRONG_CANTEEN", f"Wrong canteen. Order belongs to {canteen.name if canteen else 'another canteen'}.")

    if payload.counter_id and payload.counter_id != order.counter_id:
        return _resp(False, False, "WRONG_COUNTER", f"Wrong counter. Direct customer to {counter.name if counter else 'assigned counter'}.")

    if order.status != "READY":
        return _resp(False, False, "ORDER_NOT_READY", f"Food is still being prepared (status: {order.status}).")

    return _resp(True, True, "VALID_ORDER", "Verified! Ready for food handover.")


def confirm_handover(db: Session, payload: HandoverConfirmRequest, staff_user_id: UUID) -> OrderHandoverRecord:
    """
    Atomically confirm food handover.
    Prevents concurrent or duplicate handover using SELECT ... FOR UPDATE and unique DB constraint.
    """
    order = db.scalar(select(Order).where(Order.id == payload.order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.payment_status != "CONFIRMED":
        raise HTTPException(status_code=409, detail="Payment not confirmed for this order")

    verified_pay = db.scalar(
        select(Payment).where(Payment.order_id == order.id, Payment.status == "CONFIRMED")
    )
    if not verified_pay:
        raise HTTPException(status_code=409, detail="No verified payment record found for this order")

    existing_ho = db.scalar(select(OrderHandoverRecord).where(OrderHandoverRecord.order_id == order.id))
    if existing_ho or order.status == "COMPLETED":
        token_for_log = db.scalar(select(PickupToken).where(PickupToken.order_id == order.id))
        _log_verification(
            db,
            order=order,
            token_row=token_for_log,
            staff_user_id=staff_user_id,
            canteen_id=order.canteen_id,
            counter_id=payload.counter_id or order.counter_id,
            method=payload.verification_method,
            presented=token_for_log.token_code if token_for_log else order.order_number,
            result_code="ALREADY_COLLECTED",
            is_valid=False,
            details="Duplicate handover confirmation attempted",
        )
        raise HTTPException(status_code=409, detail="Order has already been collected; duplicate handover rejected")

    if order.status != "READY":
        raise HTTPException(status_code=409, detail=f"Order cannot be handed over while in status {order.status}")

    if payload.counter_id and payload.counter_id != order.counter_id:
        counter = db.get(Counter, order.counter_id)
        raise HTTPException(
            status_code=409,
            detail=f"Wrong counter. Please complete handover at {counter.name if counter else 'assigned counter'}",
        )

    token_row = db.scalar(select(PickupToken).where(PickupToken.order_id == order.id).with_for_update())
    if not token_row:
        raise HTTPException(status_code=409, detail="Pickup token missing for order")

    now = datetime.now(timezone.utc)
    transition_order_status(db, order, "COMPLETED", actor_user_id=staff_user_id, reason="Food handed over at pickup counter")
    token_row.status = "HANDED_OVER"

    resv = db.scalar(select(SlotReservation).where(SlotReservation.order_id == order.id))
    if resv and resv.status == "reserved":
        resv.status = "fulfilled"

    handover = OrderHandoverRecord(
        order_id=order.id,
        pickup_token_id=token_row.id,
        counter_id=order.counter_id,
        handed_over_by_user_id=staff_user_id,
        verification_method=payload.verification_method,
        handed_over_at=now,
        notes=payload.notes,
    )
    db.add(handover)
    record_audit_log(
        db,
        action="pickup.handover_confirmed",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=staff_user_id,
        details={"pickup_token": token_row.token_code, "method": payload.verification_method},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Order has already been collected") from exc
    db.refresh(handover)

    try:
        from app.services.notification_service import notify_order_completed
        notify_order_completed(db, order)
        db.commit()
    except ImportError:
        pass

    emit_order_event_sync(
        str(order.canteen_id),
        str(order.id),
        "order.completed",
        {"pickup_token": token_row.token_code, "status": "COMPLETED"},
    )
    return handover


def _build_board_item_summaries(db: Session, order_ids: list[UUID]) -> dict[UUID, tuple[str, int]]:
    if not order_ids:
        return {}
    item_rows = db.execute(
        select(OrderItem.order_id, OrderItem.item_name, OrderItem.quantity)
        .where(OrderItem.order_id.in_(order_ids))
        .order_by(OrderItem.id.asc())
    ).all()
    grouped: dict[UUID, list[tuple[str, int]]] = {}
    for oid, name, qty in item_rows:
        grouped.setdefault(oid, []).append((name, int(qty or 1)))
    result: dict[UUID, tuple[str, int]] = {}
    for oid, parts in grouped.items():
        total_qty = sum(q for _, q in parts)
        head = [f"{q}x {n}" for n, q in parts[:3]]
        if len(parts) > 3:
            head.append(f"+{len(parts) - 3} more")
        result[oid] = (", ".join(head), total_qty)
    return result


def get_digital_token_board(
    db: Session,
    canteen_id: Optional[UUID] = None,
    *,
    counter_id: Optional[UUID] = None,
) -> DigitalBoardResponse:
    """Staff-only display board for kitchen/pickup monitors — never exposed without authorization."""
    cache_ns = f"{NS_BOARD}:{canteen_id}" if canteen_id is not None else NS_BOARD
    cache_key = f"digital:{canteen_id or 'all'}:{counter_id or 'all'}"
    hit, cached = cache_manager.get_json(cache_ns, cache_key, l1_ttl=1.0)
    if hit and isinstance(cached, dict):
        return DigitalBoardResponse.model_validate(cached)

    canteen_name = "All Campus Canteens"
    if canteen_id is not None:
        canteen = db.get(Canteen, canteen_id)
        if not canteen or not canteen.is_active:
            raise HTTPException(status_code=404, detail="Canteen not found")
        canteen_name = canteen.name

    today = today_college()
    active_stmt = (
        select(
            PickupToken.token_code,
            PickupToken.sequence_number,
            Counter.name,
            Canteen.id,
            Canteen.name,
            Order.id,
            Order.order_number,
            Order.status,
            Order.ready_at,
            Order.completed_at,
            Order.delayed_minutes,
            Order.created_at,
            Order.updated_at,
        )
        .join(Order, Order.id == PickupToken.order_id)
        .join(Counter, Counter.id == PickupToken.counter_id)
        .join(Canteen, Canteen.id == Order.canteen_id)
        .where(
            Canteen.is_active.is_(True),
            PickupToken.service_date == today,
            Order.status.in_(("PLACED", "ACCEPTED", "PREPARING", "READY")),
        )
        .order_by(Order.is_priority.desc(), PickupToken.sequence_number.asc(), Order.created_at.asc())
        .limit(120)
    )
    completed_stmt = (
        select(
            PickupToken.token_code,
            PickupToken.sequence_number,
            Counter.name,
            Canteen.id,
            Canteen.name,
            Order.id,
            Order.order_number,
            Order.status,
            Order.ready_at,
            Order.completed_at,
            Order.delayed_minutes,
            Order.created_at,
            Order.updated_at,
        )
        .join(Order, Order.id == PickupToken.order_id)
        .join(Counter, Counter.id == PickupToken.counter_id)
        .join(Canteen, Canteen.id == Order.canteen_id)
        .where(
            Canteen.is_active.is_(True),
            PickupToken.service_date == today,
            Order.status == "COMPLETED",
        )
        .order_by(Order.completed_at.desc(), PickupToken.sequence_number.desc())
        .limit(12)
    )
    if canteen_id is not None:
        active_stmt = active_stmt.where(Order.canteen_id == canteen_id)
        completed_stmt = completed_stmt.where(Order.canteen_id == canteen_id)
    if counter_id is not None:
        active_stmt = active_stmt.where(Order.counter_id == counter_id)
        completed_stmt = completed_stmt.where(Order.counter_id == counter_id)

    active_rows = db.execute(active_stmt).all()
    completed_rows = db.execute(completed_stmt).all()

    all_order_ids = [row[5] for row in active_rows] + [row[5] for row in completed_rows]
    summaries = _build_board_item_summaries(db, all_order_ids)

    def _to_item(row: tuple) -> TokenBoardItem:
        tc, seq, cnt_name, cid, cname, oid, onum, st, ra, _ca, dmin, crt, _upd = row
        summary, count = summaries.get(oid, ("", 0))
        return TokenBoardItem(
            token_code=tc,
            counter_name=cnt_name,
            order_status=st,
            ready_at=ra,
            order_id=oid,
            order_number=onum,
            canteen_id=cid,
            canteen_name=cname,
            sequence_number=seq,
            item_summary=summary or None,
            item_count=count,
            delayed_minutes=int(dmin or 0),
            created_at=crt,
        )

    preparing: list[TokenBoardItem] = []
    ready: list[TokenBoardItem] = []
    completed: list[TokenBoardItem] = [_to_item(r) for r in completed_rows]
    for row in active_rows:
        item = _to_item(row)
        if item.order_status in ("PLACED", "ACCEPTED", "PREPARING"):
            preparing.append(item)
        elif item.order_status == "READY":
            ready.append(item)

    fingerprint_parts = [f"{today.isoformat()}|{canteen_id or 'all'}"]
    for row in active_rows + completed_rows:
        upd = row[12].isoformat() if row[12] else ""
        fingerprint_parts.append(f"{row[5]}:{row[7]}:{row[10]}:{upd}:{row[0]}")
    version = sha256_hex("|".join(fingerprint_parts))[:16]

    board_out = DigitalBoardResponse(
        canteen_id=canteen_id,
        canteen_name=canteen_name,
        now_preparing=preparing,
        ready_for_pickup=ready,
        recently_completed=completed,
        updated_at=datetime.now(timezone.utc),
        version=version,
    )
    cache_manager.set_json(cache_ns, cache_key, board_out.model_dump(mode="json"), ttl_seconds=3, l1_ttl=1.0)
    return board_out


def get_operational_token_board(
    db: Session,
    canteen_id: Optional[UUID] = None,
    *,
    counter_id: Optional[UUID] = None,
) -> OperationalTokenBoardResponse:
    """Real-time 5-section operational Token Board for Canteen Managers, Kitchen & Pickup Staff."""
    cache_ns = f"{NS_BOARD}:{canteen_id}" if canteen_id is not None else NS_BOARD
    cache_key = f"ops:{canteen_id or 'all'}:{counter_id or 'all'}"
    hit, cached = cache_manager.get_json(cache_ns, cache_key, l1_ttl=1.0)
    if hit and isinstance(cached, dict):
        return OperationalTokenBoardResponse.model_validate(cached)

    canteen_name = "All Campus Canteens"
    if canteen_id is not None:
        canteen = db.get(Canteen, canteen_id)
        if not canteen or not canteen.is_active:
            raise HTTPException(status_code=404, detail="Canteen not found")
        canteen_name = canteen.name

    today = today_college()
    base_cols = (
        PickupToken.token_code,
        PickupToken.sequence_number,
        Counter.id,
        Counter.name,
        Canteen.id,
        Canteen.name,
        Order.id,
        Order.order_number,
        Order.status,
        Order.payment_status,
        Order.payment_method,
        Order.total_amount,
        Order.order_type,
        Order.order_channel,
        Order.is_priority,
        Order.delayed_minutes,
        Order.delay_reason,
        Order.estimated_prep_minutes,
        Order.estimated_pickup_at,
        Order.created_at,
        Order.confirmed_at,
        Order.accepted_at,
        Order.preparing_at,
        Order.ready_at,
        Order.completed_at,
        Order.updated_at,
        Order.guest_name,
        Order.customer_id,
        OrderQRCode.token_hash,
        OrderQRCode.verification_path,
    )

    active_stmt = (
        select(*base_cols)
        .join(Order, Order.id == PickupToken.order_id)
        .join(Counter, Counter.id == PickupToken.counter_id)
        .join(Canteen, Canteen.id == Order.canteen_id)
        .outerjoin(OrderQRCode, OrderQRCode.order_id == Order.id)
        .where(
            Canteen.is_active.is_(True),
            PickupToken.service_date == today,
            Order.payment_status == "CONFIRMED",
            Order.status.in_(("PLACED", "ACCEPTED", "PREPARING", "READY")),
        )
        .order_by(Order.is_priority.desc(), PickupToken.sequence_number.asc(), Order.created_at.asc())
        .limit(180)
    )
    completed_stmt = (
        select(*base_cols)
        .join(Order, Order.id == PickupToken.order_id)
        .join(Counter, Counter.id == PickupToken.counter_id)
        .join(Canteen, Canteen.id == Order.canteen_id)
        .outerjoin(OrderQRCode, OrderQRCode.order_id == Order.id)
        .where(
            Canteen.is_active.is_(True),
            PickupToken.service_date == today,
            Order.payment_status == "CONFIRMED",
            Order.status == "COMPLETED",
        )
        .order_by(Order.completed_at.desc(), PickupToken.sequence_number.desc())
        .limit(30)
    )
    if canteen_id is not None:
        active_stmt = active_stmt.where(Order.canteen_id == canteen_id)
        completed_stmt = completed_stmt.where(Order.canteen_id == canteen_id)
    if counter_id is not None:
        active_stmt = active_stmt.where(Order.counter_id == counter_id)
        completed_stmt = completed_stmt.where(Order.counter_id == counter_id)

    active_rows = db.execute(active_stmt).all()
    completed_rows = db.execute(completed_stmt).all()
    all_rows = active_rows + completed_rows

    order_ids = [r[6] for r in all_rows]
    customer_ids = list({r[27] for r in all_rows if r[27] is not None})
    user_names = (
        {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(customer_ids))).all()}
        if customer_ids
        else {}
    )
    items_by_order: dict[UUID, list[TokenBoardOrderItemDetail]] = {}
    if order_ids:
        item_rows = db.scalars(
            select(OrderItem).where(OrderItem.order_id.in_(order_ids)).order_by(OrderItem.id.asc())
        ).all()
        used_station_ids = list({it.station_id for it in item_rows if getattr(it, "station_id", None)})
        stations = (
            {s.id: s.name for s in db.scalars(select(KitchenStation).where(KitchenStation.id.in_(used_station_ids))).all()}
            if used_station_ids
            else {}
        )
        for it in item_rows:
            items_by_order.setdefault(it.order_id, []).append(
                TokenBoardOrderItemDetail(
                    id=it.id,
                    item_name=it.item_name,
                    variant_name=it.variant_name,
                    quantity=it.quantity,
                    prep_status=getattr(it, "prep_status", "PENDING") or "PENDING",
                    station_id=getattr(it, "station_id", None),
                    station_name=stations.get(getattr(it, "station_id", None)),
                    special_instructions=it.special_instructions,
                )
            )

    new_orders: list[OperationalTokenCard] = []
    accepted_orders: list[OperationalTokenCard] = []
    preparing_orders: list[OperationalTokenCard] = []
    ready_orders: list[OperationalTokenCard] = []
    completed_orders: list[OperationalTokenCard] = []

    fp_parts = [f"ops|{today.isoformat()}|{canteen_id or 'all'}"]
    for r in all_rows:
        (
            tc, seq, cnt_id, cnt_name, cid, cname, oid, onum, st, pst, pmethod,
            tot_amt, otype, ochan, is_prio, dmin, dreason, est_mins, est_at,
            crt, cnf, acc, prp, rdy, cmp, upd, gname, cust_id, qr_hash, qr_path
        ) = r
        cust_label = user_names.get(cust_id) or (gname.strip() if gname else None) or "Walk-in / Guest"
        card_items = items_by_order.get(oid, [])
        qr_ref = f"QR-{qr_hash[:8].upper()}" if qr_hash else f"TKN-{tc}"
        card = OperationalTokenCard(
            order_id=oid,
            order_number=onum,
            token_code=tc,
            sequence_number=seq,
            qr_reference=qr_ref,
            qr_verification_path=qr_path,
            canteen_id=cid,
            canteen_name=cname,
            counter_id=cnt_id,
            counter_name=cnt_name,
            customer_label=cust_label,
            order_type=otype,
            order_channel=ochan,
            status=st,
            payment_status=pst,
            payment_method=pmethod,
            total_amount=tot_amt,
            is_priority=bool(is_prio),
            delayed_minutes=int(dmin or 0),
            delay_reason=dreason,
            estimated_prep_minutes=int(est_mins or 12),
            estimated_pickup_at=est_at,
            created_at=crt,
            confirmed_at=cnf,
            accepted_at=acc,
            preparing_at=prp,
            ready_at=rdy,
            completed_at=cmp,
            items=card_items,
        )
        item_fp = ",".join(f"{i.id}:{i.prep_status}" for i in card_items)
        fp_parts.append(f"{oid}:{st}:{bool(is_prio)}:{dmin}:{upd.isoformat() if upd else ''}:{item_fp}")

        if st == "PLACED":
            new_orders.append(card)
        elif st == "ACCEPTED":
            accepted_orders.append(card)
        elif st == "PREPARING":
            preparing_orders.append(card)
        elif st == "READY":
            ready_orders.append(card)
        elif st == "COMPLETED":
            completed_orders.append(card)

    version = sha256_hex("|".join(fp_parts))[:16]
    ops_out = OperationalTokenBoardResponse(
        canteen_id=canteen_id,
        canteen_name=canteen_name,
        new_orders=new_orders,
        accepted_orders=accepted_orders,
        preparing_orders=preparing_orders,
        ready_for_pickup=ready_orders,
        completed_orders=completed_orders,
        counts={
            "new_orders": len(new_orders),
            "accepted_orders": len(accepted_orders),
            "preparing_orders": len(preparing_orders),
            "ready_for_pickup": len(ready_orders),
            "completed_orders": len(completed_orders),
        },
        updated_at=datetime.now(timezone.utc),
        version=version,
    )
    cache_manager.set_json(cache_ns, cache_key, ops_out.model_dump(mode="json"), ttl_seconds=3, l1_ttl=1.0)
    return ops_out
