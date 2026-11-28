from decimal import Decimal
from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_kitchen_lifecycle_qr_verification_cases_handover_and_digital_board(client: TestClient):
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")

    canteen = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    detail = client.get(f"/api/v1/canteens/{canteen['id']}").json()
    c1 = next(cnt for cnt in detail["counters"] if cnt["code"] == "C1")
    c2 = next(cnt for cnt in detail["counters"] if cnt["code"] == "C2")
    items = client.get(f"/api/v1/menus/canteens/{canteen['id']}/items").json()
    biryani = next(i for i in items if "Biryani" in i["name"])  # Counter C2

    # Open cashier shift
    shift_open = client.post(
        "/api/v1/pos/shifts/open",
        headers=cashier["headers"],
        json={"canteen_id": canteen["id"], "counter_id": c1["id"], "opening_cash_amount": "500.00"},
    )
    assert shift_open.status_code == 200

    # Walk-in POS order -> immediately paid + token + QR generated
    pos_order = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={
            "canteen_id": canteen["id"],
            "counter_id": c2["id"],
            "customer_name": "Walk-in Student",
            "payment_method": "upi_pos",
            "items": [{"food_item_id": biryani["id"], "quantity": 1}],
        },
    )
    assert pos_order.status_code == 201, pos_order.text
    order = pos_order.json()
    token = order["pickup_token_code"]
    qr_raw = order["qr_token_raw"]
    assert token is not None and qr_raw is not None

    # Cashier live active queue shows the newly paid order
    pos_active = client.get(f"/api/v1/pos/orders/active?canteen_id={canteen['id']}", headers=cashier["headers"])
    assert pos_active.status_code == 200
    assert any(o["id"] == order["id"] for o in pos_active.json())

    # 1. Invalid QR check -> rejected with no private order info leaked
    inv = client.post("/api/v1/pickup/verify", headers=pickup["headers"], json={"qr_payload": "CBQR.fake.bad"})
    assert inv.status_code == 200
    assert inv.json()["result_code"] == "INVALID_QR"
    assert inv.json()["items"] == []

    # 2. Student cannot call pickup verify
    assert client.post("/api/v1/pickup/verify", headers=student["headers"], json={"qr_payload": qr_raw}).status_code == 403

    # 3. Order NOT READY check (status is PLACED)
    not_ready = client.post(
        "/api/v1/pickup/verify",
        headers=pickup["headers"],
        json={"qr_payload": qr_raw, "counter_id": c2["id"]},
    ).json()
    assert not_ready["result_code"] == "ORDER_NOT_READY"
    assert not_ready["can_handover"] is False

    # 4. Kitchen accepts -> prepares -> reports delay -> marks READY
    assert client.post(f"/api/v1/kitchen/orders/{order['id']}/accept", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{order['id']}/start-preparing", headers=kitchen["headers"]).status_code == 200

    # Operational staff board shows NOW PREPARING without private PII (blocked for unauthenticated/student callers)
    assert client.get(f"/api/v1/pickup/board/{canteen['id']}").status_code == 401
    assert client.get(f"/api/v1/pickup/board/{canteen['id']}", headers=student["headers"]).status_code == 403
    board_prep = client.get(f"/api/v1/pickup/board/{canteen['id']}", headers=pickup["headers"]).json()
    assert any(t["token_code"] == token for t in board_prep["now_preparing"])
    assert "guest_phone" not in str(board_prep)

    assert client.post(f"/api/v1/kitchen/orders/{order['id']}/mark-ready", headers=kitchen["headers"]).status_code == 200
    board_ready = client.get(f"/api/v1/pickup/board/{canteen['id']}", headers=pickup["headers"]).json()
    assert any(t["token_code"] == token for t in board_ready["ready_for_pickup"])

    # 5. Wrong counter check
    wrong_cnt = client.post(
        "/api/v1/pickup/verify",
        headers=pickup["headers"],
        json={"qr_payload": qr_raw, "counter_id": c1["id"]},
    ).json()
    assert wrong_cnt["result_code"] == "WRONG_COUNTER"
    assert wrong_cnt["can_handover"] is False

    # 6. Valid QR verification at right counter -> does NOT auto-complete!
    valid_qr = client.post(
        "/api/v1/pickup/verify",
        headers=pickup["headers"],
        json={"qr_payload": qr_raw, "counter_id": c2["id"]},
    ).json()
    assert valid_qr["valid"] is True
    assert valid_qr["can_handover"] is True
    assert valid_qr["result_code"] == "VALID_ORDER"
    assert client.get(f"/api/v1/orders/{order['order_number']}", headers=pickup["headers"]).json()["status"] == "READY"

    # Manual token verification also works cleanly
    manual_ok = client.post(
        "/api/v1/pickup/verify",
        headers=pickup["headers"],
        json={"pickup_token": token, "canteen_id": canteen["id"], "counter_id": c2["id"]},
    ).json()
    assert manual_ok["valid"] is True

    # 7. Separate Confirm Handover -> COMPLETED
    ho1 = client.post(
        "/api/v1/pickup/handover",
        headers=pickup["headers"],
        json={"order_id": order["id"], "counter_id": c2["id"], "verification_method": "qr_scan"},
    )
    assert ho1.status_code == 200

    # 8. Second collection / duplicate handover rejected!
    verify_dup = client.post(
        "/api/v1/pickup/verify",
        headers=pickup["headers"],
        json={"qr_payload": qr_raw, "counter_id": c2["id"]},
    ).json()
    assert verify_dup["result_code"] == "ALREADY_COLLECTED"
    assert verify_dup["previous_handover_at"] is not None

    ho2 = client.post(
        "/api/v1/pickup/handover",
        headers=pickup["headers"],
        json={"order_id": order["id"], "counter_id": c2["id"], "verification_method": "qr_scan"},
    )
    assert ho2.status_code == 409

    # 9. Close cashier shift and verify online-only expected cash + UPI POS sales summary
    shift_close = client.post(
        "/api/v1/pos/shifts/close",
        headers=cashier["headers"],
        json={"closing_cash_amount": "500.00"},
    )
    assert shift_close.status_code == 200
    assert shift_close.json()["status"] == "closed"
    assert Decimal(shift_close.json()["expected_cash_amount"]) == Decimal("500.00")
    summary = shift_close.json()["shift_sales_summary"]
    assert Decimal(summary["total_collected"]) == Decimal(order["total_amount"])
    assert Decimal(summary["by_method"]["upi_pos"]["amount"]) == Decimal(order["total_amount"])
