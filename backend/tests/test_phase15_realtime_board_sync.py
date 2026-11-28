from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from typing import Any
from uuid import uuid4
from fastapi.testclient import TestClient

from app.integrations.razorpay_client import razorpay_gateway
from tests.conftest import login_as


def _parse_sse_events(raw_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    blocks = raw_text.replace("\r\n", "\n").split("\n\n")
    for block in blocks:
        if not block.strip():
            continue
        ev_id = None
        ev_name = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith(":") or not line:
                continue
            if line.startswith("id:"):
                ev_id = line[3:].strip()
            elif line.startswith("event:"):
                ev_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if data_lines:
            raw_data = "\n".join(data_lines)
            try:
                parsed = json.loads(raw_data)
            except ValueError:
                parsed = raw_data
            events.append({"id": ev_id, "event": ev_name, "data": parsed})
    return events


def _create_paid_student_order(
    client: TestClient,
    student_headers: dict,
    canteen_id: str,
    food_item_id: str,
    qty: int = 1,
) -> dict:
    co = client.post(
        "/api/v1/orders/checkout",
        headers=student_headers,
        json={
            "canteen_id": canteen_id,
            "order_type": "pickup",
            "order_channel": "web",
            "payment_method": "razorpay",
            "idempotency_key": f"rt-{uuid4().hex[:16]}",
            "accepted_policy": True,
            "use_cart": False,
            "direct_items": [{"food_item_id": food_item_id, "quantity": qty}],
        },
    )
    assert co.status_code == 201, co.text
    order = co.json()
    rzp_order_id = order["razorpay_order_id"]
    rzp_pay_id = f"pay_{uuid4().hex[:14]}"
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=rzp_order_id,
        razorpay_payment_id=rzp_pay_id,
    )
    ver = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student_headers,
        json={
            "order_id": order["id"],
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": rzp_pay_id,
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    )
    assert ver.status_code == 200, ver.text
    return ver.json()


def test_realtime_board_simultaneous_orders_sequence_dedup_and_reconnect_catchup(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")

    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    items = client.get(f"/api/v1/menus/canteens/{main_canteen['id']}/items").json()
    food = items[0]

    # 1. Place multiple orders simultaneously and verify instant board registration + sequence + zero duplicates
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(_create_paid_student_order, client, student["headers"], main_canteen["id"], food["id"], 1)
            for _ in range(4)
        ]
        orders = [f.result() for f in futures]
    orders.sort(key=lambda o: o["pickup_token_code"])
    tokens = [o["pickup_token_code"] for o in orders]
    assert all(tokens)
    assert len(tokens) == len(set(tokens)), f"Duplicate tokens generated: {tokens}"

    # Verify staff-protected board endpoints (single canteen & All Canteens) show all 4 in strict creation sequence without PII
    assert client.get(f"/api/v1/pickup/board/{main_canteen['id']}").status_code == 401
    assert client.get(f"/api/v1/pickup/board/{main_canteen['id']}", headers=student["headers"]).status_code == 403
    board_single = client.get(f"/api/v1/pickup/board/{main_canteen['id']}", headers=kitchen["headers"])
    assert board_single.status_code == 200
    snap_1 = board_single.json()
    assert snap_1["version"]
    assert "guest_phone" not in board_single.text
    assert "guest_access_token" not in board_single.text

    prep_tokens = [item["token_code"] for item in snap_1["now_preparing"]]
    for tok in tokens:
        assert tok in prep_tokens
    positions = [prep_tokens.index(tok) for tok in tokens]
    assert positions == sorted(positions), f"Sequence order broken: {positions}"

    seq_nums = [
        item["sequence_number"]
        for item in snap_1["now_preparing"]
        if item["token_code"] in tokens and item["sequence_number"] is not None
    ]
    assert seq_nums == sorted(seq_nums)

    # All-Canteens endpoint
    board_all = client.get("/api/v1/pickup/board", headers=admin["headers"])
    assert board_all.status_code == 200
    assert board_all.json()["canteen_name"] == "All Campus Canteens"
    all_prep_tokens = [item["token_code"] for item in board_all.json()["now_preparing"]]
    for tok in tokens:
        assert tok in all_prep_tokens

    # 2. Simulate SSE snapshot sync for two independent staff board viewers + deduplication when version unchanged
    assert client.get(f"/api/v1/realtime/board/stream?canteen_id={main_canteen['id']}&once=true").status_code == 401
    assert (
        client.get(
            f"/api/v1/realtime/board/stream?canteen_id={main_canteen['id']}&once=true",
            headers=student["headers"],
        ).status_code
        == 403
    )
    sse_v1 = client.get(
        f"/api/v1/realtime/board/stream?canteen_id={main_canteen['id']}&once=true",
        headers=kitchen["headers"],
    )
    assert sse_v1.status_code == 200
    assert "text/event-stream" in sse_v1.headers["content-type"]
    events_1 = _parse_sse_events(sse_v1.text)
    assert len(events_1) == 1
    assert events_1[0]["event"] == "board.snapshot"
    ver_before = events_1[0]["id"]
    assert ver_before == events_1[0]["data"]["version"]

    # Second concurrent staff viewer sees identical board version
    sse_viewer2 = client.get(
        f"/api/v1/realtime/board/stream?canteen_id={main_canteen['id']}&once=true",
        headers=pickup["headers"],
    )
    events_v2 = _parse_sse_events(sse_viewer2.text)
    assert events_v2[0]["id"] == ver_before

    # 3. Manager / Kitchen processes orders -> verify sequence stability (no jumping in now_preparing)
    # Advance order #2 to PREPARING before order #1; order #1 should remain ahead in sequence
    o1, o2, o3, _o4 = orders
    assert client.post(f"/api/v1/kitchen/orders/{o1['id']}/accept", headers=manager["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{o2['id']}/accept", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{o2['id']}/start-preparing", headers=kitchen["headers"]).status_code == 200

    board_mid = client.get(f"/api/v1/pickup/board/{main_canteen['id']}", headers=kitchen["headers"]).json()
    mid_tokens = [i["token_code"] for i in board_mid["now_preparing"]]
    assert mid_tokens.index(o1["pickup_token_code"]) < mid_tokens.index(o2["pickup_token_code"])
    o2_card = next(i for i in board_mid["now_preparing"] if i["token_code"] == o2["pickup_token_code"])
    assert o2_card["order_status"] == "PREPARING"
    assert o2_card["item_summary"]

    # Invalid server-side transition check (o3 is PLACED -> cannot jump straight to READY)
    invalid_ready = client.post(f"/api/v1/kitchen/orders/{o3['id']}/mark-ready", headers=kitchen["headers"])
    assert invalid_ready.status_code in (400, 409)

    # 4. Customer real-time order stream shows PREPARING -> READY -> COMPLETED
    order_sse_prep = client.get(
        f"/api/v1/realtime/orders/{o2['id']}/stream?once=true",
        headers=student["headers"],
    )
    assert order_sse_prep.status_code == 200
    o2_ev1 = _parse_sse_events(order_sse_prep.text)[0]
    assert o2_ev1["event"] == "order.snapshot"
    assert o2_ev1["data"]["order"]["status"] == "PREPARING"

    # Mark o2 READY and o1 PREPARING
    assert client.post(f"/api/v1/kitchen/orders/{o1['id']}/start-preparing", headers=manager["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{o2['id']}/mark-ready", headers=kitchen["headers"]).status_code == 200

    # 5. Simulate disconnected staff board client reconnecting with Last-Event-ID = ver_before -> receives missed catch-up snapshot
    sse_catchup = client.get(
        f"/api/v1/realtime/board/stream?canteen_id={main_canteen['id']}&once=true",
        headers={**pickup["headers"], "Last-Event-ID": ver_before},
    )
    assert sse_catchup.status_code == 200
    catchup_ev = _parse_sse_events(sse_catchup.text)[0]
    assert catchup_ev["id"] != ver_before
    ready_tokens = [i["token_code"] for i in catchup_ev["data"]["ready_for_pickup"]]
    prep_tokens_after = [i["token_code"] for i in catchup_ev["data"]["now_preparing"]]
    assert o2["pickup_token_code"] in ready_tokens
    assert o2["pickup_token_code"] not in prep_tokens_after

    # Customer reconnect catch-up stream shows READY
    order_sse_ready = client.get(
        f"/api/v1/realtime/orders/{o2['id']}/stream?once=true",
        headers={**student["headers"], "Last-Event-ID": o2_ev1["id"]},
    )
    o2_ev2 = _parse_sse_events(order_sse_ready.text)[0]
    assert o2_ev2["id"] != o2_ev1["id"]
    assert o2_ev2["data"]["order"]["status"] == "READY"

    # 6. Handover o2 -> COMPLETED removes from READY and adds to recently_completed
    ho = client.post(
        "/api/v1/pickup/handover",
        headers=pickup["headers"],
        json={"order_id": o2["id"], "verification_method": "manual_token"},
    )
    assert ho.status_code == 200

    # Staff real-time stream (Manager Dashboard / KDS / Admin) receives updated order + board state
    staff_sse = client.get(
        f"/api/v1/realtime/staff/orders/stream?canteen_id={main_canteen['id']}&once=true",
        headers=manager["headers"],
    )
    assert staff_sse.status_code == 200
    staff_ev = _parse_sse_events(staff_sse.text)[0]
    assert staff_ev["event"] == "orders.snapshot"
    board_final = staff_ev["data"]["board"]
    assert o2["pickup_token_code"] not in [i["token_code"] for i in board_final["ready_for_pickup"]]
    assert o2["pickup_token_code"] in [i["token_code"] for i in board_final["recently_completed"]]

    # Clean unauthorized checks on protected streams
    assert client.get(f"/api/v1/realtime/orders/{o2['id']}/stream?once=true").status_code == 401
    assert client.get("/api/v1/realtime/staff/orders/stream?once=true").status_code == 401
