from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select

from app.core.time_utils import today_college
from app.integrations.razorpay_client import razorpay_gateway
from app.models.order import Order, SlotReservation
from app.services.order_service import release_expired_slot_reservations
from tests.conftest import TestingSessionLocal, login_as


def test_auth_password_sessions_and_self_deactivate(client: TestClient):
    # Register a new universal customer with phone & email
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Kiran Rao",
            "email": "kiran.rao@aceec.ac.in",
            "phone": "+919876511122",
            "password": "InitialPass123",
            "college_id_number": "25AG1A0199",
            "department": "IT",
        },
    )
    assert reg.status_code == 201, reg.text
    first_refresh = reg.json()["refresh_token"]

    # Direct password login flow (OTP permanently removed)
    pw_login_res = client.post(
        "/api/v1/auth/login",
        json={"identifier": "+919876511122", "password": "InitialPass123", "device_info": "Mobile iOS"},
    )
    assert pw_login_res.status_code == 200, pw_login_res.text
    access = pw_login_res.json()["access_token"]
    hdrs = {"Authorization": f"Bearer {access}"}

    # Change password
    cp = client.post(
        "/api/v1/auth/change-password",
        headers=hdrs,
        json={"current_password": "InitialPass123", "new_password": "ChangedPass456"},
    )
    assert cp.status_code == 200, cp.text
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"identifier": "kiran.rao@aceec.ac.in", "password": "InitialPass123"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"identifier": "kiran.rao@aceec.ac.in", "password": "ChangedPass456"},
        ).status_code
        == 200
    )

    # Multi-device session management using current password
    tablet_login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "kiran.rao@aceec.ac.in", "password": "ChangedPass456", "device_info": "Tablet Safari"},
    )
    assert tablet_login.status_code == 200
    reset_login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "kiran.rao@aceec.ac.in", "password": "ChangedPass456", "device_info": "Desktop Chrome"},
    )
    assert reset_login.status_code == 200
    latest_hdrs = {"Authorization": f"Bearer {reset_login.json()['access_token']}"}

    # Session list & revoke non-current session
    sessions = client.get("/api/v1/auth/sessions", headers=latest_hdrs)
    assert sessions.status_code == 200
    sess_list = sessions.json()
    assert len(sess_list) >= 2
    assert any(s["is_current"] for s in sess_list)
    other = next(s for s in sess_list if s["device_info"] == "Tablet Safari")
    rev = client.delete(f"/api/v1/auth/sessions/{other['id']}", headers=latest_hdrs)
    assert rev.status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tablet_login.json()["refresh_token"]}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh}).status_code == 401

    # Re-login to test self-deactivation
    re_login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "kiran.rao@aceec.ac.in", "password": "ChangedPass456"},
    )
    assert re_login.status_code == 200
    re_hdrs = {"Authorization": f"Bearer {re_login.json()['access_token']}"}
    deact = client.delete("/api/v1/customers/me", headers=re_hdrs)
    assert deact.status_code == 200
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"identifier": "kiran.rao@aceec.ac.in", "password": "ChangedPass456"},
        ).status_code
        == 403
    )

    # Staff cannot self-deactivate via customer endpoint
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    assert client.delete("/api/v1/customers/me", headers=kitchen["headers"]).status_code == 403


def test_rbac_canteen_isolation_ssrf_printing_holidays_and_schedules(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")

    canteens = client.get("/api/v1/canteens").json()
    main = next(c for c in canteens if c["code"] == "MAIN")

    # Use existing 2nd counter (Snacks & Bakery Counter) — creating a 3rd counter is blocked by policy
    assert (
        client.post(
            "/api/v1/admin/canteens",
            headers=admin["headers"],
            json={
                "name": "Night Bakery",
                "slug": "night-bakery",
                "code": "NBK",
                "token_prefix": "N",
                "location": "West Block",
                "canteen_type": "bakery",
            },
        ).status_code
        == 400
    )
    nbk_id = next(c["id"] for c in canteens if c["code"] == "SNK")
    nbk_detail = client.get(f"/api/v1/canteens/{nbk_id}").json()
    nbk_counter_id = nbk_detail["counters"][0]["id"]
    nbk_kitchen_id = nbk_detail["kitchens"][0]["id"]

    # Update counter & kitchen, add station & pickup location
    assert (
        client.patch(
            f"/api/v1/admin/counters/{nbk_counter_id}",
            headers=admin["headers"],
            json={"name": "NBK Express Counter"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/admin/kitchens/{nbk_kitchen_id}",
            headers=admin["headers"],
            json={"name": "NBK Oven Kitchen"},
        ).status_code
        == 200
    )
    st = client.post(
        f"/api/v1/admin/kitchens/{nbk_kitchen_id}/stations",
        headers=admin["headers"],
        json={"name": "Pastry Deck", "station_type": "bakery"},
    )
    assert st.status_code == 201, st.text
    pl = client.post(
        f"/api/v1/admin/canteens/{nbk_id}/pickup-locations",
        headers=admin["headers"],
        json={"counter_id": nbk_counter_id, "name": "NBK Window A", "display_code": "W-A"},
    )
    assert pl.status_code == 201, pl.text
    assert len(client.get(f"/api/v1/admin/canteens/{nbk_id}/kitchen-stations", headers=admin["headers"]).json()) >= 1
    assert len(client.get(f"/api/v1/admin/canteens/{nbk_id}/pickup-locations", headers=admin["headers"]).json()) >= 1
    assert client.get("/api/v1/admin/system-events", headers=admin["headers"]).status_code == 200

    # Holiday patch & delete lifecycle
    today_col = today_college()
    hol = client.post(
        "/api/v1/admin/holidays",
        headers=admin["headers"],
        json={"canteen_id": nbk_id, "holiday_date": today_col.isoformat(), "title": "Oven Servicing", "is_full_day": True},
    )
    assert hol.status_code == 201
    hol_id = hol.json()["id"]
    hol_patch = client.patch(
        f"/api/v1/admin/holidays/{hol_id}",
        headers=admin["headers"],
        json={"title": "Oven Servicing Complete", "is_active": False},
    )
    assert hol_patch.status_code == 200
    assert hol_patch.json()["is_active"] is False
    assert client.delete(f"/api/v1/admin/holidays/{hol_id}", headers=admin["headers"]).status_code == 200

    # Canteen scope isolation: manager assigned strictly to MAIN cannot read NBK staff/kitchen/inventory
    scoped_mgr = client.post(
        "/api/v1/admin/users/staff",
        headers=admin["headers"],
        json={
            "full_name": "Main Scoped Manager",
            "email": "main.scoped@collegebites.edu",
            "password": "Staff@12345",
            "employee_code": "MGR-MAIN-99",
            "designation": "Canteen Manager",
            "role_names": ["canteen_manager"],
            "assigned_canteen_id": main["id"],
        },
    )
    assert scoped_mgr.status_code == 201, scoped_mgr.text
    mgr_hdrs = login_as(client, "main.scoped@collegebites.edu", "Staff@12345")["headers"]
    assert client.get(f"/api/v1/kitchen/canteens/{nbk_id}/orders", headers=mgr_hdrs).status_code == 403
    assert client.get(f"/api/v1/inventory/canteens/{nbk_id}/items", headers=mgr_hdrs).status_code == 403
    assert client.get(f"/api/v1/staff?canteen_id={nbk_id}", headers=mgr_hdrs).status_code == 403

    # Menu schedule enforcement + variants/categories delete
    items = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    coffee = next(i for i in items if "Coffee" in i["name"])
    tomorrow_weekday = (today_col.weekday() + 1) % 7
    sched = client.post(
        "/api/v1/menus/schedules",
        headers=admin["headers"],
        json={
            "canteen_id": main["id"],
            "name": "Tomorrow Special Only",
            "schedule_type": "special",
            "start_time": "00:00:00",
            "end_time": "23:59:59",
            "days_of_week": [tomorrow_weekday],
        },
    )
    assert sched.status_code == 201, sched.text
    sched_id = sched.json()["id"]
    assign = client.put(
        f"/api/v1/menus/schedules/{sched_id}/items",
        headers=admin["headers"],
        json={"food_item_ids": [coffee["id"]]},
    )
    assert assign.status_code == 200

    items_off = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    coffee_off = next(i for i in items_off if i["id"] == coffee["id"])
    assert coffee_off["is_schedule_active_now"] is False

    # Checkout off-schedule item must fail
    off_co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    )
    assert off_co.status_code == 400

    # Enable schedule for today -> becomes active again, then delete schedule
    assert (
        client.patch(
            f"/api/v1/menus/schedules/{sched_id}",
            headers=admin["headers"],
            json={"days_of_week": [today_col.weekday()]},
        ).status_code
        == 200
    )
    coffee_on = next(i for i in client.get(f"/api/v1/menus/canteens/{main['id']}/items").json() if i["id"] == coffee["id"])
    assert coffee_on["is_schedule_active_now"] is True
    assert client.delete(f"/api/v1/menus/schedules/{sched_id}", headers=admin["headers"]).status_code == 200

    # Variant CRUD & empty Category delete
    new_var = client.post(
        f"/api/v1/menus/items/{coffee['id']}/variants",
        headers=admin["headers"],
        json={"name": "Pitcher 500ml", "price_delta": "40.00"},
    )
    assert new_var.status_code == 201
    vid = new_var.json()["id"]
    assert client.patch(f"/api/v1/menus/variants/{vid}", headers=admin["headers"], json={"price_delta": "45.00"}).status_code == 200
    assert client.delete(f"/api/v1/menus/variants/{vid}", headers=admin["headers"]).status_code == 200

    empty_cat = client.post(
        "/api/v1/menus/categories",
        headers=admin["headers"],
        json={"canteen_id": nbk_id, "name": "Temp Category", "slug": "temp-category", "display_order": 9},
    )
    assert empty_cat.status_code == 201
    assert client.delete(f"/api/v1/menus/categories/{empty_cat.json()['id']}", headers=admin["headers"]).status_code == 200

    # Printing RBAC + SSRF protection on private network hosts
    pos_ord = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={"canteen_id": main["id"], "payment_method": "upi_pos", "items": [{"food_item_id": coffee["id"], "quantity": 1}]},
    )
    assert pos_ord.status_code == 201, pos_ord.text
    ono = pos_ord.json()["order_number"]
    assert (
        client.post(
            f"/api/v1/printing/receipts/{ono}/print",
            headers=student["headers"],
            json={"printer_target": "network_escpos", "network_host": "203.0.113.10", "network_port": 9100},
        ).status_code
        == 403
    )
    for blocked_host in ("127.0.0.1", "169.254.169.254", "localhost", "::1"):
        ssrf = client.post(
            f"/api/v1/printing/receipts/{ono}/print",
            headers=cashier["headers"],
            json={"printer_target": "network_escpos", "network_host": blocked_host, "network_port": 9100},
        )
        assert ssrf.status_code == 400


def test_loyalty_slot_rollback_guest_lookup_retry_qr_revoke_and_notifications(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")

    main = next(c for c in client.get("/api/v1/canteens").json() if c["code"] == "MAIN")
    cid = main["id"]
    biryani = next(i for i in client.get(f"/api/v1/menus/canteens/{cid}/items").json() if "Biryani" in i["name"])

    # Confirm initial paid order for student to establish referral code
    seed_ord = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={"canteen_id": cid, "payment_method": "razorpay", "use_cart": False, "direct_items": [{"food_item_id": biryani["id"], "quantity": 2}], "accepted_policy": True},
    ).json()
    sig0 = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=seed_ord["razorpay_order_id"], razorpay_payment_id="pay_seed_loy"
    )
    assert (
        client.post(
            "/api/v1/payments/razorpay/verify",
            headers=student["headers"],
            json={
                "order_id": seed_ord["id"],
                "razorpay_order_id": seed_ord["razorpay_order_id"],
                "razorpay_payment_id": "pay_seed_loy",
                "razorpay_signature": sig0,
                "payment_method": "upi",
            },
        ).status_code
        == 200
    )

    my_loy = client.get("/api/v1/promotions/loyalty/me", headers=student["headers"]).json()
    assert my_loy["referral_code"] is not None

    # Register second student and apply referral (+50 pts each)
    friend_reg = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Loyalty Friend",
            "email": "loy.friend@aceec.ac.in",
            "phone": "+919876540099",
            "password": "Password123",
            "referral_code": my_loy["referral_code"],
        },
    )
    assert friend_reg.status_code == 201
    friend_hdrs = {"Authorization": f"Bearer {friend_reg.json()['access_token']}"}
    friend_loy = client.get("/api/v1/promotions/loyalty/me", headers=friend_hdrs).json()
    assert friend_loy["points_balance"] >= 50

    # Create / get pickup slot for today
    today_col = today_college()
    slot_res = client.post(
        f"/api/v1/queue/canteens/{cid}/slots",
        headers=admin["headers"],
        json={"slot_date": today_col.isoformat(), "start_time": "12:00:00", "end_time": "13:00:00", "capacity": 20, "is_active": True},
    )
    assert slot_res.status_code == 200
    slot_id = slot_res.json()["id"]

    # Checkout pending Razorpay order using 10 loyalty points + pickup slot (coupons disabled)
    bad_coupon_co = client.post(
        "/api/v1/orders/checkout",
        headers=friend_hdrs,
        json={
            "canteen_id": cid,
            "payment_method": "razorpay",
            "coupon_code": "CAMPUS10",
            "use_cart": False,
            "direct_items": [{"food_item_id": biryani["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    )
    assert bad_coupon_co.status_code == 400

    co_pending = client.post(
        "/api/v1/orders/checkout",
        headers=friend_hdrs,
        json={
            "canteen_id": cid,
            "pickup_slot_id": slot_id,
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": biryani["id"], "quantity": 2}],
            "accepted_policy": True,
        },
    )
    assert co_pending.status_code == 201, co_pending.text
    pend_ord_id = co_pending.json()["id"]
    pend_ord_no = co_pending.json()["order_number"]

    # Expire reservation timestamp in DB and run release_expired_slot_reservations -> fails order & releases slot
    with TestingSessionLocal() as db:
        resv = db.scalar(select(SlotReservation).where(SlotReservation.order_id == UUID(pend_ord_id)))
        assert resv is not None
        resv.expires_at = datetime.now(timezone.utc) - timedelta(minutes=20)
        db.commit()
        released = release_expired_slot_reservations(db)
        assert released >= 1

    ord_after_exp = client.get(f"/api/v1/orders/{pend_ord_no}", headers=friend_hdrs).json()
    assert ord_after_exp["status"] == "PAYMENT_FAILED"

    # Guest checkout (direct without OTP) -> Razorpay fail -> Retry with Razorpay -> Verify -> Guest lookup -> Staff QR revoke
    g_phone = "+919800012345"
    g_co = client.post(
        "/api/v1/orders/checkout",
        json={
            "canteen_id": cid,
            "guest_name": "Retry Guest",
            "guest_phone": g_phone,
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": biryani["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    ).json()
    guest_tok = g_co["guest_access_token"]
    assert (
        client.post(
            f"/api/v1/payments/razorpay/fail?guest_token={guest_tok}",
            json={"order_id": g_co["id"], "reason": "Insufficient funds"},
        ).status_code
        == 200
    )

    retried = client.post(
        f"/api/v1/payments/retry/{g_co['id']}?guest_token={guest_tok}",
        json={"payment_method": "razorpay"},
    )
    assert retried.status_code == 200, retried.text
    rp_oid = retried.json()["razorpay_order_id"]
    assert rp_oid is not None
    sig_retry = razorpay_gateway.compute_test_payment_signature(razorpay_order_id=rp_oid, razorpay_payment_id="pay_retry_1")
    confirmed = client.post(
        "/api/v1/payments/razorpay/verify",
        json={
            "order_id": g_co["id"],
            "razorpay_order_id": rp_oid,
            "razorpay_payment_id": "pay_retry_1",
            "razorpay_signature": sig_retry,
            "payment_method": "card",
            "guest_access_token": guest_tok,
        },
    )
    assert confirmed.status_code == 200
    old_qr = confirmed.json()["qr_token_raw"]
    assert old_qr is not None

    # Guest order lookup (order_number + guest_contact, no OTP)
    looked_up = client.post(
        "/api/v1/orders/guest/lookup",
        json={"order_number": g_co["order_number"], "guest_contact": g_phone},
    )
    assert looked_up.status_code == 200
    assert any(o["order_number"] == g_co["order_number"] for o in looked_up.json())

    # Revoke QR & issue replacement -> cashier disallowed (403); admin succeeds; old QR INVALID_QR, new QR matches order
    assert (
        client.post(
            f"/api/v1/tokens/orders/{g_co['id']}/revoke-qr",
            headers=cashier["headers"],
            json={"reason": "Lost QR test", "reissue": True},
        ).status_code
        == 403
    )
    revoked = client.post(
        f"/api/v1/tokens/orders/{g_co['id']}/revoke-qr",
        headers=admin["headers"],
        json={"reason": "Reissued after phone change", "reissue": True},
    )
    assert revoked.status_code == 200, revoked.text
    new_qr = revoked.json()["qr_payload"].split("#token=")[-1]
    assert new_qr != old_qr

    # Notifications mark-all-read + announcement delete
    mark_all = client.post("/api/v1/notifications/mark-all-read", headers=student["headers"])
    assert mark_all.status_code == 200
    notifs = client.get("/api/v1/notifications/my", headers=student["headers"]).json()
    assert all(n["is_read"] for n in notifs)
    ann = client.post(
        "/api/v1/notifications/announcements",
        headers=admin["headers"],
        json={"title": "Temp Notice", "body": "Testing delete", "severity": "info"},
    ).json()
    assert client.delete(f"/api/v1/notifications/announcements/{ann['id']}", headers=admin["headers"]).status_code == 200

    # Verify old QR rejected as INVALID_QR while new QR matches order
    old_chk = client.post("/api/v1/pickup/verify", headers=pickup["headers"], json={"qr_payload": old_qr}).json()
    assert old_chk["result_code"] == "INVALID_QR"
    new_chk = client.post("/api/v1/pickup/verify", headers=pickup["headers"], json={"qr_payload": new_qr}).json()
    assert new_chk["order_number"] == g_co["order_number"]


def test_inventory_fefo_transfers_staff_leave_support_guest_and_ws_auth(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    inv_mgr = login_as(client, "inventory@collegebites.edu", "Staff@12345")
    cashier = login_as(client, "cashier@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    mgr = login_as(client, "manager@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")

    canteens = client.get("/api/v1/canteens").json()
    main = next(c for c in canteens if c["code"] == "MAIN")
    mid = main["id"]
    thb_id = next(c["id"] for c in canteens if c["code"] == "SNK")

    # Create ingredient with EXPIRED initial batch (50g)
    today_col = today_college()
    basil = client.post(
        "/api/v1/inventory/ingredients",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": mid,
            "name": "Fresh Basil",
            "sku": "BSL-TEST-1",
            "unit": "grams",
            "initial_quantity": "50.000",
            "reorder_level": "15.000",
            "unit_cost": "0.50",
            "expiry_date": (today_col - timedelta(days=2)).isoformat(),
        },
    ).json()
    basil_ing_id = basil["ingredient_id"]
    basil_inv_id = basil["inventory_item_id"]

    # Receive PO in 2 partial steps (40g then 60g) with non-expired future expiry
    suppliers = client.get("/api/v1/inventory/suppliers", headers=inv_mgr["headers"]).json()
    sup_id = suppliers[0]["id"]
    assert client.patch(f"/api/v1/inventory/suppliers/{sup_id}", headers=inv_mgr["headers"], json={"phone": "+919900112233"}).status_code == 200
    assert client.patch(f"/api/v1/inventory/items/{basil_inv_id}", headers=inv_mgr["headers"], json={"reorder_level": "18.000"}).status_code == 200

    po = client.post(
        "/api/v1/inventory/purchase-orders",
        headers=inv_mgr["headers"],
        json={
            "canteen_id": mid,
            "supplier_id": sup_id,
            "items": [
                {
                    "ingredient_id": basil_ing_id,
                    "quantity_ordered": "100.000",
                    "unit_cost": "0.50",
                    "expiry_date": (today_col + timedelta(days=10)).isoformat(),
                }
            ],
        },
    ).json()
    assert po["status"] == "pending_approval"
    assert client.post(f"/api/v1/inventory/purchase-orders/{po['id']}/status", headers=mgr["headers"], json={"status": "approved"}).status_code == 200
    assert client.post(f"/api/v1/inventory/purchase-orders/{po['id']}/status", headers=inv_mgr["headers"], json={"status": "ordered"}).status_code == 200
    p1 = client.post(
        f"/api/v1/inventory/purchase-orders/{po['id']}/receive",
        headers=inv_mgr["headers"],
        json={"received_items": [{"ingredient_id": basil_ing_id, "quantity_received": "40.000"}]},
    )
    assert p1.status_code == 200 and p1.json()["status"] == "partial"
    p2 = client.post(
        f"/api/v1/inventory/purchase-orders/{po['id']}/receive",
        headers=inv_mgr["headers"],
        json={"received_items": [{"ingredient_id": basil_ing_id, "quantity_received": "60.000"}]},
    )
    assert p2.status_code == 200 and p2.json()["status"] == "received"

    # Multi-ingredient recipe & GET recipe
    items = client.get(f"/api/v1/menus/canteens/{mid}/items").json()
    coffee = next(i for i in items if "Coffee" in i["name"])
    inv_list = client.get(f"/api/v1/inventory/canteens/{mid}/items", headers=inv_mgr["headers"]).json()
    second_ing = next(i for i in inv_list if i["ingredient_id"] != basil_ing_id)
    rec = client.put(
        f"/api/v1/inventory/recipes/{coffee['id']}",
        headers=inv_mgr["headers"],
        json={
            "yield_portions": 1,
            "ingredients": [
                {"ingredient_id": basil_ing_id, "quantity_required": "20.000"},
                {"ingredient_id": second_ing["ingredient_id"], "quantity_required": "5.000"},
            ],
        },
    )
    assert rec.status_code == 200
    rec_get = client.get(f"/api/v1/inventory/recipes/{coffee['id']}", headers=inv_mgr["headers"])
    assert rec_get.status_code == 200 and len(rec_get.json()["ingredients"]) == 2

    # POS order deducts 20g from non-expired 100g batch (80g usable remains + 50g expired = 130g total)
    pos = client.post(
        "/api/v1/pos/orders",
        headers=cashier["headers"],
        json={"canteen_id": mid, "payment_method": "upi_pos", "items": [{"food_item_id": coffee["id"], "quantity": 1}]},
    )
    assert pos.status_code == 201
    basil_after = next(
        i for i in client.get(f"/api/v1/inventory/canteens/{mid}/items", headers=inv_mgr["headers"]).json() if i["ingredient_id"] == basil_ing_id
    )
    assert Decimal(basil_after["current_quantity"]) == Decimal("130.000")

    # Stock transfer exceeding 80g usable (e.g. 90g) must fail because 50g is expired!
    bad_xfer = client.post(
        "/api/v1/inventory/transfers",
        headers=inv_mgr["headers"],
        json={"from_canteen_id": mid, "to_canteen_id": thb_id, "ingredient_id": basil_ing_id, "quantity": "90.000"},
    )
    assert bad_xfer.status_code == 400
    good_xfer = client.post(
        "/api/v1/inventory/transfers",
        headers=inv_mgr["headers"],
        json={"from_canteen_id": mid, "to_canteen_id": thb_id, "ingredient_id": basil_ing_id, "quantity": "30.000", "notes": "Evening prep"},
    )
    assert good_xfer.status_code == 200
    assert len(client.get(f"/api/v1/inventory/canteens/{mid}/transfers", headers=inv_mgr["headers"]).json()) >= 1
    assert len(client.get(f"/api/v1/inventory/canteens/{mid}/movements", headers=inv_mgr["headers"]).json()) >= 1

    # Staff shift CRUD + self leave + review + check-in conflict
    sh = client.post(
        "/api/v1/staff/shifts",
        headers=mgr["headers"],
        json={
            "staff_user_id": kitchen["user"]["id"],
            "canteen_id": mid,
            "shift_date": today_col.isoformat(),
            "start_time": "08:00:00",
            "end_time": "16:00:00",
            "shift_type": "morning",
        },
    )
    assert sh.status_code == 201
    sh_id = sh.json()["id"]
    assert client.patch(f"/api/v1/staff/shifts/{sh_id}", headers=mgr["headers"], json={"end_time": "17:00:00"}).status_code == 200
    assert client.delete(f"/api/v1/staff/shifts/{sh_id}", headers=mgr["headers"]).status_code == 200

    lv = client.post(
        "/api/v1/staff/attendance/leave/request",
        headers=kitchen["headers"],
        json={"canteen_id": mid, "attendance_date": today_col.isoformat(), "reason": "Medical checkup"},
    )
    assert lv.status_code == 201 and lv.json()["status"] == "leave_pending"
    rev_lv = client.patch(
        f"/api/v1/staff/attendance/{lv.json()['id']}/review",
        headers=mgr["headers"],
        json={"approved": True},
    )
    assert rev_lv.status_code == 200 and rev_lv.json()["status"] == "leave"
    assert client.post(f"/api/v1/staff/attendance/check-in?canteen_id={mid}", headers=kitchen["headers"]).status_code == 409

    # Review moderation & guest support ticket lookup/thread/reply
    rev = client.post(
        "/api/v1/support/reviews",
        headers=student["headers"],
        json={"food_item_id": coffee["id"], "rating": 2, "comment": "Moderation test comment"},
    )
    assert rev.status_code == 201
    rev_id = rev.json()["id"]
    hide = client.patch(f"/api/v1/support/reviews/{rev_id}/visibility", headers=admin["headers"], json={"is_visible": False})
    assert hide.status_code == 200
    pub_revs = client.get(f"/api/v1/support/items/{coffee['id']}/reviews").json()
    assert not any(r["id"] == rev_id for r in pub_revs)

    sup_phone = "+919800055566"
    tkt = client.post(
        "/api/v1/support/tickets",
        json={"canteen_id": mid, "guest_name": "Ticket Guest", "guest_phone": sup_phone, "category": "app_help", "subject": "Track token", "description": "Need help checking order"},
    )
    assert tkt.status_code == 201
    tkt_id = tkt.json()["id"]
    tkt_no = tkt.json()["ticket_number"]

    tl = client.post("/api/v1/support/tickets/guest/lookup", json={"ticket_number": tkt_no, "guest_phone": sup_phone})
    assert tl.status_code == 200 and any(x["id"] == tkt_id for x in tl.json())
    th = client.post(f"/api/v1/support/tickets/{tkt_id}/guest-thread", json={"ticket_number": tkt_no, "guest_phone": sup_phone})
    assert th.status_code == 200
    gm = client.post(f"/api/v1/support/tickets/{tkt_id}/guest-messages", json={"ticket_number": tkt_no, "guest_phone": sup_phone, "message": "Found my token, thanks!"})
    assert gm.status_code == 200

    # WebSocket security checks
    pos_ord_id = pos.json()["id"]
    with pytest.raises(WebSocketDisconnect) as exc_ord:
        with client.websocket_connect(f"/api/v1/ws/orders/{pos_ord_id}") as ws:
            ws.receive_text()
    assert exc_ord.value.code == 1008

    with pytest.raises(WebSocketDisconnect) as exc_kit:
        with client.websocket_connect(f"/api/v1/ws/kitchen/{mid}?token={student['token']}") as ws:
            ws.receive_text()
    assert exc_kit.value.code == 1008

    with client.websocket_connect(f"/api/v1/ws/kitchen/{mid}?token={kitchen['token']}") as ws:
        ws.send_text("ping")
        assert '"pong"' in ws.receive_text()

    with client.websocket_connect(f"/api/v1/ws/notifications/{student['user']['id']}?token={student['token']}") as ws:
        ws.send_text("ping")
        assert '"pong"' in ws.receive_text()

    with pytest.raises(WebSocketDisconnect) as exc_board:
        with client.websocket_connect(f"/api/v1/ws/board/{mid}") as ws:
            ws.receive_text()
    assert exc_board.value.code == 1008

    with client.websocket_connect(f"/api/v1/ws/board/{mid}?token={kitchen['token']}") as ws:
        ws.send_text("ping")
        assert '"pong"' in ws.receive_text()
