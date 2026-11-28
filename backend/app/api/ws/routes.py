import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

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
    load_user_roles_and_permissions,
)
from app.core.security import decode_token, sha256_hex
from app.models.auth import SessionRecord, User
from app.models.order import Order
from app.websockets import ws_manager

router = APIRouter(tags=["Real-time WebSockets"])

STAFF_ROLES = (
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_KITCHEN_STAFF,
    ROLE_INVENTORY_MANAGER,
    ROLE_PICKUP_STAFF,
)


def _authenticate_jwt_from_ws(websocket: WebSocket) -> Optional[AuthenticatedPrincipal]:
    token = (websocket.query_params.get("token") or "").strip()
    if not token:
        return None
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        user_id = UUID(payload["sub"])
        session_id = UUID(payload["sid"])
    except Exception:
        return None

    provider = websocket.app.dependency_overrides.get(get_db, get_db)
    gen = provider()
    db = next(gen)
    try:
        sess = db.get(SessionRecord, session_id)
        if not sess or sess.revoked_at is not None:
            return None
        expires_at = sess.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            return None
        user = db.get(User, user_id)
        if not user or not user.is_active:
            return None
        roles, perms, assigned_canteen_id = load_user_roles_and_permissions(db, user.id)
        return AuthenticatedPrincipal(
            user=user,
            session_id=session_id,
            roles=roles,
            permissions=perms,
            assigned_canteen_id=assigned_canteen_id,
        )
    finally:
        gen.close()


def _authorize_order_ws(websocket: WebSocket, order_id: str) -> bool:
    try:
        oid = UUID(order_id)
    except ValueError:
        return False

    guest_token = (websocket.query_params.get("guest_token") or "").strip()
    principal = _authenticate_jwt_from_ws(websocket)

    provider = websocket.app.dependency_overrides.get(get_db, get_db)
    gen = provider()
    db = next(gen)
    try:
        order = db.get(Order, oid)
        if not order:
            return False
        if guest_token and order.guest_access_token_hash and sha256_hex(guest_token) == order.guest_access_token_hash:
            return True
        if not principal:
            return False
        if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
            return True
        if order.customer_id and order.customer_id == principal.user.id:
            return True
        if principal.has_role(*STAFF_ROLES) and principal.assigned_canteen_id == order.canteen_id:
            return True
        return False
    finally:
        gen.close()


async def _watch_room_db_changes(
    websocket: WebSocket,
    watch_kind: str,
    target_id: Optional[UUID],
) -> None:
    """Poll DB watermarks at 1s intervals so cross-instance updates reach open WebSockets."""
    from app.services import realtime_service

    last_watermark: Optional[str] = None
    provider = websocket.app.dependency_overrides.get(get_db, get_db)
    while True:
        await asyncio.sleep(1.0)
        gen = provider()
        try:
            db = next(gen)
            if watch_kind == "board":
                watermark = realtime_service.compute_board_watermark(db, target_id)
                event_name = "board.updated"
            elif watch_kind == "order" and target_id is not None:
                watermark = realtime_service.compute_order_version(db, target_id) or ""
                event_name = "order.updated"
            elif watch_kind == "kitchen":
                watermark = realtime_service.compute_staff_orders_version(db, canteen_id=target_id)
                event_name = "kitchen.updated"
            elif watch_kind == "notifications" and target_id is not None:
                from app.core.permissions import load_user_roles_and_permissions
                roles, _perms, _cid = load_user_roles_and_permissions(db, target_id)
                watermark = realtime_service.compute_user_notifications_version(db, user_id=target_id, roles=roles)
                event_name = "notifications.updated"
            else:
                continue

            if last_watermark is None:
                last_watermark = watermark
            elif watermark and watermark != last_watermark:
                last_watermark = watermark
                await websocket.send_json(
                    {
                        "event": event_name,
                        "version": watermark,
                        "canteen_id": str(target_id) if target_id else None,
                        "order_id": str(target_id) if watch_kind == "order" and target_id else None,
                    }
                )
        except Exception:
            break
        finally:
            with contextlib.suppress(Exception):
                gen.close()


async def _serve_room(
    room: str,
    websocket: WebSocket,
    *,
    watch_kind: Optional[str] = None,
    target_id: Optional[UUID] = None,
) -> None:
    """Register websocket in a room, answer ping keepalives, and watch cross-instance DB updates."""
    await ws_manager.connect(room, websocket)
    watcher_task: Optional[asyncio.Task[None]] = None
    if watch_kind:
        watcher_task = asyncio.create_task(_watch_room_db_changes(websocket, watch_kind, target_id))
    try:
        while True:
            msg = await websocket.receive_text()
            if msg.strip().lower() == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(room, websocket)
    finally:
        if watcher_task is not None:
            watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher_task


@router.websocket("/ws/orders/{order_id}")
async def ws_order(websocket: WebSocket, order_id: str):
    if not _authorize_order_ws(websocket, order_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await _serve_room(f"order:{order_id}", websocket, watch_kind="order", target_id=UUID(order_id))


@router.websocket("/ws/kitchen/{canteen_id}")
async def ws_kitchen(websocket: WebSocket, canteen_id: str):
    try:
        cid = UUID(canteen_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    principal = _authenticate_jwt_from_ws(websocket)
    if not principal or not principal.has_role(*STAFF_ROLES):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) and principal.assigned_canteen_id != cid:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await _serve_room(f"kitchen:{canteen_id}", websocket, watch_kind="kitchen", target_id=cid)


@router.websocket("/ws/board/{canteen_id}")
async def ws_board(websocket: WebSocket, canteen_id: str):
    principal = _authenticate_jwt_from_ws(websocket)
    if not principal or not principal.has_role(*STAFF_ROLES):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if canteen_id == "all":
        if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await _serve_room("board:all", websocket, watch_kind="board", target_id=None)
        return
    try:
        target = UUID(canteen_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN) and principal.assigned_canteen_id != target:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await _serve_room(f"board:{canteen_id}", websocket, watch_kind="board", target_id=target)


@router.websocket("/ws/notifications/{user_id}")
async def ws_notifications(websocket: WebSocket, user_id: str):
    try:
        uid = UUID(user_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    principal = _authenticate_jwt_from_ws(websocket)
    if not principal or (
        principal.user.id != uid and not principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN)
    ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await _serve_room(f"user:{user_id}", websocket, watch_kind="notifications", target_id=uid)
