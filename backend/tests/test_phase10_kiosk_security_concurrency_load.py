from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from fastapi.testclient import TestClient

from app.integrations.razorpay_client import razorpay_gateway
from tests.conftest import TestingSessionLocal, login_as


def test_kiosk_disabled_by_default_and_works_when_enabled(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    items = client.get(f"/api/v1/menus/canteens/{canteen['id']}/items").json()
    dosa = next(i for i in items if "Dosa" in i["name"])

    status_res = client.get("/api/v1/kiosk/status").json()
    assert status_res["kiosk_enabled"] is False
    dev_id = status_res["devices"][0]["id"]
    dev_code = status_res["devices"][0]["device_code"]

    # Blocked when disabled
    blocked = client.post(
        "/api/v1/kiosk/orders",
        json={"device_code": dev_code, "canteen_id": canteen["id"], "items": [{"food_item_id": dosa["id"], "quantity": 1}]},
    )
    assert blocked.status_code == 403

    # Admin enables kiosk globally + device
    client.put("/api/v1/admin/college", headers=admin["headers"], json={"kiosk_enabled": True})
    client.patch(f"/api/v1/kiosk/devices/{dev_id}", headers=admin["headers"], json={"is_enabled": True})

    ok = client.post(
        "/api/v1/kiosk/orders",
        json={"device_code": dev_code, "canteen_id": canteen["id"], "items": [{"food_item_id": dosa["id"], "quantity": 1}]},
    )
    assert ok.status_code == 201
    assert ok.json()["order_type"] == "kiosk"

    recs = client.get(f"/api/v1/kiosk/recommendations/{canteen['id']}?veg_only=true")
    assert recs.status_code == 200
    assert len(recs.json()) >= 1

    hb = client.post(f"/api/v1/kiosk/devices/{dev_id}/heartbeat")
    assert hb.status_code == 200
    assert hb.json()["status"] == "ok"


def test_security_sqli_headers_and_concurrent_handover_and_tokens(client: TestClient):
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")

    # Security headers check
    health = client.get("/health")
    assert health.headers["X-Content-Type-Options"] == "nosniff"
    assert health.headers["X-Frame-Options"] == "SAMEORIGIN"

    # SQL injection attempt in search & auth safely handled
    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    sqli = client.get(f"/api/v1/menus/canteens/{canteen['id']}/items?q=' OR '1'='1'; DROP TABLE orders;--")
    assert sqli.status_code == 200
    assert sqli.json() == []

    # Concurrent token generation: 8 simultaneous POS walk-in orders -> 8 distinct tokens!
    items = client.get(f"/api/v1/menus/canteens/{canteen['id']}/items").json()
    dosa = next(i for i in items if "Dosa" in i["name"])

    def place_pos(idx: int):
        from app.schemas.operations import POSWalkInOrderRequest
        from app.schemas.order import CheckoutItemDirectIn
        from app.services.pos_service import create_pos_walkin_order
        from uuid import UUID

        with TestingSessionLocal() as db:
            res = create_pos_walkin_order(
                db,
                POSWalkInOrderRequest(
                    canteen_id=UUID(canteen["id"]),
                    customer_name=f"Concurrent {idx}",
                    payment_method="upi_pos",
                    items=[CheckoutItemDirectIn(food_item_id=UUID(dosa["id"]), quantity=1)],
                ),
                cashier_user_id=UUID(cashier["user"]["id"]),
            )
            return res.pickup_token_code, str(res.id)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(place_pos, range(8)))

    tokens = [r[0] for r in results]
    assert len(set(tokens)) == 8, f"Duplicate tokens generated under concurrency: {tokens}"

    # Concurrent handover on the first order -> ONLY 1 succeeds, second gets 409!
    target_order_id = results[0][1]
    assert client.post(f"/api/v1/kitchen/orders/{target_order_id}/accept", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{target_order_id}/start-preparing", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{target_order_id}/mark-ready", headers=kitchen["headers"]).status_code == 200

    def try_handover(_idx: int):
        from app.schemas.operations import HandoverConfirmRequest
        from app.services.pickup_service import confirm_handover
        from fastapi import HTTPException
        from uuid import UUID

        with TestingSessionLocal() as db:
            try:
                confirm_handover(
                    db,
                    HandoverConfirmRequest(order_id=UUID(target_order_id), verification_method="qr_scan"),
                    staff_user_id=UUID(pickup["user"]["id"]),
                )
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(try_handover, range(4)))
    assert statuses.count(200) == 1
    assert statuses.count(409) == 3


def test_section_34_full_end_to_end_acceptance_scenario(client: TestClient):
    """Verifies all 27 steps of Section 34 Final Acceptance Criteria end-to-end."""
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")

    # 1-2. Customer opens app & scans permanent location QR code
    qr_scan = client.get("/api/v1/qr/locations/resolve/CB-MAIN-C2").json()
    canteen_id = qr_scan["canteen"]["id"]
    counter_id = qr_scan["counter"]["id"]

    # 3-5. Browse food, add multiple items with variants & customizations
    items = client.get(f"/api/v1/menus/canteens/{canteen_id}/items").json()
    biryani = next(i for i in items if "Biryani" in i["name"])
    coffee = next(i for i in items if "Coffee" in i["name"])
    jumbo = next(v for v in biryani["variants"] if v["name"] == "Jumbo Pack")
    raita = next(a for a in biryani["addons"] if "Raita" in a["name"])

    guest_headers = {"X-Guest-Session-ID": "e2e-guest-sess"}
    client.post(
        "/api/v1/carts/items",
        headers=guest_headers,
        json={
            "canteen_id": canteen_id,
            "food_item_id": biryani["id"],
            "variant_id": jumbo["id"],
            "quantity": 2,
            "spice_level": "Extra Spicy",
            "addons": [{"addon_id": raita["id"], "quantity": 1}],
            "special_instructions": "Hot & fresh",
        },
    )
    client.post(
        "/api/v1/carts/items",
        headers=guest_headers,
        json={"canteen_id": canteen_id, "food_item_id": coffee["id"], "quantity": 2, "sugar_level": "Regular"},
    )

    # 6-7. Guest proceeds directly to checkout (backend validates prices, availability, capacity; no OTP)
    checkout = client.post(
        "/api/v1/orders/checkout",
        headers=guest_headers,
        json={
            "canteen_id": canteen_id,
            "counter_id": counter_id,
            "location_qr_code": "CB-MAIN-C2",
            "guest_name": "E2E Guest",
            "guest_phone": "+919876500001",
            "payment_method": "razorpay",
            "order_type": "pickup",
            "order_channel": "qr",
            "idempotency_key": "e2e-accept-001",
            "accepted_policy": True,
        },
    ).json()
    guest_token = checkout["guest_access_token"]
    assert checkout["pickup_token_code"] is None

    # 8-13. Complete Razorpay payment & backend verifies -> token, QR, and complete receipt generated
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=checkout["razorpay_order_id"], razorpay_payment_id="pay_e2e_999"
    )
    confirmed = client.post(
        "/api/v1/payments/razorpay/verify",
        json={
            "order_id": checkout["id"],
            "razorpay_order_id": checkout["razorpay_order_id"],
            "razorpay_payment_id": "pay_e2e_999",
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    ).json()
    assert confirmed["status"] == "PLACED"
    assert confirmed["pickup_token_code"] is not None
    assert confirmed["qr_token_raw"] is not None

    # 14-16. Customer views receipt & downloads PDF containing ALL ordered food details
    receipt = client.get(f"/api/v1/tokens/receipts/{confirmed['order_number']}?guest_token={guest_token}").json()
    assert len(receipt["items"]) == 2
    assert Decimal(receipt["total_paid"]) == Decimal(confirmed["total_amount"])
    pdf = client.get(f"/api/v1/tokens/receipts/{confirmed['order_number']}/pdf?guest_token={guest_token}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # 17-20. Kitchen receives -> prepares -> marks READY -> appears on digital token display board
    k_orders = client.get(f"/api/v1/kitchen/canteens/{canteen_id}/orders", headers=kitchen["headers"]).json()
    assert any(o["id"] == confirmed["id"] for o in k_orders)
    assert client.post(f"/api/v1/kitchen/orders/{confirmed['id']}/accept", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{confirmed['id']}/start-preparing", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{confirmed['id']}/mark-ready", headers=kitchen["headers"]).status_code == 200

    assert client.get(f"/api/v1/pickup/board/{canteen_id}").status_code == 401
    board = client.get(f"/api/v1/pickup/board/{canteen_id}", headers=pickup["headers"]).json()
    assert any(t["token_code"] == confirmed["pickup_token_code"] for t in board["ready_for_pickup"])

    # 21-25. Pickup staff scans QR -> backend verifies -> staff confirms handover -> COMPLETED
    v = client.post(
        "/api/v1/pickup/verify",
        headers=pickup["headers"],
        json={"qr_payload": confirmed["qr_token_raw"], "counter_id": counter_id},
    ).json()
    assert v["valid"] is True and v["can_handover"] is True

    ho = client.post(
        "/api/v1/pickup/handover",
        headers=pickup["headers"],
        json={"order_id": confirmed["id"], "counter_id": counter_id, "verification_method": "qr_scan"},
    )
    assert ho.status_code == 200

    final_order = client.get(f"/api/v1/orders/{confirmed['order_number']}?guest_token={guest_token}").json()
    assert final_order["status"] == "COMPLETED"

    # 26. Second collection attempt is rejected
    second = client.post(
        "/api/v1/pickup/verify",
        headers=pickup["headers"],
        json={"qr_payload": confirmed["qr_token_raw"], "counter_id": counter_id},
    ).json()
    assert second["result_code"] == "ALREADY_COLLECTED"
    assert second["can_handover"] is False

    # 27. Audit logs contain lifecycle events
    logs = client.get("/api/v1/admin/audit-logs", headers=admin["headers"]).json()
    actions = {l["action"] for l in logs}
    assert {"payment.confirmed", "pickup.handover_confirmed"}.issubset(actions)
