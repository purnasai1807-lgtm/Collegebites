from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Callable, Optional
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    import orjson as _orjson
except Exception:  # pragma: no cover
    _orjson = None

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_COLLEGE_ADMIN,
    ROLE_INVENTORY_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    enforce_canteen_scope,
    get_optional_principal,
    require_roles,
    scoped_canteen_for_principal,
)
from app.core.security import sha256_hex
from app.models.college import Canteen
from app.models.order import Order
from app.services import realtime_service
from app.websockets import ws_manager

router = APIRouter(prefix="/realtime", tags=["Real-time SSE Streams"])

STAFF_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_KITCHEN_STAFF,
    ROLE_INVENTORY_MANAGER,
    ROLE_PICKUP_STAFF,
)

TOKEN_BOARD_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_KITCHEN_STAFF,
    ROLE_PICKUP_STAFF,
    ROLE_CASHIER,
)

SSE_PUBLIC_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

SSE_PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store, no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _is_serverless() -> bool:
    return bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


def _release_request_db_before_stream(request: Request, db: Optional[Session]) -> None:
    """Return the auth/validation DB connection back to the pool before starting a long-lived SSE stream."""
    if db is None:
        return
    if get_db in request.app.dependency_overrides:
        return
    try:
        db.close()
    except Exception:
        pass


def _default_stream_window(max_seconds: Optional[float]) -> float:
    if max_seconds is not None:
        return max(0.5, min(float(max_seconds), 55.0))
    if _is_serverless():
        return 20.0
    return 45.0


def _format_sse(event: str, data: dict, event_id: Optional[str] = None, retry_ms: Optional[int] = None) -> str:
    lines: list[str] = []
    if retry_ms is not None:
        lines.append(f"retry: {retry_ms}")
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    body = json.dumps(data, default=str)
    lines.append(f"data: {body}")
    return "\n".join(lines) + "\n\n"


def _authorize_order_for_stream(
    db: Session,
    order_id_or_number: str,
    principal: Optional[AuthenticatedPrincipal],
    guest_token: Optional[str],
) -> Order:
    try:
        uid = UUID(order_id_or_number)
        stmt = select(Order).where(Order.id == uid)
    except ValueError:
        stmt = select(Order).where(Order.order_number == order_id_or_number)
    order = db.scalar(stmt)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if principal and principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        return order
    if principal and order.customer_id and order.customer_id == principal.user.id:
        return order
    if principal and order.canteen_id and principal.has_role(*STAFF_ROLES):
        enforce_canteen_scope(principal, order.canteen_id)
        return order
    if guest_token and order.guest_access_token_hash and sha256_hex(guest_token.strip()) == order.guest_access_token_hash:
        return order
    if principal:
        raise HTTPException(status_code=403, detail="Not authorized to stream this order")
    raise HTTPException(status_code=401, detail="Authentication or valid guest token required")


def _stream_with_watermark(
    *,
    request: Request,
    topic: str,
    event_name: str,
    last_version: Optional[str],
    last_event_id: Optional[str],
    once: bool,
    max_seconds: Optional[float],
    compute_version: Callable[[Session], Optional[str]],
    fetch_payload: Callable[[Session], tuple[Optional[str], Optional[dict[str, Any]]]],
    is_private: bool = True,
) -> StreamingResponse:
    window_secs = _default_stream_window(max_seconds)
    seen_version = (last_version or last_event_id or "").strip() or None
    serverless = _is_serverless()
    poll_interval = 4.0 if serverless else 1.5
    retry_hint = "retry: 3000\n\n" if serverless else "retry: 1500\n\n"

    def _run_cycle(is_first: bool, woken: bool, prev_watermark: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[dict[str, Any]]]:
        gen, sess = realtime_service.resolve_db_session(request)
        try:
            watermark = compute_version(sess)
            if watermark and (is_first or woken or watermark != prev_watermark):
                snap_ver, payload = fetch_payload(sess)
                return watermark, (snap_ver or watermark), payload
            return watermark, None, None
        finally:
            realtime_service.close_db_session(gen)

    async def event_generator():
        nonlocal seen_version
        queue = ws_manager.subscribe(topic)
        started_at = time.monotonic()
        last_ping = started_at
        last_watermark: Optional[str] = None
        first_cycle = True

        try:
            yield retry_hint
            while True:
                if await request.is_disconnected():
                    break

                woken_by_event = False
                if not first_cycle:
                    remaining = window_secs - (time.monotonic() - started_at)
                    if remaining <= 0:
                        yield _format_sse("stream.reconnect", {"reason": "cycle", "version": seen_version})
                        break
                    try:
                        await asyncio.wait_for(queue.get(), timeout=min(poll_interval, remaining))
                        while not queue.empty():
                            try:
                                queue.get_nowait()
                            except asyncio.QueueEmpty:
                                break
                        woken_by_event = True
                    except asyncio.TimeoutError:
                        pass

                watermark, eff_ver, payload = await anyio.to_thread.run_sync(
                    _run_cycle, first_cycle, woken_by_event, last_watermark
                )
                if watermark:
                    last_watermark = watermark
                if payload is not None and eff_ver and (first_cycle or eff_ver != seen_version):
                    seen_version = eff_ver
                    yield _format_sse(event_name, payload, event_id=eff_ver)

                first_cycle = False
                if once:
                    break

                now = time.monotonic()
                if now - last_ping >= 15.0:
                    last_ping = now
                    yield ": keepalive\n\n"
                if now - started_at >= window_secs:
                    yield _format_sse("stream.reconnect", {"reason": "cycle", "version": seen_version})
                    break
        finally:
            ws_manager.unsubscribe(topic, queue)

    headers = SSE_PRIVATE_HEADERS if is_private else SSE_PUBLIC_HEADERS
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


@router.get("/board/stream")
async def stream_digital_board(
    request: Request,
    canteen_id: Optional[UUID] = Query(default=None),
    last_version: Optional[str] = Query(default=None),
    once: bool = Query(default=False),
    max_seconds: Optional[float] = Query(default=None, ge=0.2, le=55.0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    principal: AuthenticatedPrincipal = Depends(require_roles(*TOKEN_BOARD_ROLES)),
    db: Session = Depends(get_db),
):
    """Private Server-Sent Events stream for authenticated staff Token Display synchronization."""
    scoped_canteen = scoped_canteen_for_principal(principal, canteen_id)
    _release_request_db_before_stream(request, db)
    if scoped_canteen is not None:
        def _validate_canteen() -> bool:
            gen, sess = realtime_service.resolve_db_session(request)
            try:
                return sess.get(Canteen, scoped_canteen) is not None
            finally:
                realtime_service.close_db_session(gen)

        if not await anyio.to_thread.run_sync(_validate_canteen):
            raise HTTPException(status_code=404, detail="Canteen not found")

    def _fetch(sess: Session) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        snap = realtime_service.fetch_board_snapshot(sess, scoped_canteen)
        return snap.version, snap.model_dump(mode="json")

    return _stream_with_watermark(
        request=request,
        topic=f"board:{scoped_canteen}" if scoped_canteen is not None else "board:all",
        event_name="board.snapshot",
        last_version=last_version,
        last_event_id=last_event_id,
        once=once,
        max_seconds=max_seconds,
        compute_version=lambda sess: realtime_service.compute_board_watermark(sess, scoped_canteen),
        fetch_payload=_fetch,
        is_private=True,
    )


@router.get("/queue/{canteen_id}/stream")
async def stream_queue_dashboard(
    canteen_id: UUID,
    request: Request,
    last_version: Optional[str] = Query(default=None),
    once: bool = Query(default=False),
    max_seconds: Optional[float] = Query(default=None, ge=0.2, le=55.0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    principal: AuthenticatedPrincipal = Depends(require_roles(*STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    """Server-Sent Events stream for live Canteen Queue Management dashboard."""
    enforce_canteen_scope(principal, canteen_id)
    _release_request_db_before_stream(request, db)

    def _fetch(sess: Session) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        ver, snap = realtime_service.fetch_queue_snapshot(sess, canteen_id)
        return ver, {"version": ver, "queue": snap}

    return _stream_with_watermark(
        request=request,
        topic=f"queue:{canteen_id}",
        event_name="queue.snapshot",
        last_version=last_version,
        last_event_id=last_event_id,
        once=once,
        max_seconds=max_seconds,
        compute_version=lambda sess: realtime_service.compute_queue_version(sess, canteen_id),
        fetch_payload=_fetch,
        is_private=True,
    )


@router.get("/token-board/stream")
async def stream_operational_token_board(
    request: Request,
    canteen_id: Optional[UUID] = Query(default=None),
    last_version: Optional[str] = Query(default=None),
    once: bool = Query(default=False),
    max_seconds: Optional[float] = Query(default=None, ge=0.2, le=55.0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    principal: AuthenticatedPrincipal = Depends(require_roles(*TOKEN_BOARD_ROLES)),
    db: Session = Depends(get_db),
):
    """Authenticated SSE stream for the 5-section Operational Token Board."""
    scoped_canteen = scoped_canteen_for_principal(principal, canteen_id)
    _release_request_db_before_stream(request, db)

    def _fetch(sess: Session) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        snap = realtime_service.fetch_token_board_snapshot(sess, scoped_canteen)
        return snap.version, snap.model_dump(mode="json")

    return _stream_with_watermark(
        request=request,
        topic=f"kitchen:{scoped_canteen}" if scoped_canteen is not None else "staff:orders",
        event_name="token_board.snapshot",
        last_version=last_version,
        last_event_id=last_event_id,
        once=once,
        max_seconds=max_seconds,
        compute_version=lambda sess: realtime_service.compute_staff_orders_version(sess, canteen_id=scoped_canteen),
        fetch_payload=_fetch,
        is_private=True,
    )


@router.get("/orders/{order_id_or_number}/stream")
async def stream_order_updates(
    order_id_or_number: str,
    request: Request,
    guest_token: Optional[str] = Query(default=None),
    x_guest_token: Optional[str] = Header(default=None),
    last_version: Optional[str] = Query(default=None),
    once: bool = Query(default=False),
    max_seconds: Optional[float] = Query(default=None, ge=0.2, le=55.0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
):
    """Server-Sent Events stream for real-time customer & staff single-order status tracking."""
    order = _authorize_order_for_stream(db, order_id_or_number, principal, guest_token or x_guest_token)
    order_id = order.id
    _release_request_db_before_stream(request, db)

    def _fetch(sess: Session) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        ver, out = realtime_service.fetch_order_snapshot(sess, order_id)
        if not ver or not out:
            return None, None
        return ver, {"version": ver, "order": out.model_dump(mode="json")}

    return _stream_with_watermark(
        request=request,
        topic=f"order:{order_id}",
        event_name="order.snapshot",
        last_version=last_version,
        last_event_id=last_event_id,
        once=once,
        max_seconds=max_seconds,
        compute_version=lambda sess: realtime_service.compute_order_version(sess, order_id),
        fetch_payload=_fetch,
        is_private=True,
    )


@router.get("/staff/orders/stream")
async def stream_staff_orders(
    request: Request,
    canteen_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    payment_status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    last_version: Optional[str] = Query(default=None),
    once: bool = Query(default=False),
    max_seconds: Optional[float] = Query(default=None, ge=0.2, le=55.0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    principal: AuthenticatedPrincipal = Depends(require_roles(*STAFF_ROLES)),
    db: Session = Depends(get_db),
):
    """Server-Sent Events stream for Canteen Manager, Kitchen Display, Pickup, and Admin consoles."""
    scoped_canteen = scoped_canteen_for_principal(principal, canteen_id)
    _release_request_db_before_stream(request, db)

    def _compute(sess: Session) -> str:
        ver = realtime_service.compute_staff_orders_version(
            sess,
            canteen_id=scoped_canteen,
            status_filter=status_filter,
            payment_status=payment_status,
            q=q,
        )
        board_wm = realtime_service.compute_board_watermark(sess, scoped_canteen)
        return sha256_hex(f"{ver}|{board_wm}")[:16]

    def _fetch(sess: Session) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        snap = realtime_service.fetch_staff_orders_snapshot(
            sess,
            canteen_id=scoped_canteen,
            status_filter=status_filter,
            payment_status=payment_status,
            q=q,
            limit=limit,
        )
        return snap.get("version"), snap

    return _stream_with_watermark(
        request=request,
        topic=f"kitchen:{scoped_canteen}" if scoped_canteen is not None else "staff:orders",
        event_name="orders.snapshot",
        last_version=last_version,
        last_event_id=last_event_id,
        once=once,
        max_seconds=max_seconds,
        compute_version=_compute,
        fetch_payload=_fetch,
        is_private=True,
    )


@router.get("/notifications/stream")
async def stream_user_notifications(
    request: Request,
    last_version: Optional[str] = Query(default=None),
    once: bool = Query(default=False),
    max_seconds: Optional[float] = Query(default=None, ge=0.2, le=55.0),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    principal: AuthenticatedPrincipal = Depends(require_roles(
        ROLE_SUPER_ADMIN,
        ROLE_COLLEGE_ADMIN,
        ROLE_CANTEEN_MANAGER,
        ROLE_CASHIER,
        ROLE_KITCHEN_STAFF,
        ROLE_INVENTORY_MANAGER,
        ROLE_PICKUP_STAFF,
        "food_safety_inspector",
        "customer",
    )),
    db: Session = Depends(get_db),
):
    """SSE stream for authenticated customer & staff in-app + browser push notifications."""
    uid = principal.user.id
    roles = set(principal.roles)
    assigned_cid = principal.assigned_canteen_id
    _release_request_db_before_stream(request, db)

    def _fetch(sess: Session) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        return realtime_service.fetch_user_notifications_snapshot(
            sess, user_id=uid, roles=roles, assigned_canteen_id=assigned_cid
        )

    return _stream_with_watermark(
        request=request,
        topic=f"user:{uid}",
        event_name="notifications.snapshot",
        last_version=last_version,
        last_event_id=last_event_id,
        once=once,
        max_seconds=max_seconds,
        compute_version=lambda sess: realtime_service.compute_user_notifications_version(
            sess, user_id=uid, roles=roles, assigned_canteen_id=assigned_cid
        ),
        fetch_payload=_fetch,
        is_private=True,
    )
