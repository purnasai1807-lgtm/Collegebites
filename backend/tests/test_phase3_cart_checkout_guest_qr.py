from decimal import Decimal
from fastapi.testclient import TestClient

from tests.conftest import login_as


def test_qr_location_resolve_revoke_and_replace(client: TestClient):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    resolved = client.get("/api/v1/qr/locations/resolve/CB-MAIN-T01")
    assert resolved.status_code == 200
    data = resolved.json()
    assert data["canteen"]["slug"] == "main-canteen"
    assert data["table"]["table_number"] == "T-01"
    qr_id = data["qr"]["id"]

    # Replace QR -> old code becomes 410 Gone, new code works
    rep = client.post(f"/api/v1/qr/locations/{qr_id}/replace", headers=admin["headers"])
    assert rep.status_code == 200
    new_code = rep.json()["code"]
    assert new_code != "CB-MAIN-T01"

    old_res = client.get("/api/v1/qr/locations/resolve/CB-MAIN-T01")
    assert old_res.status_code == 410

    new_res = client.get(f"/api/v1/qr/locations/resolve/{new_code}")
    assert new_res.status_code == 200

    # Revoke new QR
    rev = client.post(f"/api/v1/qr/locations/{rep.json()['id']}/revoke", headers=admin["headers"])
    assert rev.status_code == 200
    assert client.get(f"/api/v1/qr/locations/resolve/{new_code}").status_code == 410


def test_cart_backend_pricing_no_coupons_and_guest_checkout_idempotency(client: TestClient):
    main = next(c for c in client.get("/api/v1/canteens").json() if c["slug"] == "main-canteen")
    cid = main["id"]
    items = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    biryani = next(i for i in items if "Biryani" in i["name"])
    coffee = next(i for i in items if "Coffee" in i["name"])
    jumbo_var = next(v for v in biryani["variants"] if v["name"] == "Jumbo Pack")
    raita_addon = next(a for a in biryani["addons"] if "Raita" in a["name"])

    guest_headers = {"X-Guest-Session-ID": "guest-sess-001"}

    # Add Biryani (80 + 60 = 140) + Raita (20) = 160 * 1 = 160
    r1 = client.post(
        "/api/v1/carts/items",
        headers=guest_headers,
        json={
            "canteen_id": cid,
            "food_item_id": biryani["id"],
            "variant_id": jumbo_var["id"],
            "quantity": 1,
            "spice_level": "Extra Spicy",
            "addons": [{"addon_id": raita_addon["id"], "quantity": 1}],
            "special_instructions": "Less oil",
        },
    )
    assert r1.status_code == 200, r1.text

    # Add 2 Cold Coffee (50 * 2 = 100) -> Subtotal = 260, Discount = 0, Additional Tax = 0 -> Total = 260.00
    r2 = client.post(
        "/api/v1/carts/items",
        headers=guest_headers,
        json={
            "canteen_id": cid,
            "food_item_id": coffee["id"],
            "quantity": 2,
            "sugar_level": "Less Sugar",
        },
    )
    assert r2.status_code == 200
    assert Decimal(r2.json()["subtotal_amount"]) == Decimal("260.00")
    assert Decimal(r2.json()["discount_amount"]) == Decimal("0.00")
    assert Decimal(r2.json()["tax_amount"]) == Decimal("0.00")
    assert Decimal(r2.json()["total_amount"]) == Decimal("260.00")

    # Invalid/non-existent coupon code is rejected on backend
    rc = client.post("/api/v1/carts/coupon", headers=guest_headers, json={"canteen_id": cid, "coupon_code": "CAMPUS10"})
    assert rc.status_code in (400, 404, 405)

    # Direct guest checkout without OTP (OTP verification permanently removed)
    co = client.post(
        "/api/v1/orders/checkout",
        headers=guest_headers,
        json={
            "canteen_id": cid,
            "guest_name": "Guest Tester",
            "guest_phone": "+919900112233",
            "payment_method": "razorpay",
            "idempotency_key": "idem-guest-1",
            "location_qr_code": "CB-MAIN-CANTEEN",
            "order_channel": "qr",
            "accepted_policy": True,
        },
    )
    assert co.status_code == 201, co.text
    order = co.json()
    assert order["status"] == "PAYMENT_PENDING"
    assert order["payment_status"] == "PENDING"
    assert order["pickup_token_code"] is None  # NO token before verified payment!
    assert order["qr_token_raw"] is None
    assert Decimal(order["total_amount"]) == Decimal("260.00")
    assert order["coupon_code"] is None
    assert order["razorpay_order_id"] is not None
    guest_token = order["guest_access_token"]
    assert guest_token is not None

    # Duplicate checkout with same idempotency_key returns existing order without duplicating
    co_dup = client.post(
        "/api/v1/orders/checkout",
        headers=guest_headers,
        json={
            "canteen_id": cid,
            "guest_name": "Guest Tester",
            "guest_phone": "+919900112233",
            "payment_method": "razorpay",
            "idempotency_key": "idem-guest-1",
            "accepted_policy": True,
        },
    )
    assert co_dup.status_code == 201
    assert co_dup.json()["id"] == order["id"]

    # Unauthorized viewer cannot read guest order without guest_token
    assert client.get(f"/api/v1/orders/{order['order_number']}").status_code == 401
    assert client.get(f"/api/v1/orders/{order['order_number']}?guest_token={guest_token}").status_code == 200
