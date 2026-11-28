"""
Phase 34: Complete Pricing Cleanup (Exact Listed Prices, Zero Discounts, Zero Additional Checkout Tax)
+ Fixed Two-Counter College Cafeteria Structure (Main Canteen + Snacks & Bakery Counter).

Covers all 12 Pricing Test Scenarios and all 13 Counter Test Scenarios plus Alembic migration safety.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import importlib.util
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from app.core.config import settings
from app.core.database import SessionLocal
from app.integrations.razorpay_client import razorpay_gateway
from app.models.base import Base
from app.models.college import Canteen, Counter, Kitchen
from app.models.menu import FoodCategory, FoodItem
from app.models.order import Cart, Order, OrderItem
from app.models.payment import Invoice, Payment, PickupToken, Receipt
from app.models.promotion import Coupon
from app.services.seed_service import seed_live_production_advanced_data
from tests.conftest import login_as


def _rzp_sig(order_id: str, payment_id: str) -> str:
    return razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=order_id, razorpay_payment_id=payment_id
    )


def _rzp_webhook_sig(raw_body: bytes) -> str:
    return razorpay_gateway.compute_test_webhook_signature(raw_body=raw_body)


def _get_counters(client: TestClient) -> tuple[dict, dict]:
    canteens = client.get("/api/v1/canteens").json()
    main = next(c for c in canteens if c["slug"] == "main-canteen")
    snacks = next(c for c in canteens if c["slug"] == "snacks-bakery")
    return main, snacks


def _create_priced_item(client: TestClient, admin_headers: dict, canteen_id: str, category_id: str, name: str, price: str) -> dict:
    slug = f"p34-{uuid4().hex[:8]}"
    r = client.post(
        "/api/v1/menus/items",
        headers=admin_headers,
        json={
            "canteen_id": canteen_id,
            "category_id": category_id,
            "name": name,
            "slug": slug,
            "base_price": price,
            "is_veg": True,
            "prep_time_minutes": 5,
            "tax_rate_percent": "5.00",  # Backend must ignore/zero any extra checkout tax
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# =============================================================================
# PART 1: COMPLETE PRICING CLEANUP TESTS (12 SCENARIOS)
# =============================================================================


def test_01_single_item_exact_pricing(client: TestClient):
    """Scenario 1: Single item purchase (Rs.50 x 1 = Rs.50.00 exact)."""
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    main, _ = _get_counters(client)
    items = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    coffee = next(i for i in items if Decimal(i["base_price"]) == Decimal("50.00"))

    co = client.post(
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
    assert co.status_code == 201, co.text
    order = co.json()
    assert Decimal(order["subtotal_amount"]) == Decimal("50.00")
    assert Decimal(order["discount_amount"]) == Decimal("0.00")
    assert Decimal(order["tax_amount"]) == Decimal("0.00")
    assert Decimal(order["total_amount"]) == Decimal("50.00")
    assert len(order["items"]) == 1
    assert Decimal(order["items"][0]["tax_amount"]) == Decimal("0.00")
    assert Decimal(order["items"][0]["line_total"]) == Decimal("50.00")


def test_02_multiple_items_exact_pricing(client: TestClient):
    """Scenario 2: Multiple item purchase (Rs.75 + Rs.100 + Rs.40 = Rs.215.00 exact)."""
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    main, _ = _get_counters(client)
    cats = client.get(f"/api/v1/menus/canteens/{main['id']}/categories").json()
    cat_id = cats[0]["id"]

    it1 = _create_priced_item(client, admin["headers"], main["id"], cat_id, "Item A 75", "75.00")
    it2 = _create_priced_item(client, admin["headers"], main["id"], cat_id, "Item B 100", "100.00")
    it3 = _create_priced_item(client, admin["headers"], main["id"], cat_id, "Item C 40", "40.00")

    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [
                {"food_item_id": it1["id"], "quantity": 1},
                {"food_item_id": it2["id"], "quantity": 1},
                {"food_item_id": it3["id"], "quantity": 1},
            ],
            "accepted_policy": True,
        },
    )
    assert co.status_code == 201, co.text
    order = co.json()
    assert Decimal(order["subtotal_amount"]) == Decimal("215.00")
    assert Decimal(order["discount_amount"]) == Decimal("0.00")
    assert Decimal(order["tax_amount"]) == Decimal("0.00")
    assert Decimal(order["total_amount"]) == Decimal("215.00")


def test_03_multiple_quantities_exact_pricing(client: TestClient):
    """Scenario 3: Multiple quantities (Rs.50 x 2 = Rs.100.00 exact)."""
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    main, _ = _get_counters(client)
    items = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    coffee = next(i for i in items if Decimal(i["base_price"]) == Decimal("50.00"))

    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 2}],
            "accepted_policy": True,
        },
    )
    assert co.status_code == 201, co.text
    order = co.json()
    assert Decimal(order["subtotal_amount"]) == Decimal("100.00")
    assert Decimal(order["discount_amount"]) == Decimal("0.00")
    assert Decimal(order["tax_amount"]) == Decimal("0.00")
    assert Decimal(order["total_amount"]) == Decimal("100.00")


def test_04_cart_quantity_updates_recalculate_exact(client: TestClient):
    """Scenario 4: Cart quantity updates (1 -> 3 -> 2 -> 0) compute exact totals with zero tax/discount."""
    guest_headers = {"X-Guest-Session-ID": f"p34-cart-{uuid4().hex[:8]}"}
    main, _ = _get_counters(client)
    items = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    coffee = next(i for i in items if Decimal(i["base_price"]) == Decimal("50.00"))

    r1 = client.post(
        "/api/v1/carts/items",
        headers=guest_headers,
        json={"canteen_id": main["id"], "food_item_id": coffee["id"], "quantity": 1},
    )
    assert r1.status_code == 200, r1.text
    c1 = r1.json()
    assert Decimal(c1["subtotal_amount"]) == Decimal("50.00")
    assert Decimal(c1["discount_amount"]) == Decimal("0.00")
    assert Decimal(c1["tax_amount"]) == Decimal("0.00")
    assert Decimal(c1["total_amount"]) == Decimal("50.00")

    ci_id = c1["items"][0]["id"]
    r2 = client.patch(f"/api/v1/carts/items/{ci_id}", headers=guest_headers, json={"quantity": 3})
    assert r2.status_code == 200
    assert Decimal(r2.json()["total_amount"]) == Decimal("150.00")
    assert Decimal(r2.json()["tax_amount"]) == Decimal("0.00")

    r3 = client.patch(f"/api/v1/carts/items/{ci_id}", headers=guest_headers, json={"quantity": 2})
    assert r3.status_code == 200
    assert Decimal(r3.json()["total_amount"]) == Decimal("100.00")

    r4 = client.patch(f"/api/v1/carts/items/{ci_id}", headers=guest_headers, json={"quantity": 0})
    assert r4.status_code == 200
    assert Decimal(r4.json()["total_amount"]) == Decimal("0.00")
    assert r4.json()["items"] == []


def test_05_item_price_changes_backend_authoritative(client: TestClient):
    """Scenario 5: Admin item price change in DB immediately updates cart and checkout totals."""
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    main, _ = _get_counters(client)
    cat_id = client.get(f"/api/v1/menus/canteens/{main['id']}/categories").json()[0]["id"]
    item = _create_priced_item(client, admin["headers"], main["id"], cat_id, "Dynamic Price Sandwich", "50.00")

    guest_headers = {"X-Guest-Session-ID": f"p34-dyn-{uuid4().hex[:8]}"}
    add_r = client.post(
        "/api/v1/carts/items",
        headers=guest_headers,
        json={"canteen_id": main["id"], "food_item_id": item["id"], "quantity": 2},
    )
    assert add_r.status_code == 200
    assert Decimal(add_r.json()["total_amount"]) == Decimal("100.00")

    # Admin updates price from 50 -> 65
    upd = client.patch(f"/api/v1/menus/items/{item['id']}", headers=admin["headers"], json={"base_price": "65.00"})
    assert upd.status_code == 200

    cart_after = client.get(f"/api/v1/carts?canteen_id={main['id']}", headers=guest_headers).json()
    assert Decimal(cart_after["subtotal_amount"]) == Decimal("130.00")
    assert Decimal(cart_after["total_amount"]) == Decimal("130.00")
    assert Decimal(cart_after["tax_amount"]) == Decimal("0.00")

    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": item["id"], "quantity": 2}],
            "accepted_policy": True,
        },
    )
    assert co.status_code == 201
    assert Decimal(co.json()["total_amount"]) == Decimal("130.00")


def test_06_discounts_coupons_loyalty_and_extra_tax_disabled_everywhere(client: TestClient):
    """Scenario 6: All coupon, discount, loyalty redemption, and extra-tax configuration paths are blocked; legacy DB records ignored."""
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    main, _ = _get_counters(client)
    items = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    biryani = next(i for i in items if "Biryani" in i["name"])

    # 1. Public coupons endpoint always returns []
    assert client.get("/api/v1/promotions/coupons").json() == []

    # 2. Creating/validating/applying coupons all rejected with 400
    assert (
        client.post(
            "/api/v1/promotions/coupons",
            headers=admin["headers"],
            json={"code": "OFF20", "title": "20% Off", "discount_type": "percentage", "discount_value": "20.00"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/promotions/coupons/validate",
            headers=student["headers"],
            json={"canteen_id": main["id"], "coupon_code": "OFF20", "subtotal_amount": "200.00"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/carts/coupon",
            headers=student["headers"],
            json={"canteen_id": main["id"], "coupon_code": "OFF20"},
        ).status_code
        == 400
    )

    # 3. Checkout with coupon_code or redeem_loyalty_points rejected with 400
    assert (
        client.post(
            "/api/v1/orders/checkout",
            headers=student["headers"],
            json={
                "canteen_id": main["id"],
                "payment_method": "razorpay",
                "coupon_code": "CAMPUS15",
                "use_cart": False,
                "direct_items": [{"food_item_id": biryani["id"], "quantity": 1}],
                "accepted_policy": True,
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/orders/checkout",
            headers=student["headers"],
            json={
                "canteen_id": main["id"],
                "payment_method": "razorpay",
                "redeem_loyalty_points": 20,
                "use_cart": False,
                "direct_items": [{"food_item_id": biryani["id"], "quantity": 1}],
                "accepted_policy": True,
            },
        ).status_code
        == 400
    )

    # 4. Admin cannot re-enable additional checkout tax on college settings or canteen
    assert (
        client.put(
            "/api/v1/admin/college",
            headers=admin["headers"],
            json={"default_tax_rate_percent": "5.00"},
        ).status_code
        == 400
    )
    assert (
        client.patch(
            f"/api/v1/admin/canteens/{main['id']}",
            headers=admin["headers"],
            json={"tax_rate_percent": "5.00"},
        ).status_code
        == 400
    )

    # 5. Legacy DB coupon + legacy cart.coupon_code are completely ignored and never reduce totals
    legacy_guest = {"X-Guest-Session-ID": f"p34-legacy-{uuid4().hex[:8]}"}
    client.post(
        "/api/v1/carts/items",
        headers=legacy_guest,
        json={"canteen_id": main["id"], "food_item_id": biryani["id"], "quantity": 1},
    )
    with SessionLocal() as db:
        db.add(
            Coupon(
                code=f"OLD{uuid4().hex[:4].upper()}",
                title="Legacy Promo",
                discount_type="percentage",
                discount_value=Decimal("50.00"),
                is_active=True,
            )
        )
        cart_row = db.scalar(select(Cart).where(Cart.guest_session_id == legacy_guest["X-Guest-Session-ID"]))
        assert cart_row is not None
        cart_row.coupon_code = "OLD50"
        db.commit()

    cart_summary = client.get(f"/api/v1/carts?canteen_id={main['id']}", headers=legacy_guest).json()
    assert cart_summary["coupon_code"] is None
    assert Decimal(cart_summary["discount_amount"]) == Decimal("0.00")
    assert Decimal(cart_summary["tax_amount"]) == Decimal("0.00")
    assert Decimal(cart_summary["total_amount"]) == Decimal(cart_summary["subtotal_amount"])
    assert client.get("/api/v1/promotions/coupons").json() == []

    # 6. Meal Plan subscription also charges exact listed price with zero extra tax
    with SessionLocal() as db:
        seed_live_production_advanced_data(db)
    plans = client.get("/api/v1/meal-plans").json()
    assert len(plans) >= 1
    p0 = plans[0]
    assert Decimal(p0["tax_amount"]) == Decimal("0.00")
    assert Decimal(p0["total_price"]) == Decimal(p0["price"])
    sub = client.post(
        f"/api/v1/meal-plans/{p0['id']}/subscribe",
        headers=student["headers"],
        json={"payment_method": "razorpay"},
    )
    assert sub.status_code == 201, sub.text
    assert Decimal(sub.json()["tax_amount"]) == Decimal("0.00")
    assert Decimal(sub.json()["total_amount"]) == Decimal(p0["price"])


def test_07_successful_payment_exact_amount_razorpay_only(client: TestClient):
    """Scenario 7: Razorpay verified payment charges exact subtotal and generates token + QR + receipt."""
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    main, _ = _get_counters(client)
    items = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    dosa = next(i for i in items if "Dosa" in i["name"])
    expected = Decimal(dosa["base_price"]) * 2  # 55 x 2 = 110.00

    # Razorpay flow
    co_r = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": dosa["id"], "quantity": 2}],
            "accepted_policy": True,
        },
    )
    assert co_r.status_code == 201
    ord_r = co_r.json()
    assert Decimal(ord_r["total_amount"]) == expected
    pay_id = f"pay_p34_{uuid4().hex[:8]}"
    ver_r = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": ord_r["id"],
            "razorpay_order_id": ord_r["razorpay_order_id"],
            "razorpay_payment_id": pay_id,
            "razorpay_signature": _rzp_sig(ord_r["razorpay_order_id"], pay_id),
        },
    )
    assert ver_r.status_code == 200, ver_r.text
    conf_r = ver_r.json()
    assert conf_r["payment_status"] == "CONFIRMED"
    assert Decimal(conf_r["total_amount"]) == expected
    assert conf_r["pickup_token_code"] and conf_r["pickup_token_code"].startswith("A")
    assert conf_r["qr_verification_path"]

    with SessionLocal() as db:
        pay_row = db.scalar(select(Payment).where(Payment.order_id == UUID(ord_r["id"])))
        assert pay_row is not None and pay_row.amount == expected and pay_row.status == "CONFIRMED"

    rec_r = client.get(f"/api/v1/tokens/receipts/{ord_r['order_number']}", headers=student["headers"])
    assert rec_r.status_code == 200
    snap = rec_r.json()
    assert Decimal(snap["subtotal_amount"]) == expected
    assert Decimal(snap["discount_amount"]) == Decimal("0.00")
    assert Decimal(snap["tax_amount"]) == Decimal("0.00")
    assert Decimal(snap["total_paid"]) == expected
    assert "statutory taxes" in (snap.get("tax_inclusive_notice") or "").lower()


def test_08_failed_payment_handling(client: TestClient):
    """Scenario 8: Failed payment marks order PAYMENT_FAILED, releases slot, and issues no token."""
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    main, _ = _get_counters(client)
    coffee = next(i for i in client.get(f"/api/v1/menus/canteens/{main['id']}/items").json() if "Coffee" in i["name"])
    slots = client.get(f"/api/v1/orders/slots/{main['id']}").json()
    slot_id = slots[0]["id"]
    reserved_before = slots[0]["reserved_count"]

    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "pickup_slot_id": slot_id,
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    )
    assert co.status_code == 201
    ord_id = co.json()["id"]
    fail = client.post(
        "/api/v1/payments/razorpay/fail",
        headers=student["headers"],
        json={"order_id": ord_id, "reason": "UPI PIN cancelled by user"},
    )
    assert fail.status_code == 200, fail.text
    assert fail.json()["status"] == "PAYMENT_FAILED"
    assert fail.json()["payment_status"] == "FAILED"
    assert fail.json()["pickup_token_code"] is None

    slots_after = client.get(f"/api/v1/orders/slots/{main['id']}").json()
    slot_after = next(s for s in slots_after if s["id"] == slot_id)
    assert slot_after["reserved_count"] == reserved_before


def test_09_duplicate_payment_callback_and_webhook_idempotency(client: TestClient):
    """Scenario 9: Duplicate payment verify calls and webhooks remain strictly idempotent."""
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    main, _ = _get_counters(client)
    coffee = next(i for i in client.get(f"/api/v1/menus/canteens/{main['id']}/items").json() if "Coffee" in i["name"])

    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    ).json()
    pay_id = f"pay_dup_{uuid4().hex[:8]}"
    payload = {
        "order_id": co["id"],
        "razorpay_order_id": co["razorpay_order_id"],
        "razorpay_payment_id": pay_id,
        "razorpay_signature": _rzp_sig(co["razorpay_order_id"], pay_id),
    }
    v1 = client.post("/api/v1/payments/razorpay/verify", headers=student["headers"], json=payload)
    v2 = client.post("/api/v1/payments/razorpay/verify", headers=student["headers"], json=payload)
    assert v1.status_code == 200 and v2.status_code == 200
    assert v1.json()["pickup_token_code"] == v2.json()["pickup_token_code"]

    # Replay via webhook
    import json

    wh_body = json.dumps({
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": pay_id,
                    "order_id": co["razorpay_order_id"],
                    "amount": int(Decimal(co["total_amount"]) * 100),
                }
            }
        },
    }).encode()
    wh = client.post(
        "/api/v1/payments/razorpay/webhook",
        content=wh_body,
        headers={"X-Razorpay-Signature": _rzp_webhook_sig(wh_body), "Content-Type": "application/json"},
    )
    assert wh.status_code == 200, wh.text

    with SessionLocal() as db:
        oid = UUID(co["id"])
        assert len(db.scalars(select(Payment).where(Payment.order_id == oid, Payment.status == "CONFIRMED")).all()) == 1
        assert len(db.scalars(select(PickupToken).where(PickupToken.order_id == oid)).all()) == 1
        assert len(db.scalars(select(Receipt).where(Receipt.order_id == oid)).all()) == 1
        assert len(db.scalars(select(Invoice).where(Invoice.order_id == oid)).all()) == 1


def test_10_order_history_matches_exact_totals(client: TestClient):
    """Scenario 10: Customer order history & admin order list report exact totals (subtotal==total, tax==0, discount==0)."""
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    main, _ = _get_counters(client)
    biryani = next(i for i in client.get(f"/api/v1/menus/canteens/{main['id']}/items").json() if "Biryani" in i["name"])

    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": biryani["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    ).json()
    pay_id_10 = f"pay_p34_10_{uuid4().hex[:8]}"
    client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": co["id"],
            "razorpay_order_id": co["razorpay_order_id"],
            "razorpay_payment_id": pay_id_10,
            "razorpay_signature": _rzp_sig(co["razorpay_order_id"], pay_id_10),
        },
    )

    my_orders = client.get("/api/v1/orders/my", headers=student["headers"]).json()
    found = next(o for o in my_orders if o["id"] == co["id"])
    assert Decimal(found["subtotal_amount"]) == Decimal(biryani["base_price"])
    assert Decimal(found["discount_amount"]) == Decimal("0.00")
    assert Decimal(found["tax_amount"]) == Decimal("0.00")
    assert Decimal(found["total_amount"]) == Decimal(biryani["base_price"])

    admin_orders = client.get(f"/api/v1/admin/orders?canteen_id={main['id']}", headers=admin["headers"]).json()
    found_admin = next(o for o in admin_orders if o["id"] == co["id"])
    assert Decimal(found_admin["total_amount"]) == Decimal(biryani["base_price"])


def test_11_invoice_generation_statutory_compliance_and_historical_preservation(client: TestClient):
    """Scenario 11: New invoices reflect exact listed prices + statutory tax-inclusive notice; historical taxed invoices preserved."""
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    main, _ = _get_counters(client)
    coffee = next(i for i in client.get(f"/api/v1/menus/canteens/{main['id']}/items").json() if "Coffee" in i["name"])

    co = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 2}],
            "accepted_policy": True,
        },
    ).json()
    pay_id_11 = f"pay_p34_11_{uuid4().hex[:8]}"
    client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": co["id"],
            "razorpay_order_id": co["razorpay_order_id"],
            "razorpay_payment_id": pay_id_11,
            "razorpay_signature": _rzp_sig(co["razorpay_order_id"], pay_id_11),
        },
    )

    inv_res = client.get(f"/api/v1/invoices/{co['id']}", headers=student["headers"])
    assert inv_res.status_code == 200, inv_res.text
    inv = inv_res.json()
    assert Decimal(inv["subtotal_amount"]) == Decimal("100.00")
    assert Decimal(inv["discount_amount"]) == Decimal("0.00")
    assert Decimal(inv["tax_amount"]) == Decimal("0.00")
    assert Decimal(inv["total_amount"]) == Decimal("100.00")
    assert inv["tax_breakdown"]["tax_inclusive_pricing"] is True
    assert "statutory taxes" in inv["tax_breakdown"]["statutory_notice"].lower()

    pdf_res = client.get(f"/api/v1/invoices/{co['id']}/pdf", headers=student["headers"])
    assert pdf_res.status_code == 200
    assert pdf_res.content[:4] == b"%PDF"

    # Historical invoice with prior tax & discount stays completely intact
    hist_inv_num = f"INV-HIST-{uuid4().hex[:6].upper()}"
    with SessionLocal() as db:
        hist_inv = Invoice(
            invoice_number=hist_inv_num,
            invoice_type="order",
            canteen_id=UUID(main["id"]),
            reference_number=f"CB-HIST-{uuid4().hex[:6]}",
            customer_name="Historical Student",
            subtotal_amount=Decimal("200.00"),
            discount_amount=Decimal("20.00"),
            tax_amount=Decimal("9.00"),
            total_amount=Decimal("189.00"),
            tax_breakdown_json={"tax_label": "GST", "cgst_amount": "4.50", "sgst_amount": "4.50", "total_tax_amount": "9.00"},
            items_json=[{"item_name": "Historical Thali", "quantity": 2, "unit_price": "100.00", "tax_amount": "9.00", "line_total": "189.00"}],
            payment_method="razorpay",
            payment_reference="pay_hist_001",
            payment_status="CONFIRMED",
            issued_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
        db.add(hist_inv)
        db.commit()

    hist_get = client.get(f"/api/v1/invoices/{hist_inv_num}", headers=admin["headers"])
    assert hist_get.status_code == 200
    assert Decimal(hist_get.json()["discount_amount"]) == Decimal("20.00")
    assert Decimal(hist_get.json()["tax_amount"]) == Decimal("9.00")
    assert Decimal(hist_get.json()["total_amount"]) == Decimal("189.00")
    hist_pdf = client.get(f"/api/v1/invoices/{hist_inv_num}/pdf", headers=admin["headers"])
    assert hist_pdf.status_code == 200 and hist_pdf.content[:4] == b"%PDF"


def test_12_concurrent_checkout_requests_exact_and_idempotent(client: TestClient):
    """Scenario 12: Concurrent checkouts (same idempotency key -> 1 order; distinct keys -> exact independent totals)."""
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    main, _ = _get_counters(client)
    coffee = next(i for i in client.get(f"/api/v1/menus/canteens/{main['id']}/items").json() if "Coffee" in i["name"])

    shared_key = f"p34-idem-shared-{uuid4().hex}"

    def _checkout(idem: str, qty: int):
        return client.post(
            "/api/v1/orders/checkout",
            headers={**student["headers"], "X-Idempotency-Key": idem},
            json={
                "canteen_id": main["id"],
                "payment_method": "razorpay",
                "idempotency_key": idem,
                "use_cart": False,
                "direct_items": [{"food_item_id": coffee["id"], "quantity": qty}],
                "accepted_policy": True,
            },
        )

    # Same idempotency key sequentially/concurrently returns the single same order
    with ThreadPoolExecutor(max_workers=4) as ex:
        res_same = list(ex.map(lambda _: _checkout(shared_key, 2), range(4)))
    ok_ids = {r.json()["id"] for r in res_same if r.status_code in (200, 201)}
    assert len(ok_ids) == 1
    for r in res_same:
        if r.status_code in (200, 201):
            assert Decimal(r.json()["total_amount"]) == Decimal("100.00")
            assert Decimal(r.json()["tax_amount"]) == Decimal("0.00")

    # Distinct idempotency keys create independent exact orders
    distinct_keys = [f"p34-idem-dist-{i}-{uuid4().hex}" for i in range(3)]
    with ThreadPoolExecutor(max_workers=3) as ex:
        res_dist = list(ex.map(lambda k: _checkout(k, 1), distinct_keys))
    dist_ids = {r.json()["id"] for r in res_dist if r.status_code in (200, 201)}
    assert len(dist_ids) == 3
    for r in res_dist:
        assert r.status_code == 201
        assert Decimal(r.json()["total_amount"]) == Decimal("50.00")


# =============================================================================
# PART 2: TWO-COUNTER CAFETERIA STRUCTURE TESTS (13 SCENARIOS)
# =============================================================================


def test_13_to_17_two_counters_only_locations_and_juice_bar_removed(client: TestClient):
    """Scenarios 13-17: Exactly 2 counters (Main Canteen & Snacks & Bakery Counter), both at College Cafeteria, Fresh Juice & Shake Bar removed."""
    canteens = client.get("/api/v1/canteens").json()
    # Scenario 13: Exactly two active counters exist
    assert len(canteens) == 2

    # Also verify include_inactive=true does not leak retired counters
    all_canteens = client.get("/api/v1/canteens?include_inactive=true").json()
    assert len(all_canteens) == 2

    by_slug = {c["slug"]: c for c in canteens}
    # Scenario 14: Main Canteen appears correctly
    assert "main-canteen" in by_slug
    assert by_slug["main-canteen"]["name"] == "Main Canteen"
    assert by_slug["main-canteen"]["code"] == "MAIN"
    assert by_slug["main-canteen"]["token_prefix"] == "A"
    assert Decimal(by_slug["main-canteen"]["tax_rate_percent"]) == Decimal("0.00")

    # Scenario 15: Snacks & Bakery Counter appears correctly
    assert "snacks-bakery" in by_slug
    assert by_slug["snacks-bakery"]["name"] == "Snacks & Bakery Counter"
    assert by_slug["snacks-bakery"]["code"] == "SNK"
    assert by_slug["snacks-bakery"]["token_prefix"] == "S"
    assert Decimal(by_slug["snacks-bakery"]["tax_rate_percent"]) == Decimal("0.00")

    # Scenario 16: Both show College Cafeteria; none show removed locations
    disallowed_locations = {"Academic Block Ground Floor", "Central Courtyard", "Sports Complex Plaza"}
    for c in canteens:
        assert c["location"] == "College Cafeteria"
        assert c["location"] not in disallowed_locations

    # Scenario 17: Fresh Juice & Shake Bar completely absent everywhere
    for c in canteens:
        assert "juice" not in c["name"].lower()
        assert "shake" not in c["name"].lower()
        assert c["slug"] != "juice-bar"
    assert client.get("/api/v1/canteens/juice-bar").status_code == 404
    assert client.get("/api/v1/qr/resolve/CB-JUICE").status_code == 404


def test_18_to_22_independent_menus_orders_kds_queues_and_tokens(client: TestClient):
    """Scenarios 18-22: Both counters operate independently for menus, orders, KDS processing, queues, and pickup tokens."""
    student = login_as(client, "student@collegebites.edu", "Student@12345")
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    main, snacks = _get_counters(client)

    # Scenario 18: Independent menus
    main_items = client.get(f"/api/v1/menus/canteens/{main['id']}/items").json()
    snacks_items = client.get(f"/api/v1/menus/canteens/{snacks['id']}/items").json()
    assert len(main_items) >= 4
    assert len(snacks_items) >= 1
    assert {i["id"] for i in main_items}.isdisjoint({i["id"] for i in snacks_items})
    assert all(i["canteen_id"] == main["id"] for i in main_items)
    assert all(i["canteen_id"] == snacks["id"] for i in snacks_items)

    # Cross-counter cart add must fail
    cross_add = client.post(
        "/api/v1/carts/items",
        headers=student["headers"],
        json={"canteen_id": main["id"], "food_item_id": snacks_items[0]["id"], "quantity": 1},
    )
    assert cross_add.status_code in (400, 404)

    # Scenario 19: Independent order placement & payment confirmation
    m_item = main_items[0]
    s_item = snacks_items[0]
    co_m = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": main["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": m_item["id"], "quantity": 1}],
            "accepted_policy": True,
        },
    ).json()
    co_s = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": snacks["id"],
            "payment_method": "razorpay",
            "use_cart": False,
            "direct_items": [{"food_item_id": s_item["id"], "quantity": 2}],
            "accepted_policy": True,
        },
    ).json()
    assert Decimal(co_m["total_amount"]) == Decimal(m_item["base_price"])
    assert Decimal(co_s["total_amount"]) == Decimal(s_item["base_price"]) * 2

    pay_m = f"pay_m_{uuid4().hex[:8]}"
    pay_s = f"pay_s_{uuid4().hex[:8]}"
    conf_m = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": co_m["id"],
            "razorpay_order_id": co_m["razorpay_order_id"],
            "razorpay_payment_id": pay_m,
            "razorpay_signature": _rzp_sig(co_m["razorpay_order_id"], pay_m),
        },
    ).json()
    conf_s = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=student["headers"],
        json={
            "order_id": co_s["id"],
            "razorpay_order_id": co_s["razorpay_order_id"],
            "razorpay_payment_id": pay_s,
            "razorpay_signature": _rzp_sig(co_s["razorpay_order_id"], pay_s),
        },
    ).json()

    # Scenario 22: Pickup tokens generated for correct counter (A... vs S...)
    assert conf_m["pickup_token_code"].startswith("A")
    assert conf_s["pickup_token_code"].startswith("S")
    assert conf_m["canteen_id"] == main["id"]
    assert conf_s["canteen_id"] == snacks["id"]

    # Scenario 21: Independent queues
    q_m = client.get(f"/api/v1/queue/canteens/{main['id']}", headers=admin["headers"]).json()
    q_s = client.get(f"/api/v1/queue/canteens/{snacks['id']}", headers=admin["headers"]).json()
    q_m_ids = {o["order_id"] for o in q_m["active_orders_queue"]}
    q_s_ids = {o["order_id"] for o in q_s["active_orders_queue"]}
    assert co_m["id"] in q_m_ids and co_m["id"] not in q_s_ids
    assert co_s["id"] in q_s_ids and co_s["id"] not in q_m_ids

    # Scenario 20: Independent KDS processing
    for action in ("accept", "start-preparing", "mark-ready"):
        r = client.post(
            f"/api/v1/kitchen/orders/{co_m['id']}/{action}",
            headers=admin["headers"],
        )
        assert r.status_code == 200, r.text

    # Snacks order remains untouched at PLACED while Main Canteen order is READY
    ord_m_now = client.get(f"/api/v1/orders/{co_m['order_number']}", headers=student["headers"]).json()
    ord_s_now = client.get(f"/api/v1/orders/{co_s['order_number']}", headers=student["headers"]).json()
    assert ord_m_now["status"] == "READY"
    assert ord_s_now["status"] == "PLACED"

    # Staff pickup board filters cleanly by counter
    board_m = client.get(f"/api/v1/pickup/board?canteen_id={main['id']}", headers=admin["headers"]).json()
    board_s = client.get(f"/api/v1/pickup/board?canteen_id={snacks['id']}", headers=admin["headers"]).json()
    assert any(x["token_code"] == conf_m["pickup_token_code"] for x in board_m["ready_for_pickup"])
    assert not any(x["token_code"] == conf_s["pickup_token_code"] for x in board_m["ready_for_pickup"] + board_m["now_preparing"])
    assert any(x["token_code"] == conf_s["pickup_token_code"] for x in board_s["now_preparing"])


def test_23_inventory_functional_for_both_counters(client: TestClient):
    """Scenario 23: Inventory management remains functional for both Main Canteen and Snacks & Bakery Counter."""
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    main, snacks = _get_counters(client)

    dash_m = client.get(f"/api/v1/inventory/canteens/{main['id']}/dashboard", headers=admin["headers"])
    assert dash_m.status_code == 200
    assert dash_m.json()["total_inventory_items"] >= 4

    # Add an inventory ingredient specifically for Snacks & Bakery Counter
    add_snk = client.post(
        "/api/v1/inventory/ingredients",
        headers=admin["headers"],
        json={
            "canteen_id": snacks["id"],
            "name": "Puff Pastry Sheets",
            "sku": f"SNK-PUFF-{uuid4().hex[:5].upper()}",
            "category": "Bakery",
            "unit": "packs",
            "initial_quantity": "50.000",
            "reorder_level": "10.000",
            "unit_cost": "45.00",
        },
    )
    assert add_snk.status_code == 201, add_snk.text
    dash_s = client.get(f"/api/v1/inventory/canteens/{snacks['id']}/dashboard", headers=admin["headers"])
    assert dash_s.status_code == 200
    assert dash_s.json()["total_inventory_items"] >= 1


def test_24_admin_sees_both_counters_and_manager_strictly_scoped(client: TestClient):
    """Scenario 24: Admin sees and manages both counters; counter manager is strictly scoped to assigned counter."""
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    mgr = login_as(client, "manager@collegebites.edu", "Staff@12345")
    main, snacks = _get_counters(client)

    # Admin accesses both counters
    assert client.get(f"/api/v1/queue/canteens/{main['id']}", headers=admin["headers"]).status_code == 200
    assert client.get(f"/api/v1/queue/canteens/{snacks['id']}", headers=admin["headers"]).status_code == 200

    # Main Canteen manager accesses Main Canteen, rejected on Snacks & Bakery Counter
    assert client.get(f"/api/v1/queue/canteens/{main['id']}", headers=mgr["headers"]).status_code == 200
    assert (
        client.patch(
            f"/api/v1/admin/canteens/{snacks['id']}",
            headers=mgr["headers"],
            json={"pause_reason": "Unauthorized attempt"},
        ).status_code
        == 403
    )
    snacks_cat_id = client.get(f"/api/v1/menus/canteens/{snacks['id']}/categories").json()[0]["id"]
    assert (
        client.post(
            "/api/v1/menus/items",
            headers=mgr["headers"],
            json={
                "canteen_id": snacks["id"],
                "category_id": snacks_cat_id,
                "name": "Unauthorized Snack",
                "slug": f"unauth-{uuid4().hex[:6]}",
                "base_price": "25.00",
            },
        ).status_code
        == 403
    )


def test_25_third_counter_blocked_and_migration_safely_cleans_legacy_db(client: TestClient, tmp_path: Path):
    """Scenario 25: Creating a 3rd counter via API is blocked, and Alembic migration cleans legacy DBs safely with or without historical orders."""
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")

    # 1. API blocks creating ANY third counter (generic or Fresh Juice & Shake Bar)
    r_generic = client.post(
        "/api/v1/admin/canteens",
        headers=admin["headers"],
        json={
            "name": "Third Cafeteria Counter",
            "slug": "third-counter",
            "code": "TRD",
            "location": "College Cafeteria",
            "token_prefix": "T",
            "tax_rate_percent": "0.00",
        },
    )
    assert r_generic.status_code == 400, r_generic.text

    r_juice = client.post(
        "/api/v1/admin/canteens",
        headers=admin["headers"],
        json={
            "name": "Fresh Juice & Shake Bar",
            "slug": "juice-bar",
            "code": "JUC",
            "location": "Sports Complex Plaza",
            "token_prefix": "J",
            "tax_rate_percent": "0.00",
        },
    )
    assert r_juice.status_code == 400, r_juice.text
    assert len(client.get("/api/v1/canteens").json()) == 2

    # 2. Verify Alembic migration d4e5f6a7b8c9 on simulated pre-migration DB (Case A: zero orders -> full delete; Case B: historical order -> safe deactivation & FK preserved)
    mig_path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "d4e5f6a7b8c9_pricing_cleanup_and_two_counters.py"
    spec = importlib.util.spec_from_file_location("mig_p34", str(mig_path))
    assert spec and spec.loader
    mig_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig_mod)

    for case_name, with_hist_order in (("zero_history", False), ("with_history", True)):
        db_file = tmp_path / f"mig_{case_name}.db"
        eng = create_engine(f"sqlite:///{db_file}")
        Base.metadata.create_all(bind=eng)
        with eng.begin() as conn:
            main_id = uuid4().hex
            snk_id = uuid4().hex
            juc_id = uuid4().hex
            cnt_juc_id = uuid4().hex
            conn.execute(
                text(
                    "INSERT INTO college_settings (id, college_name, college_short_code, default_tax_rate_percent, currency_code, currency_symbol, "
                    "cancellation_policy_text, kiosk_enabled, razorpay_enabled, cash_at_counter_enabled, pay_at_pickup_enabled, college_timezone, created_at, updated_at) "
                    "VALUES (:id, 'ACE', 'ACE', 5.00, 'INR', 'Rs', 'Policy', 0, 1, 0, 0, 'Asia/Kolkata', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": uuid4().hex},
            )
            for cid, name, slug, code, loc in (
                (main_id, "Main Canteen", "main-canteen", "MAIN", "Academic Block Ground Floor"),
                (snk_id, "Snacks & Bakery Counter", "snacks-bakery", "SNK", "Central Courtyard"),
                (juc_id, "Fresh Juice & Shake Bar", "juice-bar", "JUC", "Sports Complex Plaza"),
            ):
                conn.execute(
                    text(
                        "INSERT INTO canteens (id, name, slug, code, token_prefix, location, canteen_type, is_active, is_temporarily_closed, ordering_paused, "
                        "tax_rate_percent, allow_online_payment, allow_cash_at_counter, allow_pay_at_pickup, max_concurrent_orders, orders_per_slot_capacity, "
                        "default_prep_time_minutes, peak_hour_buffer_minutes, crowd_moderate_threshold, crowd_high_threshold, crowd_very_high_threshold, auto_throttle_enabled, created_at, updated_at) "
                        "VALUES (:id, :name, :slug, :code, 'X', :loc, 'canteen', 1, 0, 0, 5.00, 1, 0, 0, 50, 30, 10, 5, 15, 30, 45, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"id": cid, "name": name, "slug": slug, "code": code, "loc": loc},
                )
            conn.execute(
                text(
                    "INSERT INTO counters (id, canteen_id, name, code, counter_type, is_active, max_queue_capacity, created_at, updated_at) "
                    "VALUES (:id, :cid, 'Juice Counter', 'J1', 'both', 1, 25, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": cnt_juc_id, "cid": juc_id},
            )
            conn.execute(
                text(
                    "INSERT INTO coupons (id, code, title, discount_type, discount_value, min_order_amount, first_order_only, usage_limit_per_user, times_used, is_active, created_at, updated_at) "
                    "VALUES (:id, 'CAMPUS15', 'Old Promo', 'percentage', 15.00, 100.00, 0, 1, 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": uuid4().hex},
            )
            if with_hist_order:
                conn.execute(
                    text(
                        "INSERT INTO orders (id, order_number, canteen_id, counter_id, is_guest, order_type, order_channel, status, payment_status, payment_method, "
                        "subtotal_amount, discount_amount, tax_amount, total_amount, estimated_prep_minutes, delayed_minutes, is_priority, inventory_deducted, created_at, updated_at) "
                        "VALUES (:id, 'CB-HIST-JUC-1', :cid, :cnt_id, 1, 'pickup', 'web', 'COMPLETED', 'CONFIRMED', 'razorpay', 65.00, 0.00, 3.25, 68.25, 5, 0, 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {"id": uuid4().hex, "cid": juc_id, "cnt_id": cnt_juc_id},
                )

            # Monkeypatch alembic.op.get_bind for isolated migration verification
            orig_get_bind = mig_mod.op.get_bind
            mig_mod.op.get_bind = lambda: conn
            try:
                mig_mod.upgrade()
            finally:
                mig_mod.op.get_bind = orig_get_bind

            # Assertions after migration upgrade()
            assert conn.execute(text("SELECT default_tax_rate_percent FROM college_settings")).scalar() == Decimal("0.00")
            assert conn.execute(text("SELECT COUNT(*) FROM coupons WHERE is_active = 1")).scalar() == 0
            assert conn.execute(text("SELECT COUNT(*) FROM coupons")).scalar() == 1  # Historical coupon preserved

            active_canteens = conn.execute(
                text("SELECT slug, location, tax_rate_percent FROM canteens WHERE is_active = 1 ORDER BY slug")
            ).fetchall()
            assert len(active_canteens) == 2
            assert [r[0] for r in active_canteens] == ["main-canteen", "snacks-bakery"]
            assert all(r[1] == "College Cafeteria" for r in active_canteens)
            assert all(Decimal(str(r[2])) == Decimal("0.00") for r in active_canteens)

            if with_hist_order:
                # Historical order preserved intact and juice-bar cleanly deactivated
                assert conn.execute(text("SELECT COUNT(*) FROM orders WHERE order_number = 'CB-HIST-JUC-1'")).scalar() == 1
                juc_active = conn.execute(text("SELECT is_active FROM canteens WHERE slug = 'juice-bar'")).scalar()
                assert not bool(juc_active)
            else:
                # Zero history -> juice-bar row completely deleted
                assert conn.execute(text("SELECT COUNT(*) FROM canteens WHERE slug = 'juice-bar'")).scalar() == 0
        eng.dispose()
