import asyncio
from collections import defaultdict
from typing import Any, Optional
from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket rooms and async SSE topic subscribers for real-time order updates."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, room: str, websocket: WebSocket) -> None:
        self._loop = asyncio.get_running_loop()
        await websocket.accept()
        self._rooms[room].add(websocket)

    def disconnect(self, room: str, websocket: WebSocket) -> None:
        if room in self._rooms:
            self._rooms[room].discard(websocket)
            if not self._rooms[room]:
                del self._rooms[room]

    def subscribe(self, topic: str) -> asyncio.Queue[dict[str, Any]]:
        """Register an async queue subscriber for in-process low-latency SSE wakeups."""
        self._loop = asyncio.get_running_loop()
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subscribers[topic].add(q)
        return q

    def unsubscribe(self, topic: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if topic in self._subscribers:
            self._subscribers[topic].discard(queue)
            if not self._subscribers[topic]:
                del self._subscribers[topic]

    def _enqueue_subscribers(self, room: str, payload: dict[str, Any]) -> None:
        queues = list(self._subscribers.get(room, ()))
        for q in queues:
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def broadcast(self, room: str, payload: dict[str, Any]) -> None:
        self._enqueue_subscribers(room, payload)
        if room not in self._rooms:
            return
        dead: list[WebSocket] = []
        for ws in list(self._rooms[room]):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(room, ws)

    def schedule_broadcast(self, room: str, payload: dict[str, Any]) -> None:
        has_ws = room in self._rooms
        has_sub = room in self._subscribers
        if not has_ws and not has_sub:
            return
        try:
            loop = asyncio.get_running_loop()
            if has_ws:
                loop.create_task(self.broadcast(room, payload))
            else:
                self._enqueue_subscribers(room, payload)
            return
        except RuntimeError:
            pass
        if self._loop and not self._loop.is_closed() and self._loop.is_running():
            if has_ws:
                asyncio.run_coroutine_threadsafe(self.broadcast(room, payload), self._loop)
            elif has_sub:
                self._loop.call_soon_threadsafe(self._enqueue_subscribers, room, payload)


ws_manager = ConnectionManager()


def emit_order_event_sync(canteen_id: str, order_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Safely schedule WebSocket/SSE broadcasts and invalidate affected board/queue/report caches."""
    try:
        from app.core.cache import invalidate_board_and_queue, invalidate_reports

        invalidate_board_and_queue(canteen_id)
        if event_type.startswith("order.") or event_type.startswith("payment.") or event_type in ("menu.updated", "stock.updated"):
            invalidate_reports(canteen_id)
    except Exception:
        pass
    message = {"event": event_type, "order_id": order_id, "canteen_id": canteen_id, "data": payload}
    ws_manager.schedule_broadcast(f"order:{order_id}", message)
    ws_manager.schedule_broadcast(f"kitchen:{canteen_id}", message)
    ws_manager.schedule_broadcast(f"queue:{canteen_id}", message)
    ws_manager.schedule_broadcast(f"board:{canteen_id}", message)
    ws_manager.schedule_broadcast("board:all", message)
    ws_manager.schedule_broadcast("staff:orders", message)


def emit_user_notification_sync(user_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Push real-time notification events to a signed-in user's WebSocket room."""
    message = {"event": event_type, "user_id": user_id, "data": payload}
    ws_manager.schedule_broadcast(f"user:{user_id}", message)
