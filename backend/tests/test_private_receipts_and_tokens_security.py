from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.integrations.razorpay_client import razorpay_gateway
from app.models.auth import Role, StaffProfile, User, UserRole
from app.models.payment import Receipt
from tests.conftest import login_as


def _create_verified_student_order(
    client: TestClient,
    headers: dict,
    canteen_id: str,
    food_item_id: str,
    counter_id: str | None = None,
) -> dict:
    payload: dict = {
        "canteen_id": canteen_id,
        "payment_method": "razorpay",
        "idempotency_key": f"sec-{uuid4().hex[:14]}",
        "use_cart": False,
        "accepted_policy": True,
        "direct_items": [{"food_item_id": food_item_id, "quantity": 1}],
    }
    if counter_id:
        payload["counter_id"] = counter_id
    chk = client.post("/api/v1/orders/checkout", headers=headers, json=payload)
    assert chk.status_code == 201, chk.text
    ord_row = chk.json()
    pay_id = f"pay_sec_{uuid4().hex[:12]}"
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=ord_row["razorpay_order_id"],
        razorpay_payment_id=pay_id,
    )
    ver = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=headers,
        json={
            "order_id": ord_row["id"],
            "razorpay_order_id": ord_row["razorpay_order_id"],
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
    )
    assert ver.status_code == 200, ver.text
    return ver.json()


def test_private_receipt_ownership_unauth_cross_student_admin_and_counter_staff(
    client: TestClient,
    clean_db_and_seed: Session,
):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    student_a = login_as(client, "student@collegebites.edu", "Student@12345")

    # Register Student B cleanly via /auth/register
    reg_b = client.post(
        "/api/v1/auth/register",
        json={
            "email": "student_b@collegebites.edu",
            "phone": "+919876501112",
            "full_name": "Student Bravo",
            "password": "StudentB@12345",
        },
    )
    assert reg_b.status_code in (200, 201), reg_b.text
    student_b = login_as(client, "student_b@collegebites.edu", "StudentB@12345")

    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    other_canteen = next(c for c in canteens if c["id"] != main_canteen["id"])
    detail = client.get(f"/api/v1/canteens/{main_canteen['id']}").json()
    counters = detail["counters"]
    c1 = counters[0]
    c2 = counters[1] if len(counters) > 1 else counters[0]
    menu = client.get(f"/api/v1/menus/canteens/{main_canteen['id']}/items").json()
    dish = menu[0]

    # Student A & Student B place separate paid orders
    order_a = _create_verified_student_order(client, student_a["headers"], main_canteen["id"], dish["id"], c1["id"])
    order_b = _create_verified_student_order(client, student_b["headers"], main_canteen["id"], dish["id"], c2["id"])

    # Verify DB-level Receipt.user_id ownership directly
    clean_db_and_seed.expire_all()
    rec_a_db = clean_db_and_seed.scalar(select(Receipt).where(Receipt.order_id == UUID(order_a["id"])))
    rec_b_db = clean_db_and_seed.scalar(select(Receipt).where(Receipt.order_id == UUID(order_b["id"])))
    assert rec_a_db is not None and rec_b_db is not None
    assert str(rec_a_db.user_id) == student_a["user"]["id"]
    assert str(rec_b_db.user_id) == student_b["user"]["id"]

    # Scenario 1 & 2: Student A and Student B each see ONLY their own receipts and orders (never each other's)
    my_recs_a = client.get("/api/v1/tokens/receipts/my", headers=student_a["headers"])
    my_recs_b = client.get("/api/v1/tokens/receipts/my", headers=student_b["headers"])
    assert my_recs_a.status_code == 200 and my_recs_b.status_code == 200
    assert {r["order_number"] for r in my_recs_a.json()} == {order_a["order_number"]}
    assert {r["order_number"] for r in my_recs_b.json()} == {order_b["order_number"]}

    # Attempting to pass forged userId query param MUST NEVER leak Student B's orders/receipts
    spoof_recs = client.get(f"/api/v1/tokens/receipts/my?userId={student_b['user']['id']}", headers=student_a["headers"])
    assert spoof_recs.status_code == 200
    assert {r["order_number"] for r in spoof_recs.json()} == {order_a["order_number"]}

    my_ords_a = client.get("/api/v1/orders/my-orders", headers=student_a["headers"])
    assert my_ords_a.status_code == 200
    assert {o["order_number"] for o in my_ords_a.json()} == {order_a["order_number"]}

    # Verify Cache-Control: private, no-store is strictly set on private receipt & order responses
    for resp in (my_recs_a, my_ords_a):
        cc = resp.headers.get("cache-control", "")
        assert "private" in cc and "no-store" in cc

    # Scenario 3 & 4: Student A modifies URL/receipt ID to access Student B's receipt, PDF, QR, ESC/POS, or order -> 403!
    forbidden_targets = [
        f"/api/v1/tokens/receipts/{order_b['order_number']}",
        f"/api/v1/tokens/receipts/{order_b['id']}",
        f"/api/v1/tokens/receipts/{rec_b_db.id}",
        f"/api/v1/tokens/receipts/{rec_b_db.receipt_number}",
        f"/api/v1/tokens/receipts/{rec_b_db.id}/pdf?format=a4",
        f"/api/v1/tokens/receipts/{order_b['order_number']}/qr.png",
        f"/api/v1/printing/receipts/{order_b['order_number']}/escpos",
        f"/api/v1/orders/{order_b['order_number']}",
        f"/api/v1/orders/{order_b['id']}",
    ]
    for url in forbidden_targets:
        res = client.get(url, headers=student_a["headers"])
        assert res.status_code == 403, f"Expected 403 for Student A accessing {url}, got {res.status_code}: {res.text}"

    # Nonexistent ID -> 404
    assert client.get(f"/api/v1/tokens/receipts/{uuid4()}", headers=student_a["headers"]).status_code == 404

    # Scenario 5 & 6: Unauthenticated visitor blocked from ALL receipt, order, & token board endpoints with HTTP 401!
    unauth_urls = [
        "/api/v1/tokens/receipts/my",
        "/api/v1/orders/my",
        "/api/v1/orders/my-orders",
        f"/api/v1/tokens/receipts/{order_a['order_number']}",
        f"/api/v1/tokens/receipts/{rec_a_db.id}",
        f"/api/v1/tokens/receipts/{order_a['order_number']}/pdf",
        f"/api/v1/tokens/receipts/{order_a['order_number']}/qr.png",
        f"/api/v1/printing/receipts/{order_a['order_number']}/escpos",
        f"/api/v1/orders/{order_a['order_number']}",
        "/api/v1/pickup/board",
        f"/api/v1/pickup/board/{main_canteen['id']}",
        "/api/v1/realtime/board/stream?once=true",
        "/api/v1/pickup/token-board",
    ]
    for url in unauth_urls:
        res = client.get(url)
        assert res.status_code == 401, f"Expected 401 for unauthenticated {url}, got {res.status_code}: {res.text}"

    # Logged-in students MUST NOT see internal pickup token board or operational token endpoints -> 403!
    assert client.get("/api/v1/pickup/board", headers=student_a["headers"]).status_code == 403
    assert client.get(f"/api/v1/pickup/board/{main_canteen['id']}", headers=student_a["headers"]).status_code == 403
    assert client.get("/api/v1/realtime/board/stream?once=true", headers=student_a["headers"]).status_code == 403
    assert client.get("/api/v1/pickup/token-board", headers=student_a["headers"]).status_code == 403

    # Scenario 7: Admin accesses authorized operational orders, receipts, & token board across canteens
    assert client.get(f"/api/v1/tokens/receipts/{order_b['order_number']}", headers=admin["headers"]).status_code == 200
    adm_board = client.get("/api/v1/pickup/board", headers=admin["headers"])
    assert adm_board.status_code == 200
    assert "no-store" in adm_board.headers.get("cache-control", "")

    # Scenario 8: Canteen manager & counter staff scope enforcement
    # Canteen manager can access their canteen, NOT other_canteen
    assert client.get(f"/api/v1/tokens/receipts/{order_a['order_number']}", headers=manager["headers"]).status_code == 200
    assert (
        client.get(f"/api/v1/pickup/board/{other_canteen['id']}", headers=manager["headers"]).status_code == 403
    )
    assert client.get(f"/api/v1/tokens/receipts/{order_a['order_number']}", headers=cashier["headers"]).status_code == 200

    # Create a counter-bound cashier assigned strictly to Counter 1 (c1) in main_canteen
    if c1["id"] != c2["id"]:
        cashier_role = clean_db_and_seed.scalar(select(Role).where(Role.name == "cashier"))
        assert cashier_role is not None
        counter1_user = User(
            email="counter1.staff@collegebites.edu",
            phone="+919876509988",
            full_name="Counter 1 Bound Cashier",
            password_hash=hash_password("Staff@12345"),
            is_active=True,
        )
        clean_db_and_seed.add(counter1_user)
        clean_db_and_seed.flush()
        clean_db_and_seed.add(UserRole(user_id=counter1_user.id, role_id=cashier_role.id, canteen_id=UUID(main_canteen["id"])))
        clean_db_and_seed.add(
            StaffProfile(
                user_id=counter1_user.id,
                employee_code="EMP-CNT1-SEC",
                designation="Counter 1 Cashier",
                assigned_canteen_id=UUID(main_canteen["id"]),
                assigned_counter_id=UUID(c1["id"]),
            )
        )
        clean_db_and_seed.commit()
        cnt1_auth = login_as(client, "counter1.staff@collegebites.edu", "Staff@12345")

        # Allowed for Counter 1 order/receipt, BLOCKED (403) for Counter 2 order/receipt
        assert client.get(f"/api/v1/tokens/receipts/{order_a['order_number']}", headers=cnt1_auth["headers"]).status_code == 200
        assert client.get(f"/api/v1/orders/{order_a['order_number']}", headers=cnt1_auth["headers"]).status_code == 200
        assert client.get(f"/api/v1/tokens/receipts/{order_b['order_number']}", headers=cnt1_auth["headers"]).status_code == 403
        assert client.get(f"/api/v1/orders/{order_b['order_number']}", headers=cnt1_auth["headers"]).status_code == 403
