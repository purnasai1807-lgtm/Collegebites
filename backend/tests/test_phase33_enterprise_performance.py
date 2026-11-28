"""
Phase 33 Enterprise Performance, Caching, Pooling & Ordering Reliability Regression Tests.
Verifies:
- N+1 query elimination across all 5 target endpoints + /admin/users
- Two-tier Redis cache hit & mutation invalidation (menu, board, queue, reports, auth)
- Graceful fallback when Redis is unreachable
- Order checkout idempotency & duplicate webhook deduplication
- /health/ready pool & cache observability
"""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
from unittest.mock import patch

import redis
from sqlalchemy import event, select

from app.core.cache import cache_manager
from app.core.config import settings
from app.models.college import Canteen, Counter
from app.models.menu import FoodItem
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PickupToken


def _count_sql_queries(db_session, fn):
    queries: list[str] = []
    bind_engine = db_session.get_bind()

    def _before_exec(_conn, _cursor, statement, _params, _ctx, _executemany):
        queries.append(statement)

    event.listen(bind_engine, "before_cursor_execute", _before_exec)
    try:
        res = fn()
    finally:
        event.remove(bind_engine, "before_cursor_execute", _before_exec)
    return res, len(queries)


def _login(client, email: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"identifier": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _seed_25_orders(db, canteen, counter, food, customer_id):
    from app.core.time_utils import today_college

    today_d = today_college()
    statuses = ["PLACED", "ACCEPTED", "PREPARING", "READY", "COMPLETED"]
    for i in range(1, 26):
        st = statuses[i % len(statuses)]
        ord_row = Order(
            order_number=f"CB-P33-{i:04d}",
            canteen_id=canteen.id,
            counter_id=counter.id,
            customer_id=customer_id,
            is_guest=False,
            order_type="pickup",
            order_channel="web",
            status=st,
            payment_status="CONFIRMED",
            payment_method="razorpay",
            subtotal_amount=Decimal("100.00"),
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("5.00"),
            total_amount=Decimal("105.00"),
            confirmed_at=datetime.now(timezone.utc),
            ready_at=datetime.now(timezone.utc) if st in ("READY", "COMPLETED") else None,
            completed_at=datetime.now(timezone.utc) if st == "COMPLETED" else None,
        )
        db.add(ord_row)
        db.flush()
        db.add(
            OrderItem(
                order_id=ord_row.id,
                food_item_id=food.id,
                item_name=food.name,
                quantity=1,
                unit_price=Decimal("100.00"),
                line_subtotal=Decimal("100.00"),
                tax_amount=Decimal("5.00"),
                line_total=Decimal("105.00"),
            )
        )
        db.add(
            PickupToken(
                order_id=ord_row.id,
                canteen_id=canteen.id,
                counter_id=counter.id,
                service_date=today_d,
                sequence_number=i,
                token_code=f"P{i:03d}",
                status="HANDED_OVER" if st == "COMPLETED" else "ACTIVE",
            )
        )
        db.add(
            Payment(
                order_id=ord_row.id,
                provider="razorpay",
                method="razorpay",
                amount=Decimal("105.00"),
                currency="INR",
                status="CONFIRMED",
                provider_order_id=f"order_p33_{i:04d}",
                provider_payment_id=f"pay_p33_{i:04d}",
            )
        )
    db.commit()


def test_optimized_target_endpoints_sql_counts_and_caching(client, clean_db_and_seed):
    db_session = clean_db_and_seed
    admin_tok = _login(client, "admin@collegebites.edu", "Admin@12345")
    student_tok = _login(client, "student@collegebites.edu", "Student@12345")
    admin_hdr = {"Authorization": f"Bearer {admin_tok}"}
    student_hdr = {"Authorization": f"Bearer {student_tok}"}

    canteen = db_session.scalar(select(Canteen).where(Canteen.is_active.is_(True)))
    counter = db_session.scalar(select(Counter).where(Counter.canteen_id == canteen.id))
    food = db_session.scalar(select(FoodItem).where(FoodItem.canteen_id == canteen.id))
    me_resp = client.get("/api/v1/auth/me", headers=student_hdr)
    assert me_resp.status_code == 200
    student_id = me_resp.json()["id"]

    from uuid import UUID

    _seed_25_orders(db_session, canteen, counter, food, UUID(student_id))
    cache_manager.reset_all()

    # Warm auth cache once
    assert client.get("/api/v1/auth/me", headers=admin_hdr).status_code == 200
    assert client.get("/api/v1/auth/me", headers=student_hdr).status_code == 200

    # 1. GET /api/v1/admin/orders (was 235 queries; must be <= 15 queries with 25 orders)
    r_adm, q_adm = _count_sql_queries(db_session, lambda: client.get("/api/v1/admin/orders?limit=50", headers=admin_hdr))
    assert r_adm.status_code == 200
    assert len(r_adm.json()) == 25
    assert q_adm <= 15, f"Expected <= 15 SQL queries for 25 admin orders, got {q_adm}"

    # 2. GET /api/v1/orders/my (was 21 queries; must be <= 14 queries)
    r_my, q_my = _count_sql_queries(db_session, lambda: client.get("/api/v1/orders/my?limit=50", headers=student_hdr))
    assert r_my.status_code == 200
    assert len(r_my.json()) == 25
    assert q_my <= 14, f"Expected <= 14 SQL queries for /orders/my, got {q_my}"

    # 3. GET /api/v1/reports/dashboard (was 42 queries; miss <= 28, warm cache <= 2)
    r_rep1, q_rep1 = _count_sql_queries(
        db_session,
        lambda: client.get("/api/v1/reports/dashboard?preset=last_30_days", headers=admin_hdr),
    )
    assert r_rep1.status_code == 200
    assert r_rep1.json()["sales"]["total_orders"] == 25
    assert q_rep1 <= 28, f"Expected <= 28 SQL queries on cold /reports/dashboard, got {q_rep1}"

    r_rep2, q_rep2 = _count_sql_queries(
        db_session,
        lambda: client.get("/api/v1/reports/dashboard?preset=last_30_days", headers=admin_hdr),
    )
    assert r_rep2.status_code == 200
    assert q_rep2 <= 2, f"Expected <= 2 SQL queries on cached /reports/dashboard, got {q_rep2}"

    # 4. GET /api/v1/menus/canteens/{id}/items (cold <= 10, warm == 0)
    r_m1, q_m1 = _count_sql_queries(db_session, lambda: client.get(f"/api/v1/menus/canteens/{canteen.id}/items"))
    assert r_m1.status_code == 200
    assert len(r_m1.json()) > 0
    assert q_m1 <= 10, f"Expected <= 10 SQL queries on cold menu items, got {q_m1}"

    r_m2, q_m2 = _count_sql_queries(db_session, lambda: client.get(f"/api/v1/menus/canteens/{canteen.id}/items"))
    assert r_m2.status_code == 200
    assert q_m2 == 0, f"Expected 0 SQL queries on cached menu items, got {q_m2}"

    # Verify menu cache invalidates immediately on PATCH
    orig_price = Decimal(str(food.base_price))
    new_price = orig_price + Decimal("5.00")
    r_upd = client.patch(
        f"/api/v1/menus/items/{food.id}",
        headers=admin_hdr,
        json={"base_price": str(new_price)},
    )
    assert r_upd.status_code == 200
    r_m3 = client.get(f"/api/v1/menus/canteens/{canteen.id}/items")
    matched = next(x for x in r_m3.json() if x["id"] == str(food.id))
    assert Decimal(str(matched["base_price"])) == new_price

    # 5. GET /api/v1/queue/canteens/{id} (was 25 queries; cold <= 15, warm == 0)
    r_q1, q_q1 = _count_sql_queries(db_session, lambda: client.get(f"/api/v1/queue/canteens/{canteen.id}"))
    assert r_q1.status_code == 200
    assert q_q1 <= 15, f"Expected <= 15 SQL queries on cold queue dashboard, got {q_q1}"

    r_q2, q_q2 = _count_sql_queries(db_session, lambda: client.get(f"/api/v1/queue/canteens/{canteen.id}"))
    assert r_q2.status_code == 200
    assert q_q2 == 0, f"Expected 0 SQL queries on cached queue dashboard, got {q_q2}"

    # 6. GET /api/v1/admin/users batched RBAC (must be <= 8 queries regardless of user count)
    r_u, q_u = _count_sql_queries(db_session, lambda: client.get("/api/v1/admin/users", headers=admin_hdr))
    assert r_u.status_code == 200
    assert len(r_u.json()) >= 4
    assert q_u <= 8, f"Expected <= 8 SQL queries for /admin/users, got {q_u}"


def test_redis_unavailable_graceful_fallback_and_health_ready(client, clean_db_and_seed):
    # Even when Redis raises ConnectionError on every operation, public and health APIs must stay 200 OK
    class _BrokenRedis:
        def get(self, *_a, **_kw):
            raise redis.exceptions.ConnectionError("Simulated Redis outage")

        def setex(self, *_a, **_kw):
            raise redis.exceptions.ConnectionError("Simulated Redis outage")

        def incr(self, *_a, **_kw):
            raise redis.exceptions.ConnectionError("Simulated Redis outage")

        def ping(self):
            raise redis.exceptions.ConnectionError("Simulated Redis outage")

    cache_manager.reset_all()
    with patch("app.core.cache.get_redis", return_value=_BrokenRedis()), patch(
        "app.main.get_redis", return_value=_BrokenRedis()
    ):
        r_c = client.get("/api/v1/canteens")
        assert r_c.status_code == 200
        assert len(r_c.json()) >= 1
        admin_tok = _login(client, "admin@collegebites.edu", "Admin@12345")
        r_b = client.get("/api/v1/pickup/board", headers={"Authorization": f"Bearer {admin_tok}"})
        assert r_b.status_code == 200
        r_h = client.get("/health/ready")
        assert r_h.status_code == 200
        body = r_h.json()
        assert body["database"] == "connected"
        assert body["redis"] == "fallback"
        assert "db_pool" in body and "cache" in body


def test_order_idempotency_and_webhook_deduplication(client, clean_db_and_seed):
    db_session = clean_db_and_seed
    student_tok = _login(client, "student@collegebites.edu", "Student@12345")
    hdr = {"Authorization": f"Bearer {student_tok}"}
    canteen = db_session.scalar(select(Canteen).where(Canteen.is_active.is_(True)))
    food = db_session.scalar(select(FoodItem).where(FoodItem.canteen_id == canteen.id, FoodItem.is_available.is_(True)))

    idem_key = "idem-phase33-unique-order-001"
    payload = {
        "canteen_id": str(canteen.id),
        "order_type": "pickup",
        "order_channel": "web",
        "payment_method": "razorpay",
        "accepted_policy": True,
        "use_cart": False,
        "idempotency_key": idem_key,
        "direct_items": [{"food_item_id": str(food.id), "quantity": 1}],
    }

    r1 = client.post("/api/v1/orders/checkout", json=payload, headers=hdr)
    assert r1.status_code == 201, r1.text
    r2 = client.post("/api/v1/orders/checkout", json=payload, headers=hdr)
    assert r2.status_code == 201, r2.text
    assert r1.json()["id"] == r2.json()["id"]
    assert r1.json()["order_number"] == r2.json()["order_number"]

    # Confirm Razorpay payment twice (idempotent verification) and ensure only 1 token exists
    from app.integrations.razorpay_client import razorpay_gateway

    order_id = r1.json()["id"]
    rzp_oid = r1.json()["razorpay_order_id"]
    rzp_pid = "pay_p33_verify_001"
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=rzp_oid,
        razorpay_payment_id=rzp_pid,
    )

    v1 = client.post(
        "/api/v1/payments/razorpay/verify",
        json={
            "order_id": order_id,
            "razorpay_order_id": rzp_oid,
            "razorpay_payment_id": rzp_pid,
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
        headers=hdr,
    )
    assert v1.status_code == 200, v1.text
    v2 = client.post(
        "/api/v1/payments/razorpay/verify",
        json={
            "order_id": order_id,
            "razorpay_order_id": rzp_oid,
            "razorpay_payment_id": rzp_pid,
            "razorpay_signature": sig,
            "payment_method": "upi",
        },
        headers=hdr,
    )
    assert v2.status_code == 200, v2.text
    assert v1.json()["pickup_token_code"] == v2.json()["pickup_token_code"]
    assert v1.json()["pickup_token_code"] is not None

    # Duplicate webhook delivery must be safely deduplicated
    wh_body = json.dumps(
        {
            "event": "payment.captured",
            "event_id": "evt_p33_dedupe_001",
            "payload": {
                "payment": {
                    "entity": {
                        "id": rzp_pid,
                        "order_id": rzp_oid,
                        "amount": int(Decimal(str(r1.json()["total_amount"])) * 100),
                        "currency": "INR",
                        "method": "upi",
                    }
                }
            },
        }
    ).encode("utf-8")
    wh_sig = razorpay_gateway.compute_test_webhook_signature(raw_body=wh_body)
    w1 = client.post("/api/v1/payments/razorpay/webhook", content=wh_body, headers={"X-Razorpay-Signature": wh_sig})
    assert w1.status_code == 200, w1.text
    w2 = client.post("/api/v1/payments/razorpay/webhook", content=wh_body, headers={"X-Razorpay-Signature": wh_sig})
    assert w2.status_code == 200, w2.text
    assert w2.json()["status"] == "already_processed"
