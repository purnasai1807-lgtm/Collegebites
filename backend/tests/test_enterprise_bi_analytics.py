from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time_utils import today_college
from app.integrations.razorpay_client import razorpay_gateway
from app.models.menu import FoodItem
from app.models.order import Order
from tests.conftest import login_as


def _create_paid_razorpay_order(
    client: TestClient,
    headers: dict,
    canteen_id: str,
    direct_items: list[dict],
    idem_key: str,
    pay_id: str,
    payment_method: str = "upi",
) -> dict:
    chk = client.post(
        "/api/v1/orders/checkout",
        headers=headers,
        json={
            "canteen_id": canteen_id,
            "payment_method": "razorpay",
            "idempotency_key": idem_key,
            "use_cart": False,
            "accepted_policy": True,
            "direct_items": direct_items,
        },
    )
    assert chk.status_code == 201, chk.text
    order = chk.json()
    sig = razorpay_gateway.compute_test_payment_signature(
        razorpay_order_id=order["razorpay_order_id"],
        razorpay_payment_id=pay_id,
    )
    ver = client.post(
        "/api/v1/payments/razorpay/verify",
        headers=headers,
        json={
            "order_id": order["id"],
            "razorpay_order_id": order["razorpay_order_id"],
            "razorpay_payment_id": pay_id,
            "razorpay_signature": sig,
            "payment_method": payment_method,
        },
    )
    assert ver.status_code == 200, ver.text
    return ver.json()


def test_enterprise_bi_all_seven_sections_filters_drilldowns_and_cache_invalidation(
    client: TestClient,
    clean_db_and_seed: Session,
):
    admin = login_as(client, "admin@collegebites.edu", "Admin@12345")
    manager = login_as(client, "manager@collegebites.edu", "Staff@12345")
    kitchen = login_as(client, "kitchen@collegebites.edu", "Staff@12345")
    pickup = login_as(client, "pickup@collegebites.edu", "Staff@12345")
    student = login_as(client, "student@collegebites.edu", "Student@12345")

    canteens = client.get("/api/v1/canteens").json()
    main_canteen = next(c for c in canteens if c["slug"] == "main-canteen")
    other_canteen = next(c for c in canteens if c["id"] != main_canteen["id"])
    cid = main_canteen["id"]
    detail = client.get(f"/api/v1/canteens/{cid}").json()
    counter = next(c for c in detail["counters"] if c["counter_type"] in ("pickup", "both"))

    menu = client.get(f"/api/v1/menus/canteens/{cid}/items").json()
    biryani = next(i for i in menu if "Biryani" in i["name"])
    coffee = next(i for i in menu if "Coffee" in i["name"])
    extra_item = next(i for i in menu if i["id"] not in (biryani["id"], coffee["id"]))

    # Mark one extra item out of stock to verify Section 6 out-of-stock analytics
    food_row = clean_db_and_seed.get(FoodItem, UUID(extra_item["id"]))
    assert food_row is not None
    food_row.is_available = False
    clean_db_and_seed.commit()

    # 1. Create and verify a paid combo order (Biryani x2 + Coffee x1) and complete lifecycle
    paid_order = _create_paid_razorpay_order(
        client,
        student["headers"],
        cid,
        [
            {"food_item_id": biryani["id"], "quantity": 2},
            {"food_item_id": coffee["id"], "quantity": 1},
        ],
        idem_key="bi-paid-combo-1",
        pay_id="pay_bi_combo_001",
    )
    assert client.post(f"/api/v1/kitchen/orders/{paid_order['id']}/accept", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{paid_order['id']}/start-preparing", headers=kitchen["headers"]).status_code == 200
    assert client.post(f"/api/v1/kitchen/orders/{paid_order['id']}/mark-ready", headers=kitchen["headers"]).status_code == 200
    assert (
        client.post(
            "/api/v1/pickup/handover",
            headers=pickup["headers"],
            json={"order_id": paid_order["id"], "counter_id": paid_order.get("counter_id") or counter["id"], "verification_method": "qr_scan"},
        ).status_code
        == 200
    )

    # Mark order delayed for Section 3 / 6 delayed order detection
    db_order = clean_db_and_seed.scalar(select(Order).where(Order.id == UUID(paid_order["id"])))
    assert db_order is not None
    db_order.delayed_minutes = 12
    clean_db_and_seed.commit()

    # 2. Create an unpaid pending order (must NOT count toward verified net revenue!)
    unpaid_chk = client.post(
        "/api/v1/orders/checkout",
        headers=student["headers"],
        json={
            "canteen_id": cid,
            "payment_method": "razorpay",
            "idempotency_key": "bi-unpaid-pending-1",
            "use_cart": False,
            "accepted_policy": True,
            "direct_items": [{"food_item_id": coffee["id"], "quantity": 5}],
        },
    )
    assert unpaid_chk.status_code == 201
    unpaid_order = unpaid_chk.json()

    # Cancel the unpaid checkout order to verify cancellation rate accounting
    cancel_res = client.post(
        f"/api/v1/orders/{unpaid_order['id']}/cancel",
        headers=student["headers"],
        json={"reason": "Changed mind before payment"},
    )
    assert cancel_res.status_code == 200

    # 3. Post verified food review for Section 5 customer satisfaction metrics
    rev_res = client.post(
        "/api/v1/support/reviews",
        headers=student["headers"],
        json={
            "food_item_id": biryani["id"],
            "order_id": paid_order["id"],
            "rating": 5,
            "comment": "Hot and well packed",
        },
    )
    assert rev_res.status_code == 201, rev_res.text

    # 4. Pull full Enterprise BI report (compare_previous=true, today)
    rep_res = client.get(
        f"/api/v1/reports/dashboard?canteen_id={cid}&preset=today&compare_previous=true",
        headers=admin["headers"],
    )
    assert rep_res.status_code == 200, rep_res.text
    bi = rep_res.json()

    # Metadata & Metric Definitions
    assert bi["generated_at"]
    assert bi["timezone"] == "Asia/Kolkata"
    assert "SQL aggregation" in bi["data_source"]
    assert isinstance(bi["metric_definitions"], dict)
    assert "net_revenue" in bi["metric_definitions"]
    assert "cancellation_rate_percent" in bi["metric_definitions"]

    # Section 1: Executive Overview
    expected_paid_rev = Decimal(str(paid_order["total_amount"])).quantize(Decimal("0.01"))
    assert Decimal(bi["today_summary"]["revenue_today"]) == expected_paid_rev
    assert bi["sales"]["total_orders"] == 1  # Only verified paid order
    assert bi["sales"]["total_created_orders"] == 2
    assert bi["operations"]["completed_orders"] == 1
    assert bi["operations"]["cancelled_orders"] == 1
    assert bi["operations"]["cancellation_rate_percent"] == 50.0
    assert Decimal(bi["sales"]["net_sales"]) == expected_paid_rev

    # Section 2: Revenue Intelligence & Financial Truth
    fin = bi["financial_analytics"]
    assert Decimal(fin["refunds_amount"]) == Decimal("0.00")
    assert fin["no_refund_policy_enforced"] is True
    assert Decimal(fin["collected_payments"]) == expected_paid_rev
    assert len(bi["sales"]["weekly_series"]) >= 1
    assert len(bi["sales"]["monthly_series"]) >= 1
    assert len(bi["sales"]["hourly_series"]) == 24
    assert any(p["method"] == "upi" for p in bi["sales"]["payment_breakdown"])

    # Section 3: Order Intelligence & Peak-Hour Heatmap
    assert len(bi["sales"]["weekday_series"]) == 7
    assert len(bi["sales"]["hourly_heatmap"]) == 7 * 16
    assert {c["hour"] for c in bi["sales"]["hourly_heatmap"]} == set(range(7, 23))
    assert bi["operations"]["delayed_orders"] == 1
    assert bi["operations"]["completion_rate_percent"] == 100.0
    assert "avg_fulfilment_minutes" in bi["operations"]

    # Section 4: Product Intelligence, All Products Sales & Frequently Purchased Combinations
    top_names = [it["item_name"] for it in bi["sales"]["top_items"]]
    assert biryani["name"] in top_names
    assert coffee["name"] in top_names
    all_prods = bi["sales"]["all_products_performance"]
    assert len(all_prods) >= len(menu)
    assert bi["sales"]["highest_selling_item"]["item_name"] == biryani["name"]
    assert bi["sales"]["highest_revenue_item"]["item_name"] in top_names
    assert bi["sales"]["lowest_selling_sold_item"]["item_name"] == coffee["name"]
    assert bi["sales"]["zero_sales_count"] >= 1
    assert len(bi["sales"]["product_demand_trends"]) >= 1
    assert len(bi["sales"]["product_demand_trend_keys"]) >= 1
    combos = bi["sales"]["frequent_combinations"]
    assert any(
        {c["item_a"], c["item_b"]} == {biryani["name"], coffee["name"]} and c["co_order_count"] == 1
        for c in combos
    )

    # Section 5: Customer Intelligence & Satisfaction
    cust = bi["customers"]
    assert cust["registered_customers"] >= 1
    assert cust["active_ordering_customers"] == 1
    assert cust["new_customers"] == 1
    assert Decimal(str(cust["avg_customer_spending"])) == expected_paid_rev
    assert cust["review_count"] == 1
    assert cust["average_food_rating"] == 5.0
    assert cust["rating_distribution"]["5"] == 1
    assert len(cust["satisfaction_trends"]) >= 1

    # Section 6: Operational Intelligence & Out-of-Stock Alerts
    assert bi["operations"]["kitchen_workload_percent"] >= 0.0
    assert len(bi["operations"]["peak_hours"]) >= 1
    assert bi["inventory"]["out_of_stock_products_count"] >= 1
    assert any(p["food_item_id"] == extra_item["id"] for p in bi["inventory"]["out_of_stock_products"])

    # Section 7: Real DB-Backed Business Insights (with V2 structured fields)
    assert isinstance(bi["business_insights"], list)
    assert len(bi["business_insights"]) >= 1
    assert all(
        "id" in ins and "drilldown" in ins and "what_happened" in ins and "recommended_action" in ins and "time_period" in ins
        for ins in bi["business_insights"]
    )
    assert "aov" in bi["sales"]["daily_series"][0]
    assert len(bi["sales"]["yearly_series"]) >= 1
    assert len(bi["sales"]["canteen_sales"]) >= 1
    assert isinstance(bi["sales"]["declining_items"], list)
    assert bi["sales"]["best_category_by_revenue"] is not None
    assert bi["operations"]["peak_hour_intel"]["has_data"] is True
    assert bi["operations"]["peak_hour_intel"]["peak_window"]
    assert "order_frequency_distribution" in bi["customers"]
    assert len(bi["customers"]["new_customers_trends"]) >= 1
    assert "has_prep_timestamps" in bi["operations"]

    # 5. Date Presets & Custom Range Validation
    today = today_college()
    for preset in ("today", "yesterday", "last_7_days", "last_30_days", "this_month", "previous_month"):
        p_res = client.get(f"/api/v1/reports/dashboard?canteen_id={cid}&preset={preset}", headers=admin["headers"])
        assert p_res.status_code == 200
        assert p_res.json()["range"]["preset"] == preset

    c_res = client.get(
        f"/api/v1/reports/dashboard?canteen_id={cid}&start_date={(today - timedelta(days=2)).isoformat()}&end_date={today.isoformat()}",
        headers=admin["headers"],
    )
    assert c_res.status_code == 200
    assert c_res.json()["range"]["preset"] == "custom"

    # 6. Drill-Down Filters (/details/orders)
    d_delayed = client.get(
        f"/api/v1/reports/details/orders?canteen_id={cid}&preset=today&delayed_only=true",
        headers=admin["headers"],
    )
    assert d_delayed.status_code == 200
    assert d_delayed.json()["total"] == 1
    assert d_delayed.json()["items"][0]["order_number"] == paid_order["order_number"]

    d_item = client.get(
        f"/api/v1/reports/details/orders?canteen_id={cid}&preset=today&food_item_id={biryani['id']}",
        headers=admin["headers"],
    )
    assert d_item.status_code == 200
    assert d_item.json()["total"] == 1

    d_cancelled = client.get(
        f"/api/v1/reports/details/orders?canteen_id={cid}&preset=today&status=CANCELLED",
        headers=admin["headers"],
    )
    assert d_cancelled.status_code == 200
    assert d_cancelled.json()["total"] == 1
    assert d_cancelled.json()["items"][0]["order_number"] == unpaid_order["order_number"]

    # 7. Cache Invalidation: placing and paying a second order updates cached BI dashboard immediately
    second_paid = _create_paid_razorpay_order(
        client,
        student["headers"],
        cid,
        [{"food_item_id": coffee["id"], "quantity": 1}],
        idem_key="bi-paid-cache-inv-2",
        pay_id="pay_bi_cache_002",
    )
    rep_after = client.get(
        f"/api/v1/reports/dashboard?canteen_id={cid}&preset=today&compare_previous=true",
        headers=admin["headers"],
    )
    assert rep_after.status_code == 200
    bi_after = rep_after.json()
    assert bi_after["sales"]["total_orders"] == 2
    expected_total_rev = expected_paid_rev + Decimal(str(second_paid["total_amount"])).quantize(Decimal("0.01"))
    assert Decimal(bi_after["sales"]["net_sales"]) == expected_total_rev

    # 8. Role & Canteen Scope RBAC
    assert client.get("/api/v1/reports/dashboard", headers=student["headers"]).status_code == 403
    assert (
        client.get(
            f"/api/v1/reports/dashboard?canteen_id={other_canteen['id']}&preset=today",
            headers=manager["headers"],
        ).status_code
        == 403
    )
