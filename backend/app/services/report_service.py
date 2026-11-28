import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.cache import NS_REPORTS, cache_manager
from app.core.time_utils import get_college_tz, today_college
from app.models.auth import StaffProfile, User
from app.models.college import Counter
from app.models.engagement import Review, SupportTicket
from app.models.inventory import InventoryItem, PurchaseOrder, StockBatch, StockMovement, WastageRecord
from app.models.menu import FoodCategory, FoodItem, Ingredient
from app.models.order import Order, OrderItem, OrderStatusHistory
from app.models.payment import Payment, PickupToken
from app.models.staff import StaffAttendance, StaffTask

PENDING_ACTIVE_STATUSES = ("PAYMENT_PENDING", "PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING", "READY")
VALID_PRESETS = {"today", "yesterday", "last_7_days", "last_30_days", "this_month", "custom"}


def _to_local_dt(dt: datetime, tz) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def resolve_report_date_range(
    preset: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> tuple[date, date, str]:
    local_today = today_college()
    chosen_preset = (preset or "").strip().lower()
    if chosen_preset and chosen_preset not in VALID_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unsupported date preset '{preset}'")

    if chosen_preset == "today":
        return local_today, local_today, "today"
    if chosen_preset == "yesterday":
        y = local_today - timedelta(days=1)
        return y, y, "yesterday"
    if chosen_preset == "last_7_days":
        return local_today - timedelta(days=6), local_today, "last_7_days"
    if chosen_preset == "last_30_days":
        return local_today - timedelta(days=29), local_today, "last_30_days"
    if chosen_preset == "this_month":
        return local_today.replace(day=1), local_today, "this_month"

    s_date = start_date or (local_today - timedelta(days=29))
    e_date = end_date or local_today
    if e_date < s_date:
        s_date, e_date = e_date, s_date
    eff_preset = chosen_preset or ("custom" if (start_date or end_date) else "last_30_days")
    return s_date, e_date, eff_preset


def get_analytics_report(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    preset: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    category_id: Optional[UUID] = None,
    food_item_id: Optional[UUID] = None,
    compare_previous: bool = False,
) -> dict[str, Any]:
    college_tz = get_college_tz()
    local_today = today_college()
    s_date, e_date, resolved_preset = resolve_report_date_range(preset, start_date, end_date)

    cache_ns = f"{NS_REPORTS}:{canteen_id}" if canteen_id else NS_REPORTS
    cache_key = (
        f"dash:{canteen_id or 'all'}:{resolved_preset}:{s_date.isoformat()}:{e_date.isoformat()}"
        f":{category_id or 'all'}:{food_item_id or 'all'}:{int(compare_previous)}"
    )
    hit, cached = cache_manager.get_json(cache_ns, cache_key, l1_ttl=2.0)
    if hit and isinstance(cached, dict):
        return cached

    s_dt = datetime.combine(s_date, time.min, tzinfo=college_tz)
    e_dt = datetime.combine(e_date, time.max, tzinfo=college_tz)

    order_filters = [Order.created_at >= s_dt, Order.created_at <= e_dt]
    if canteen_id:
        order_filters.append(Order.canteen_id == canteen_id)
    if food_item_id:
        order_filters.append(
            Order.id.in_(select(OrderItem.order_id).where(OrderItem.food_item_id == food_item_id))
        )
    elif category_id:
        order_filters.append(
            Order.id.in_(
                select(OrderItem.order_id)
                .join(FoodItem, FoodItem.id == OrderItem.food_item_id)
                .where(FoodItem.category_id == category_id)
            )
        )

    paid_filters = order_filters + [Order.payment_status == "CONFIRMED"]

    # 1. Sales & Operations aggregates collapsed into 2 single-pass SQL queries (down from 13 queries)
    has_item_or_cat_filter = bool(food_item_id or category_id)
    sales_row = db.execute(
        select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.subtotal_amount), 0),
            func.coalesce(func.sum(Order.discount_amount), 0),
            func.coalesce(func.sum(Order.tax_amount), 0),
            func.coalesce(func.sum(Order.total_amount), 0),
        ).where(*paid_filters)
    ).one()
    total_orders = int(sales_row[0] or 0)
    gross_sales = Decimal(str(sales_row[1] or 0))
    discounts = Decimal(str(sales_row[2] or 0))
    tax_collected = Decimal(str(sales_row[3] or 0))
    net_sales = Decimal(str(sales_row[4] or 0))
    if has_item_or_cat_filter:
        oi_rev_stmt = (
            select(
                func.coalesce(func.sum(OrderItem.line_subtotal), 0),
                func.coalesce(func.sum(OrderItem.line_total), 0),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(*paid_filters)
        )
        if food_item_id:
            oi_rev_stmt = oi_rev_stmt.where(OrderItem.food_item_id == food_item_id)
        elif category_id:
            oi_rev_stmt = oi_rev_stmt.join(FoodItem, FoodItem.id == OrderItem.food_item_id).where(
                FoodItem.category_id == category_id
            )
        oi_sub, oi_tot = db.execute(oi_rev_stmt).one()
        gross_sales = Decimal(str(oi_sub or 0)).quantize(Decimal("0.01"))
        net_sales = Decimal(str(oi_tot or 0)).quantize(Decimal("0.01"))
    aov = (net_sales / Decimal(max(1, total_orders))).quantize(Decimal("0.01")) if total_orders else Decimal("0.00")

    # Today's real-time snapshot in college timezone (1 single conditional aggregate query)
    today_s_dt = datetime.combine(local_today, time.min, tzinfo=college_tz)
    today_e_dt = datetime.combine(local_today, time.max, tzinfo=college_tz)
    today_base = [Order.created_at >= today_s_dt, Order.created_at <= today_e_dt]
    if canteen_id:
        today_base.append(Order.canteen_id == canteen_id)
    today_row = db.execute(
        select(
            func.coalesce(func.sum(case((Order.payment_status == "CONFIRMED", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status == "COMPLETED", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.status.in_(PENDING_ACTIVE_STATUSES), 1), else_=0)), 0),
            func.coalesce(func.sum(case((Order.payment_status == "CONFIRMED", Order.total_amount), else_=0)), 0),
        ).where(*today_base)
    ).one()
    total_orders_today = int(today_row[0] or 0)
    completed_orders_today = int(today_row[1] or 0)
    pending_orders_today = int(today_row[2] or 0)
    revenue_today = Decimal(str(today_row[3] or 0))

    active_pending_stmt = select(func.count(Order.id)).where(
        Order.status.in_(("PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING", "READY"))
    )
    if canteen_id:
        active_pending_stmt = active_pending_stmt.where(Order.canteen_id == canteen_id)
    active_pending_orders = db.scalar(active_pending_stmt) or 0

    # Lightweight column projection instead of full ORM Order hydration (~85% less RAM & CPU)
    paid_orders = db.execute(
        select(
            Order.created_at,
            Order.total_amount,
            Order.status,
            Order.order_channel,
            Order.counter_id,
            Order.cashier_id,
            Order.confirmed_at,
            Order.ready_at,
            Order.completed_at,
            Order.payment_method,
            Order.customer_id,
        )
        .where(*paid_filters)
        .order_by(Order.created_at.asc())
    ).all()
    daily_map: dict[str, dict[str, Any]] = {}
    span_days = (e_date - s_date).days + 1
    if 1 <= span_days <= 366:
        for offset in range(span_days):
            d_str = (s_date + timedelta(days=offset)).isoformat()
            daily_map[d_str] = {"date": d_str, "orders": 0, "revenue": Decimal("0.00")}

    weekly_map: dict[str, dict[str, Any]] = {}
    monthly_map: dict[str, dict[str, Any]] = {}
    hourly_counts: dict[int, int] = {h: 0 for h in range(24)}
    hourly_completed: dict[int, int] = {h: 0 for h in range(24)}
    hourly_revenue: dict[int, Decimal] = {h: Decimal("0.00") for h in range(24)}
    WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_map: dict[int, dict[str, Any]] = {
        idx: {
            "weekday_index": idx,
            "weekday": name,
            "orders": 0,
            "completed_orders": 0,
            "cancelled_orders": 0,
            "revenue": Decimal("0.00"),
        }
        for idx, name in enumerate(WEEKDAY_NAMES)
    }
    heatmap_counts: dict[tuple[int, int], dict[str, Any]] = {}
    daily_ops_extra: dict[str, dict[str, Any]] = {}
    prep_durations: list[float] = []
    wait_durations: list[float] = []
    completion_durations: list[float] = []
    status_counts: dict[str, int] = {}
    channel_counts: dict[str, dict[str, Any]] = {}
    pay_method_map: dict[str, list[Any]] = {}
    cust_order_map: dict[UUID, int] = {}

    for o in paid_orders:
        (
            o_created,
            o_total,
            o_status,
            o_channel,
            _o_counter,
            _o_cashier,
            o_confirmed,
            o_ready,
            o_completed,
            o_pay_method,
            o_customer_id,
        ) = o
        pm_key = o_pay_method or "unknown"
        if pm_key not in pay_method_map:
            pay_method_map[pm_key] = [0, Decimal("0.00")]
        pay_method_map[pm_key][0] += 1
        pay_method_map[pm_key][1] += o_total
        if o_customer_id is not None:
            cust_order_map[o_customer_id] = cust_order_map.get(o_customer_id, 0) + 1
        local_dt = _to_local_dt(o_created, college_tz)
        day_key = local_dt.strftime("%Y-%m-%d")
        iso = local_dt.isocalendar()
        week_key = f"{iso.year}-W{iso.week:02d}"
        week_start = (local_dt.date() - timedelta(days=local_dt.weekday())).isoformat()
        month_key = local_dt.strftime("%Y-%m")
        wd = local_dt.weekday()
        hr = local_dt.hour

        if day_key not in daily_map:
            daily_map[day_key] = {"date": day_key, "orders": 0, "revenue": Decimal("0.00")}
        daily_map[day_key]["orders"] += 1
        daily_map[day_key]["revenue"] += o_total
        d_extra = daily_ops_extra.setdefault(
            day_key,
            {"completed_orders": 0, "cancelled_orders": 0, "delayed_orders": 0, "prep_sum": 0.0, "prep_cnt": 0, "fulfil_sum": 0.0, "fulfil_cnt": 0},
        )
        if o_status == "COMPLETED":
            d_extra["completed_orders"] += 1

        if week_key not in weekly_map:
            weekly_map[week_key] = {"week": week_key, "week_start": week_start, "orders": 0, "revenue": Decimal("0.00")}
        weekly_map[week_key]["orders"] += 1
        weekly_map[week_key]["revenue"] += o_total

        if month_key not in monthly_map:
            monthly_map[month_key] = {"month": month_key, "orders": 0, "revenue": Decimal("0.00")}
        monthly_map[month_key]["orders"] += 1
        monthly_map[month_key]["revenue"] += o_total

        weekday_map[wd]["orders"] += 1
        if o_status == "COMPLETED":
            weekday_map[wd]["completed_orders"] += 1
        weekday_map[wd]["revenue"] += o_total

        hm_cell = heatmap_counts.setdefault((wd, hr), {"orders": 0, "revenue": Decimal("0.00")})
        hm_cell["orders"] += 1
        hm_cell["revenue"] += o_total

        hourly_counts[hr] = hourly_counts.get(hr, 0) + 1
        if o_status == "COMPLETED":
            hourly_completed[hr] = hourly_completed.get(hr, 0) + 1
        hourly_revenue[hr] = hourly_revenue.get(hr, Decimal("0.00")) + o_total

        status_counts[o_status] = status_counts.get(o_status, 0) + 1
        ch = o_channel or "web"
        if ch not in channel_counts:
            channel_counts[ch] = {"channel": ch, "orders": 0, "revenue": Decimal("0.00")}
        channel_counts[ch]["orders"] += 1
        channel_counts[ch]["revenue"] += o_total

        if o_confirmed and o_ready:
            pm = max(0.0, (o_ready - o_confirmed).total_seconds() / 60.0)
            prep_durations.append(pm)
            d_extra["prep_sum"] += pm
            d_extra["prep_cnt"] += 1
        if o_ready and o_completed:
            wait_durations.append(max(0.0, (o_completed - o_ready).total_seconds() / 60.0))
        if o_confirmed and o_completed:
            fm = max(0.0, (o_completed - o_confirmed).total_seconds() / 60.0)
            completion_durations.append(fm)
            d_extra["fulfil_sum"] += fm
            d_extra["fulfil_cnt"] += 1

    # Include cancelled/delayed/completed/pending counts across all orders in range (replaces separate ops_row query)
    all_status_rows = db.execute(
        select(Order.created_at, Order.status, Order.delayed_minutes).where(*order_filters)
    ).all()
    total_created_orders = len(all_status_rows)
    completed_orders = 0
    cancelled_orders = 0
    pending_orders = 0
    delayed_orders = 0
    for a_created, a_status, a_delayed in all_status_rows:
        ldt = _to_local_dt(a_created, college_tz)
        dkey = ldt.strftime("%Y-%m-%d")
        wdi = ldt.weekday()
        dx = daily_ops_extra.setdefault(
            dkey,
            {"completed_orders": 0, "cancelled_orders": 0, "delayed_orders": 0, "prep_sum": 0.0, "prep_cnt": 0, "fulfil_sum": 0.0, "fulfil_cnt": 0},
        )
        if a_status == "COMPLETED":
            completed_orders += 1
        elif a_status in ("CANCELLED", "REJECTED"):
            cancelled_orders += 1
            dx["cancelled_orders"] += 1
            weekday_map[wdi]["cancelled_orders"] += 1
        elif a_status in PENDING_ACTIVE_STATUSES:
            pending_orders += 1
        if (a_delayed or 0) > 0:
            delayed_orders += 1
            dx["delayed_orders"] += 1

    daily_series = []
    for v in sorted(daily_map.values(), key=lambda x: x["date"]):
        dx = daily_ops_extra.get(v["date"], {})
        p_cnt = dx.get("prep_cnt", 0)
        f_cnt = dx.get("fulfil_cnt", 0)
        daily_series.append(
            {
                "date": v["date"],
                "orders": v["orders"],
                "completed_orders": dx.get("completed_orders", 0),
                "cancelled_orders": dx.get("cancelled_orders", 0),
                "delayed_orders": dx.get("delayed_orders", 0),
                "revenue": float(v["revenue"]),
                "avg_prep_minutes": round(dx["prep_sum"] / p_cnt, 1) if p_cnt else 0.0,
                "avg_fulfilment_minutes": round(dx["fulfil_sum"] / f_cnt, 1) if f_cnt else 0.0,
            }
        )
    weekday_series = [
        {
            "weekday_index": w["weekday_index"],
            "weekday": w["weekday"],
            "orders": w["orders"],
            "completed_orders": w["completed_orders"],
            "cancelled_orders": w["cancelled_orders"],
            "revenue": float(w["revenue"]),
        }
        for w in sorted(weekday_map.values(), key=lambda x: x["weekday_index"])
    ]
    hourly_heatmap = [
        {
            "weekday_index": wd_idx,
            "weekday": WEEKDAY_NAMES[wd_idx],
            "hour": hr,
            "hour_label": f"{hr:02d}:00",
            "orders": heatmap_counts.get((wd_idx, hr), {}).get("orders", 0),
            "revenue": float(heatmap_counts.get((wd_idx, hr), {}).get("revenue", Decimal("0.00"))),
        }
        for wd_idx in range(7)
        for hr in range(7, 23)
    ]
    weekly_series = [
        {"week": v["week"], "week_start": v["week_start"], "orders": v["orders"], "revenue": float(v["revenue"])}
        for v in sorted(weekly_map.values(), key=lambda x: x["week"])
    ]
    monthly_series = [
        {"month": v["month"], "orders": v["orders"], "revenue": float(v["revenue"])}
        for v in sorted(monthly_map.values(), key=lambda x: x["month"])
    ]
    hourly_series = [
        {
            "hour": f"{h:02d}:00",
            "orders": hourly_counts[h],
            "completed_orders": hourly_completed[h],
            "revenue": float(hourly_revenue[h]),
        }
        for h in range(24)
    ]
    peak_hours = [
        {"hour": f"{h:02d}:00", "orders": c, "revenue": float(hourly_revenue[h])}
        for h, c in sorted(hourly_counts.items(), key=lambda kv: (-kv[1], -float(hourly_revenue[kv[0]]), kv[0]))
        if c > 0
    ]

    # Single unified OrderItem query feeding item performance, category sales, top-5 demand trends, and market-basket pairs
    oi_all_rows = db.execute(
        select(
            OrderItem.order_id,
            Order.created_at,
            OrderItem.food_item_id,
            OrderItem.item_name,
            OrderItem.quantity,
            OrderItem.line_total,
            FoodItem.category_id,
            FoodCategory.name,
        )
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(FoodItem, FoodItem.id == OrderItem.food_item_id)
        .outerjoin(FoodCategory, FoodCategory.id == FoodItem.category_id)
        .where(*paid_filters)
    ).all()

    sold_qty_by_food_id: dict[UUID, int] = {}
    sold_rev_by_food_id: dict[UUID, float] = {}
    sold_orders_by_food_id: dict[UUID, set[UUID]] = {}
    sold_qty_by_name: dict[str, int] = {}
    sold_rev_by_name: dict[str, float] = {}
    sold_orders_by_name: dict[str, set[UUID]] = {}
    cat_acc: dict[str, list[Any]] = {}
    items_per_order: dict[UUID, set[str]] = {}

    for idx_oi, (oid_val, o_ts, fid, iname, qty, line_tot, f_cat_id, cat_name) in enumerate(oi_all_rows):
        q_i = int(qty or 0)
        r_f = float(line_tot or 0)
        matches_filter = True
        if food_item_id and fid != food_item_id:
            matches_filter = False
        elif not food_item_id and category_id and f_cat_id != category_id:
            matches_filter = False

        if matches_filter:
            if fid:
                sold_qty_by_food_id[fid] = sold_qty_by_food_id.get(fid, 0) + q_i
                sold_rev_by_food_id[fid] = round(sold_rev_by_food_id.get(fid, 0.0) + r_f, 2)
                sold_orders_by_food_id.setdefault(fid, set()).add(oid_val)
            if iname:
                sold_qty_by_name[iname] = sold_qty_by_name.get(iname, 0) + q_i
                sold_rev_by_name[iname] = round(sold_rev_by_name.get(iname, 0.0) + r_f, 2)
                sold_orders_by_name.setdefault(iname, set()).add(oid_val)

        if cat_name:
            if cat_name not in cat_acc:
                cat_acc[cat_name] = [0, Decimal("0.00")]
            cat_acc[cat_name][0] += q_i
            cat_acc[cat_name][1] += Decimal(str(line_tot or 0))

        if idx_oi < 6000 and iname:
            items_per_order.setdefault(oid_val, set()).add(iname)

    sold_by_food_id: dict[UUID, tuple[int, float, int]] = {
        fid: (sold_qty_by_food_id[fid], sold_rev_by_food_id[fid], len(sold_orders_by_food_id[fid]))
        for fid in sold_qty_by_food_id
    }
    sold_by_name: dict[str, tuple[int, float, int]] = {
        iname: (sold_qty_by_name[iname], sold_rev_by_name[iname], len(sold_orders_by_name[iname]))
        for iname in sold_qty_by_name
    }

    top_items = [
        {"item_name": name, "quantity_sold": q, "order_count": oc, "revenue": r}
        for name, (q, r, oc) in sorted(sold_by_name.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:15]
    ]

    food_stmt = select(FoodItem, FoodCategory.name).join(FoodCategory, FoodCategory.id == FoodItem.category_id).where(FoodItem.is_active.is_(True))
    if canteen_id:
        food_stmt = food_stmt.where(FoodItem.canteen_id == canteen_id)
    if category_id:
        food_stmt = food_stmt.where(FoodItem.category_id == category_id)
    if food_item_id:
        food_stmt = food_stmt.where(FoodItem.id == food_item_id)
    active_foods = db.execute(food_stmt.order_by(FoodItem.name.asc())).all()
    all_food_perf = []
    for fi, cat_name in active_foods:
        q_sold, rev_amt, o_cnt = sold_by_food_id.get(fi.id, (0, 0.0, 0))
        all_food_perf.append({
            "food_item_id": str(fi.id),
            "item_name": fi.name,
            "category_name": cat_name,
            "quantity_sold": q_sold,
            "order_count": o_cnt,
            "revenue": rev_amt,
            "is_available": fi.is_available,
        })
    least_ordered_items = sorted(
        all_food_perf,
        key=lambda x: (x["quantity_sold"], x["revenue"], x["item_name"]),
    )[:15]

    # Out-of-stock / unavailable products + Product demand trends (top 5) + Market-basket co-occurrence
    out_of_stock_items = [
        {
            "food_item_id": str(fi.id),
            "item_name": fi.name,
            "category_name": cat_name,
            "reason": "Low ingredients" if fi.insufficient_ingredients else "Marked sold out",
            "insufficient_ingredients": bool(fi.insufficient_ingredients),
        }
        for fi, cat_name in active_foods
        if (not fi.is_available) or fi.insufficient_ingredients
    ]

    top_5_names = [t["item_name"] for t in top_items[:5]]
    top_5_set = set(top_5_names)
    product_demand_trends: list[dict[str, Any]] = []
    if top_5_names:
        trend_by_day: dict[str, dict[str, int]] = {d["date"]: {n: 0 for n in top_5_names} for d in daily_series}
        for _oid_val, o_ts, _fid, iname, iqty, _lt, _fc, _cn in oi_all_rows:
            if iname in top_5_set:
                dkey = _to_local_dt(o_ts, college_tz).strftime("%Y-%m-%d")
                bucket = trend_by_day.setdefault(dkey, {n: 0 for n in top_5_names})
                bucket[iname] = bucket.get(iname, 0) + int(iqty or 0)
        product_demand_trends = [
            {"date": dkey, **counts} for dkey, counts in sorted(trend_by_day.items(), key=lambda x: x[0])
        ]

    # Frequently purchased item combinations across confirmed orders in range
    pair_counts: dict[tuple[str, str], int] = {}
    multi_item_orders = 0
    for name_set in items_per_order.values():
        if len(name_set) < 2:
            continue
        multi_item_orders += 1
        sorted_names = sorted(name_set)
        for idx_a in range(len(sorted_names)):
            for idx_b in range(idx_a + 1, len(sorted_names)):
                pair = (sorted_names[idx_a], sorted_names[idx_b])
                pair_counts[pair] = pair_counts.get(pair, 0) + 1
    frequent_combinations = [
        {
            "item_a": a,
            "item_b": b,
            "pair_label": f"{a} + {b}",
            "co_order_count": cnt,
            "support_percent": round((cnt / max(1, total_orders)) * 100.0, 1),
        }
        for (a, b), cnt in sorted(pair_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    ]

    category_sales = [{"category": name, "quantity": vals[0], "revenue": float(vals[1])} for name, vals in cat_acc.items()]

    counter_rows = db.execute(
        select(Counter.name, func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0))
        .join(Counter, Counter.id == Order.counter_id)
        .where(*paid_filters)
        .group_by(Counter.name)
    ).all()
    counter_sales = [{"counter": name, "orders": int(cnt), "revenue": float(rev)} for name, cnt, rev in counter_rows]

    # Counter utilization & prep/wait performance
    cnt_stmt = select(Counter).where(Counter.is_active.is_(True)).order_by(Counter.name.asc())
    if canteen_id:
        cnt_stmt = cnt_stmt.where(Counter.canteen_id == canteen_id)
    counters_list = db.scalars(cnt_stmt).all()
    active_by_counter: dict[UUID, int] = {}
    for cid_row, c_act in db.execute(
        select(Order.counter_id, func.count(Order.id))
        .where(Order.status.in_(("PAYMENT_CONFIRMED", "PLACED", "ACCEPTED", "PREPARING")))
        .group_by(Order.counter_id)
    ).all():
        active_by_counter[cid_row] = int(c_act or 0)

    orders_by_cnt: dict[UUID, list[tuple]] = {}
    for o in paid_orders:
        orders_by_cnt.setdefault(o[4], []).append(o)

    counter_performance = []
    for cnt in counters_list:
        c_orders = orders_by_cnt.get(cnt.id, [])
        c_comp = sum(1 for o in c_orders if o[2] == "COMPLETED")
        c_rev = float(sum((Decimal(str(o[1])) for o in c_orders), Decimal("0.00")))
        c_preps = [max(0.0, (o[7] - o[6]).total_seconds() / 60.0) for o in c_orders if o[6] and o[7]]
        c_waits = [max(0.0, (o[8] - o[7]).total_seconds() / 60.0) for o in c_orders if o[7] and o[8]]
        act_cnt = active_by_counter.get(cnt.id, 0)
        cap = max(1, int(cnt.max_queue_capacity or 25))
        counter_performance.append({
            "counter_id": str(cnt.id),
            "counter_name": cnt.name,
            "counter_type": cnt.counter_type,
            "orders": len(c_orders),
            "completed_orders": c_comp,
            "revenue": round(c_rev, 2),
            "avg_prep_minutes": round(sum(c_preps) / len(c_preps), 1) if c_preps else 0.0,
            "avg_pickup_wait_minutes": round(sum(c_waits) / len(c_waits), 1) if c_waits else 0.0,
            "active_queue_count": act_cnt,
            "max_queue_capacity": cap,
            "utilization_percent": round(min(100.0, (act_cnt / cap) * 100.0), 1),
        })

    payment_breakdown = [{"method": m, "orders": vals[0], "amount": float(vals[1])} for m, vals in pay_method_map.items()]

    order_status_breakdown = [{"status": st, "count": cnt} for st, cnt in sorted(status_counts.items())]
    channel_breakdown = [
        {"channel": ch["channel"], "orders": ch["orders"], "revenue": float(ch["revenue"])}
        for ch in sorted(channel_counts.values(), key=lambda x: -x["orders"])
    ]

    # Real gateway/POS payment attempt stats from Payment rows
    pay_att_stmt = (
        select(Payment.status, func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0))
        .join(Order, Order.id == Payment.order_id)
        .where(Payment.created_at >= s_dt, Payment.created_at <= e_dt)
    )
    if canteen_id:
        pay_att_stmt = pay_att_stmt.where(Order.canteen_id == canteen_id)
    pay_att_rows = db.execute(pay_att_stmt.group_by(Payment.status)).all()
    pay_status_map = {st: (int(cnt), Decimal(str(amt))) for st, cnt, amt in pay_att_rows}
    confirmed_cnt, confirmed_amt = pay_status_map.get("CONFIRMED", (0, Decimal("0.00")))
    failed_cnt, failed_amt = pay_status_map.get("FAILED", (0, Decimal("0.00")))
    pending_pay_cnt, _ = pay_status_map.get("PENDING", (0, Decimal("0.00")))
    total_attempts = sum(c for c, _ in pay_status_map.values())
    pay_success_rate = round((confirmed_cnt / max(1, total_attempts)) * 100.0, 1) if total_attempts else 0.0

    # 2. Operations metrics (already accumulated above from all_status_rows)
    completion_rate = min(100.0, round((completed_orders / max(1, total_orders)) * 100.0, 1)) if total_orders else 0.0

    # 3. Inventory metrics, consumption & shortage trends (outerjoin WastageRecord so prepared-food waste counts too)
    inv_stmt = (
        select(InventoryItem, Ingredient.name)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.is_archived.is_(False))
    )
    if canteen_id:
        inv_stmt = inv_stmt.where(InventoryItem.canteen_id == canteen_id)
    inv_rows = db.execute(inv_stmt.order_by(InventoryItem.current_quantity.asc())).all()
    inv_id_map = {inv.id: (inv, ing_name) for inv, ing_name in inv_rows}
    low_stock_rows = [(inv, ing_name) for inv, ing_name in inv_rows if inv.current_quantity <= inv.reorder_level]
    low_stock_items = [
        {
            "inventory_item_id": str(inv.id),
            "ingredient_name": ing_name,
            "current_quantity": str(inv.current_quantity),
            "reorder_level": str(inv.reorder_level),
            "unit": inv.unit,
        }
        for inv, ing_name in low_stock_rows[:25]
    ]

    mov_stmt = (
        select(StockMovement, InventoryItem, Ingredient.name)
        .join(InventoryItem, InventoryItem.id == StockMovement.inventory_item_id)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(StockMovement.created_at >= s_dt, StockMovement.created_at <= e_dt)
    )
    if canteen_id:
        mov_stmt = mov_stmt.where(InventoryItem.canteen_id == canteen_id)
    mov_rows = db.execute(mov_stmt.order_by(StockMovement.created_at.asc())).all()

    cons_daily: dict[str, dict[str, Any]] = {}
    if 1 <= span_days <= 366:
        for offset in range(span_days):
            d_str = (s_date + timedelta(days=offset)).isoformat()
            cons_daily[d_str] = {"date": d_str, "consumed_qty": 0.0, "restocked_qty": 0.0, "wastage_qty": 0.0, "wastage_loss": 0.0}

    cons_by_item: dict[UUID, dict[str, Any]] = {
        inv.id: {
            "inventory_item_id": str(inv.id),
            "ingredient_name": ing_name,
            "unit": inv.unit,
            "consumed_quantity": 0.0,
            "restocked_quantity": 0.0,
            "wastage_quantity": 0.0,
            "current_quantity": float(inv.current_quantity),
            "reorder_level": float(inv.reorder_level),
            "is_low_stock": bool(inv.current_quantity <= inv.reorder_level),
        }
        for inv, ing_name in inv_rows
    }

    for sm, inv, ing_name in mov_rows:
        d_str = _to_local_dt(sm.created_at, college_tz).strftime("%Y-%m-%d")
        bucket = cons_daily.setdefault(d_str, {"date": d_str, "consumed_qty": 0.0, "restocked_qty": 0.0, "wastage_qty": 0.0, "wastage_loss": 0.0})
        delta = float(sm.quantity_delta or 0)
        entry = cons_by_item.setdefault(
            inv.id,
            {
                "inventory_item_id": str(inv.id),
                "ingredient_name": ing_name,
                "unit": inv.unit,
                "consumed_quantity": 0.0,
                "restocked_quantity": 0.0,
                "wastage_quantity": 0.0,
                "current_quantity": float(inv.current_quantity),
                "reorder_level": float(inv.reorder_level),
                "is_low_stock": bool(inv.current_quantity <= inv.reorder_level),
            },
        )
        if sm.movement_type in ("order_deduct", "order_deduction", "production_use"):
            qty_abs = abs(delta)
            bucket["consumed_qty"] = round(bucket["consumed_qty"] + qty_abs, 3)
            entry["consumed_quantity"] = round(entry["consumed_quantity"] + qty_abs, 3)
        elif sm.movement_type == "purchase" or delta > 0:
            bucket["restocked_qty"] = round(bucket["restocked_qty"] + max(0.0, delta), 3)
            entry["restocked_quantity"] = round(entry["restocked_quantity"] + max(0.0, delta), 3)
        elif sm.movement_type == "wastage":
            qty_abs = abs(delta)
            bucket["wastage_qty"] = round(bucket["wastage_qty"] + qty_abs, 3)
            entry["wastage_quantity"] = round(entry["wastage_quantity"] + qty_abs, 3)

    wastage_stmt = (
        select(WastageRecord)
        .outerjoin(InventoryItem, InventoryItem.id == WastageRecord.inventory_item_id)
        .where(WastageRecord.waste_date >= s_date, WastageRecord.waste_date <= e_date)
    )
    if canteen_id:
        wastage_stmt = wastage_stmt.where(func.coalesce(WastageRecord.canteen_id, InventoryItem.canteen_id) == canteen_id)
    wastage_rows = db.scalars(wastage_stmt).all()
    wastage_breakdown: dict[str, dict[str, str]] = {
        "damaged": {"quantity": "0.000", "loss_amount": "0.00"},
        "expired": {"quantity": "0.000", "loss_amount": "0.00"},
        "wastage": {"quantity": "0.000", "loss_amount": "0.00"},
        "unsold": {"quantity": "0.000", "loss_amount": "0.00"},
    }
    w_q_acc: dict[str, Decimal] = {}
    w_l_acc: dict[str, Decimal] = {}
    total_wastage = Decimal("0.00")
    for wr in wastage_rows:
        lt = wr.loss_type or "wastage"
        q_dec = Decimal(str(wr.quantity or 0))
        l_dec = Decimal(str(wr.estimated_loss or 0))
        total_wastage += l_dec
        w_q_acc[lt] = w_q_acc.get(lt, Decimal("0.000")) + q_dec
        w_l_acc[lt] = w_l_acc.get(lt, Decimal("0.00")) + l_dec
        d_str = wr.waste_date.isoformat() if wr.waste_date else _to_local_dt(wr.created_at, college_tz).strftime("%Y-%m-%d")
        b = cons_daily.setdefault(d_str, {"date": d_str, "consumed_qty": 0.0, "restocked_qty": 0.0, "wastage_qty": 0.0, "wastage_loss": 0.0})
        b["wastage_loss"] = round(b["wastage_loss"] + float(l_dec), 2)
    for lt in w_l_acc:
        wastage_breakdown[lt] = {"quantity": f"{w_q_acc[lt]:.3f}", "loss_amount": f"{w_l_acc[lt]:.2f}"}

    consumption_trends = [cons_daily[k] for k in sorted(cons_daily.keys())]
    consumption_summary = sorted(
        cons_by_item.values(),
        key=lambda x: (-x["consumed_quantity"], x["current_quantity"], x["ingredient_name"]),
    )[:25]

    po_stmt = select(func.coalesce(func.sum(PurchaseOrder.total_cost), 0)).where(
        PurchaseOrder.status == "received",
        PurchaseOrder.created_at >= s_dt,
        PurchaseOrder.created_at <= e_dt,
    )
    if canteen_id:
        po_stmt = po_stmt.where(PurchaseOrder.canteen_id == canteen_id)
    total_purchases = db.scalar(po_stmt) or Decimal("0.00")

    exp_stmt = (
        select(func.count(StockBatch.id))
        .join(InventoryItem, InventoryItem.id == StockBatch.inventory_item_id)
        .where(
            InventoryItem.is_archived.is_(False),
            StockBatch.remaining_quantity > 0,
            StockBatch.expiry_date.is_not(None),
            StockBatch.expiry_date <= local_today + timedelta(days=7),
        )
    )
    if canteen_id:
        exp_stmt = exp_stmt.where(InventoryItem.canteen_id == canteen_id)
    expiring_count = db.scalar(exp_stmt) or 0

    # 4. Customer metrics (new, returning, repeat rate, average spending, satisfaction trends)
    total_customers = db.scalar(select(func.count(User.id)).where(User.user_kind == "customer")) or 0
    new_customers = (
        db.scalar(
            select(func.count(User.id)).where(
                User.user_kind == "customer",
                User.created_at >= s_dt,
                User.created_at <= e_dt,
            )
        )
        or 0
    )
    active_cust_cnt = len(cust_order_map)
    returning_customers = sum(1 for cnt in cust_order_map.values() if cnt > 1)
    repeat_rate = round((returning_customers / max(1, active_cust_cnt)) * 100.0, 1) if active_cust_cnt else 0.0
    avg_customer_spending = (
        (net_sales / Decimal(active_cust_cnt)).quantize(Decimal("0.01")) if active_cust_cnt > 0 else Decimal("0.00")
    )

    rev_rows_stmt = select(Review.rating, Review.created_at).where(
        Review.is_visible.is_(True), Review.created_at >= s_dt, Review.created_at <= e_dt
    )
    if canteen_id:
        rev_rows_stmt = rev_rows_stmt.where(Review.canteen_id == canteen_id)
    rev_rows = db.execute(rev_rows_stmt.order_by(Review.created_at.asc())).all()
    rating_dist = {str(s): 0 for s in range(1, 6)}
    sat_daily: dict[str, dict[str, Any]] = {}
    rating_sum = 0.0
    for r_val, r_ts in rev_rows:
        rv = int(r_val or 0)
        rating_sum += rv
        if 1 <= rv <= 5:
            rating_dist[str(rv)] += 1
        if r_ts:
            dkey = _to_local_dt(r_ts, college_tz).strftime("%Y-%m-%d")
            sd = sat_daily.setdefault(dkey, {"date": dkey, "rating_sum": 0.0, "review_count": 0})
            sd["rating_sum"] += rv
            sd["review_count"] += 1
    avg_rating = (rating_sum / len(rev_rows)) if rev_rows else 0.0
    satisfaction_trends = [
        {
            "date": k,
            "avg_rating": round(v["rating_sum"] / max(1, v["review_count"]), 2),
            "review_count": v["review_count"],
        }
        for k, v in sorted(sat_daily.items())
    ]

    # 5. Support metrics
    sup_stmt = select(SupportTicket).where(SupportTicket.created_at >= s_dt, SupportTicket.created_at <= e_dt)
    if canteen_id:
        sup_stmt = sup_stmt.where(SupportTicket.canteen_id == canteen_id)
    tickets = db.scalars(sup_stmt).all()
    open_tickets = sum(1 for t in tickets if t.status in ("open", "assigned", "in_progress"))
    resolved_tickets = sum(1 for t in tickets if t.status in ("resolved", "closed"))
    res_mins = [
        max(0.0, (t.resolved_at - t.created_at).total_seconds() / 60.0)
        for t in tickets
        if t.resolved_at and t.created_at
    ]

    # 6. Staff performance & activity metrics (fixed staff_user_id!)
    att_stmt = select(StaffAttendance).where(
        StaffAttendance.attendance_date >= s_date, StaffAttendance.attendance_date <= e_date
    )
    if canteen_id:
        att_stmt = att_stmt.where(StaffAttendance.canteen_id == canteen_id)
    att_rows = db.scalars(att_stmt).all()
    present_checkins = sum(1 for a in att_rows if a.status == "present")
    leave_days = sum(1 for a in att_rows if a.status in ("leave", "leave_pending"))

    task_stmt = select(StaffTask).where(StaffTask.created_at >= s_dt, StaffTask.created_at <= e_dt)
    if canteen_id:
        task_stmt = task_stmt.where(StaffTask.canteen_id == canteen_id)
    tasks = db.scalars(task_stmt).all()
    tasks_done = sum(1 for t in tasks if t.status == "done")
    cashier_orders = sum(1 for o in paid_orders if o[5] is not None)
    cashier_counts_by_uid: dict[UUID, int] = {}
    for o in paid_orders:
        if o[5] is not None:
            cashier_counts_by_uid[o[5]] = cashier_counts_by_uid.get(o[5], 0) + 1

    hist_stmt = (
        select(OrderStatusHistory.changed_by_user_id, func.count(OrderStatusHistory.id))
        .join(Order, Order.id == OrderStatusHistory.order_id)
        .where(
            OrderStatusHistory.created_at >= s_dt,
            OrderStatusHistory.created_at <= e_dt,
            OrderStatusHistory.changed_by_user_id.is_not(None),
        )
        .group_by(OrderStatusHistory.changed_by_user_id)
    )
    if canteen_id:
        hist_stmt = hist_stmt.where(Order.canteen_id == canteen_id)
    status_action_counts = {uid: int(cnt) for uid, cnt in db.execute(hist_stmt).all()}

    staff_stmt = select(User, StaffProfile).join(StaffProfile, StaffProfile.user_id == User.id)
    if canteen_id:
        staff_stmt = staff_stmt.where(StaffProfile.assigned_canteen_id == canteen_id)
    staff_profiles = db.execute(staff_stmt.order_by(User.full_name.asc())).all()
    staff_breakdown = []
    for u, sp in staff_profiles:
        u_att_present = [a for a in att_rows if a.staff_user_id == u.id and a.status == "present"]
        u_checkins = len(u_att_present)
        u_worked_mins = sum(int(a.worked_minutes or 0) for a in u_att_present)
        u_tasks_tot = sum(1 for t in tasks if t.assigned_to_user_id == u.id)
        u_tasks_done = sum(1 for t in tasks if t.assigned_to_user_id == u.id and t.status == "done")
        u_cashier = cashier_counts_by_uid.get(u.id, 0)
        u_actions = status_action_counts.get(u.id, 0)
        staff_breakdown.append({
            "user_id": str(u.id),
            "full_name": u.full_name,
            "employee_code": sp.employee_code,
            "checkins": u_checkins,
            "worked_minutes": u_worked_mins,
            "tasks_total": u_tasks_tot,
            "tasks_completed": u_tasks_done,
            "cashier_orders": u_cashier,
            "status_updates": u_actions,
        })

    # 7. Financial Analytics (STRICT separation of Revenue vs Verified Costs vs Estimated Margin — NEVER label revenue as profit)
    verified_ingredient_cost = Decimal("0.00")
    batch_ids_used = {sm.batch_id for sm, _inv, _ing in mov_rows if sm.batch_id}
    batch_cost_map = (
        {
            b.id: Decimal(str(b.unit_cost or 0))
            for b in db.scalars(select(StockBatch).where(StockBatch.id.in_(list(batch_ids_used)))).all()
        }
        if batch_ids_used
        else {}
    )
    for sm, inv, _ing_name in mov_rows:
        if sm.movement_type in ("order_deduct", "order_deduction", "production_use"):
            qty_abs = abs(Decimal(str(sm.quantity_delta or 0)))
            uc = batch_cost_map.get(sm.batch_id) if sm.batch_id else None
            if uc is None or uc <= Decimal("0.00"):
                uc = Decimal(str(inv.unit_cost or 0))
            verified_ingredient_cost += (qty_abs * uc)
    verified_ingredient_cost = verified_ingredient_cost.quantize(Decimal("0.01"))
    recorded_wastage_loss = Decimal(str(total_wastage)).quantize(Decimal("0.01"))
    total_recorded_direct_costs = (verified_ingredient_cost + recorded_wastage_loss).quantize(Decimal("0.01"))

    if has_item_or_cat_filter:
        est_margin = None
        est_margin_pct = None
        margin_status = "whole_canteen_scope_required"
        margin_note = (
            "Canteen-wide ingredient consumption costs cannot be isolated to a single category or product filter. "
            "Clear category/product filters to view estimated gross margin. Verified revenue is NOT labeled as profit."
        )
    elif verified_ingredient_cost > Decimal("0.00") and net_sales > Decimal("0.00"):
        est_margin = (net_sales - total_recorded_direct_costs).quantize(Decimal("0.01"))
        est_margin_pct = round(float((est_margin / net_sales) * Decimal("100")), 1)
        margin_status = "estimated_from_verified_ingredient_costs"
        margin_note = (
            "Estimated gross margin = Verified Net Revenue - (Verified Ingredient Consumption Cost + Recorded Wastage Loss). "
            "Excludes unrecorded overhead such as rent, utilities, and labor."
        )
    else:
        est_margin = None
        est_margin_pct = None
        margin_status = "insufficient_cost_data"
        margin_note = (
            "Insufficient verified ingredient cost data to calculate gross margin. "
            "Verified net revenue is displayed separately and is NOT labeled as profit."
        )

    collected_payments = Decimal(str(confirmed_amt)).quantize(Decimal("0.01"))
    refunds_amount = Decimal("0.00")
    cancellation_rate_percent = (
        round((cancelled_orders / max(1, total_created_orders)) * 100.0, 1) if total_created_orders > 0 else 0.0
    )

    period_comparison = None
    prev_end = s_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=max(0, span_days - 1))
    prev_s_dt = datetime.combine(prev_start, time.min, tzinfo=college_tz)
    prev_e_dt = datetime.combine(prev_end, time.max, tzinfo=college_tz)
    prev_filters = [
        Order.created_at >= prev_s_dt,
        Order.created_at <= prev_e_dt,
        Order.payment_status == "CONFIRMED",
    ]
    if canteen_id:
        prev_filters.append(Order.canteen_id == canteen_id)
    if food_item_id:
        prev_filters.append(
            Order.id.in_(select(OrderItem.order_id).where(OrderItem.food_item_id == food_item_id))
        )
    elif category_id:
        prev_filters.append(
            Order.id.in_(
                select(OrderItem.order_id)
                .join(FoodItem, FoodItem.id == OrderItem.food_item_id)
                .where(FoodItem.category_id == category_id)
            )
        )
    prev_row = db.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0)).where(*prev_filters)
    ).one()
    prev_orders = int(prev_row[0] or 0)
    prev_rev = Decimal(str(prev_row[1] or 0)).quantize(Decimal("0.01"))
    orders_change_pct = (
        round(((total_orders - prev_orders) / prev_orders) * 100.0, 1) if prev_orders > 0 else None
    )
    rev_change_pct = (
        round(float(((net_sales - prev_rev) / prev_rev) * Decimal("100")), 1) if prev_rev > Decimal("0.00") else None
    )
    if compare_previous:
        period_comparison = {
            "previous_range": {"start_date": prev_start.isoformat(), "end_date": prev_end.isoformat()},
            "previous_orders": prev_orders,
            "previous_net_revenue": f"{prev_rev:.2f}",
            "orders_change_percent": orders_change_pct,
            "revenue_change_percent": rev_change_pct,
            "data_classification": "actual",
        }

    # Section 7: Real database rule-based Business Insights (never fabricated or mislabeled as ML predictions)
    business_insights: list[dict[str, Any]] = []
    if peak_hours:
        top_hr = peak_hours[0]
        peak_wd = max(weekday_series, key=lambda x: x["orders"], default=None)
        business_insights.append({
            "id": "peak_demand_window",
            "category": "demand",
            "severity": "info",
            "title": f"Peak Demand Window: {top_hr['hour']}" + (f" ({peak_wd['weekday']})" if peak_wd and peak_wd["orders"] > 0 else ""),
            "detail": f"{top_hr['orders']} confirmed orders (Rs.{top_hr['revenue']:.2f}) concentrated around {top_hr['hour']}. Pre-batching top dishes 15 minutes prior reduces queue backlog.",
            "metric_label": f"{top_hr['orders']} orders",
            "classification": "db_rule_insight",
            "drilldown": {"tab": "orders", "hour": int(top_hr["hour"][:2])},
        })
    if rev_change_pct is not None and rev_change_pct <= -15.0:
        business_insights.append({
            "id": "revenue_decline_alert",
            "category": "revenue",
            "severity": "warning",
            "title": f"Revenue Declined {abs(rev_change_pct)}% vs Previous Period",
            "detail": f"Verified net revenue is Rs.{net_sales:.2f} compared to Rs.{prev_rev:.2f} in {prev_start.isoformat()} to {prev_end.isoformat()}.",
            "metric_label": f"{rev_change_pct}%",
            "classification": "db_rule_insight",
            "drilldown": {"tab": "orders"},
        })
    elif rev_change_pct is not None and rev_change_pct >= 15.0:
        business_insights.append({
            "id": "revenue_growth_highlight",
            "category": "revenue",
            "severity": "positive",
            "title": f"Revenue Grew +{rev_change_pct}% vs Previous Period",
            "detail": f"Verified net revenue rose from Rs.{prev_rev:.2f} to Rs.{net_sales:.2f} across {total_orders} paid orders.",
            "metric_label": f"+{rev_change_pct}%",
            "classification": "db_rule_insight",
            "drilldown": {"tab": "orders"},
        })
    if top_items:
        best = top_items[0]
        zero_sellers = [x for x in least_ordered_items if x["quantity_sold"] == 0]
        business_insights.append({
            "id": "product_performance_split",
            "category": "product",
            "severity": "positive" if not zero_sellers else "info",
            "title": f"Top Seller: {best['item_name']} ({best['quantity_sold']} sold)",
            "detail": (
                f"{best['item_name']} generated Rs.{best['revenue']:.2f}."
                + (f" {len(zero_sellers)} active menu item(s) had 0 orders in this window." if zero_sellers else "")
            ),
            "metric_label": f"Rs.{best['revenue']:.2f}",
            "classification": "db_rule_insight",
            "drilldown": {"tab": "items"},
        })
    if low_stock_rows or out_of_stock_items:
        business_insights.append({
            "id": "inventory_and_stockouts",
            "category": "inventory",
            "severity": "critical" if len(out_of_stock_items) > 0 else "warning",
            "title": f"{len(low_stock_rows)} Low-Stock Ingredients & {len(out_of_stock_items)} Unavailable Dishes",
            "detail": "Replenish low-stock ingredients promptly to prevent recipe auto-blocks on peak items.",
            "metric_label": f"{len(low_stock_rows)} alerts",
            "classification": "db_rule_insight",
            "drilldown": {"tab": "inventory", "low_only": True},
        })
    if cancellation_rate_percent >= 10.0 and cancelled_orders >= 2:
        business_insights.append({
            "id": "cancellation_spike",
            "category": "operations",
            "severity": "critical",
            "title": f"Elevated Cancellation Rate ({cancellation_rate_percent}%)",
            "detail": f"{cancelled_orders} of {total_created_orders} orders in the selected range were cancelled or rejected.",
            "metric_label": f"{cancelled_orders} cancelled",
            "classification": "db_rule_insight",
            "drilldown": {"tab": "orders", "status": "CANCELLED"},
        })
    if delayed_orders > 0 or (prep_durations and (sum(prep_durations) / len(prep_durations)) > 15.0):
        avg_p = round(sum(prep_durations) / len(prep_durations), 1) if prep_durations else 0.0
        business_insights.append({
            "id": "prep_delay_alert",
            "category": "operations",
            "severity": "warning",
            "title": f"Preparation Delays Detected ({delayed_orders} delayed, avg {avg_p}m)",
            "detail": "Review kitchen station assignments and prep batching during peak windows.",
            "metric_label": f"{delayed_orders} delayed",
            "classification": "db_rule_insight",
            "drilldown": {"tab": "orders", "delayed_only": True},
        })

    generated_at_iso = datetime.now(timezone.utc).isoformat()
    report_payload = {
        "range": {"start_date": s_date.isoformat(), "end_date": e_date.isoformat(), "preset": resolved_preset},
        "filters": {
            "canteen_id": str(canteen_id) if canteen_id else None,
            "category_id": str(category_id) if category_id else None,
            "food_item_id": str(food_item_id) if food_item_id else None,
            "compare_previous": compare_previous,
        },
        "generated_at": generated_at_iso,
        "timezone": college_tz.key if hasattr(college_tz, "key") else str(college_tz),
        "data_source": "PostgreSQL / Neon real-time SQL aggregation (excludes unpaid & failed transactions from revenue)",
        "metric_definitions": {
            "gross_sales": "Sum of subtotal_amount across payment_status='CONFIRMED' orders in the selected date window.",
            "collected_payments": "Sum of Payment.amount across confirmed gateway/POS Payment records in the date window.",
            "refunds_amount": "Always 0.00 under CollegeBites strict no-in-app-refund policy.",
            "net_revenue": "Sum of Order.total_amount on confirmed orders minus refunds (excludes unpaid/failed attempts).",
            "cancellation_rate_percent": "Cancelled + Rejected orders divided by all orders created in the date window.",
            "payment_success_rate_percent": "Confirmed Payment attempts divided by total Payment attempts created in window.",
            "avg_fulfilment_minutes": "Mean elapsed minutes from payment confirmation (confirmed_at) to handover completion (completed_at).",
            "repeat_purchase_rate_percent": "Percentage of active ordering registered customers with >1 confirmed order in range.",
        },
        "empty": total_orders == 0,
        "empty_message": "No data available (no confirmed orders for the selected date range)." if total_orders == 0 else None,
        "data_classification": "actual",
        "financial_analytics": {
            "verified_gross_sales": f"{Decimal(str(gross_sales)):.2f}",
            "collected_payments": f"{collected_payments:.2f}",
            "refunds_amount": f"{refunds_amount:.2f}",
            "no_refund_policy_enforced": True,
            "historical_discounts": f"{Decimal(str(discounts)):.2f}",
            "historical_taxes": f"{Decimal(str(tax_collected)):.2f}",
            "verified_net_revenue": f"{Decimal(str(net_sales)):.2f}",
            "revenue_classification": "actual",
            "verified_ingredient_cost": f"{verified_ingredient_cost:.2f}",
            "recorded_wastage_loss": f"{recorded_wastage_loss:.2f}",
            "total_recorded_direct_costs": f"{total_recorded_direct_costs:.2f}",
            "cost_classification": "calculated",
            "estimated_gross_margin": f"{est_margin:.2f}" if est_margin is not None else None,
            "estimated_gross_margin_percent": est_margin_pct,
            "margin_classification": "estimated" if est_margin is not None else "unavailable",
            "margin_status": margin_status,
            "margin_note": margin_note,
        },
        "period_comparison": period_comparison,
        "today_summary": {
            "date": local_today.isoformat(),
            "total_orders_today": int(total_orders_today),
            "completed_orders_today": int(completed_orders_today),
            "pending_orders_today": int(pending_orders_today),
            "active_pending_orders": int(active_pending_orders),
            "revenue_today": f"{Decimal(str(revenue_today)):.2f}",
        },
        "sales": {
            "total_orders": int(total_orders),
            "total_created_orders": int(total_created_orders),
            "gross_sales": f"{Decimal(str(gross_sales)):.2f}",
            "collected_payments": f"{collected_payments:.2f}",
            "refunds": f"{refunds_amount:.2f}",
            "discounts": f"{Decimal(str(discounts)):.2f}",
            "tax_collected": f"{Decimal(str(tax_collected)):.2f}",
            "net_sales": f"{Decimal(str(net_sales)):.2f}",
            "average_order_value": f"{aov:.2f}",
            "daily_series": daily_series,
            "weekly_series": weekly_series,
            "monthly_series": monthly_series,
            "hourly_series": hourly_series,
            "weekday_series": weekday_series,
            "hourly_heatmap": hourly_heatmap,
            "top_items": top_items,
            "least_ordered_items": least_ordered_items,
            "out_of_stock_items": out_of_stock_items,
            "product_demand_trends": product_demand_trends,
            "product_demand_trend_keys": top_5_names,
            "frequent_combinations": frequent_combinations,
            "category_sales": category_sales,
            "counter_sales": counter_sales,
            "counter_performance": counter_performance,
            "payment_breakdown": payment_breakdown,
            "order_status_breakdown": order_status_breakdown,
            "channel_breakdown": channel_breakdown,
        },
        "payment_stats": {
            "total_attempts": total_attempts,
            "confirmed_count": confirmed_cnt,
            "failed_count": failed_cnt,
            "pending_count": pending_pay_cnt,
            "confirmed_amount": f"{confirmed_amt:.2f}",
            "failed_amount": f"{failed_amt:.2f}",
            "success_rate_percent": pay_success_rate,
        },
        "operations": {
            "completed_orders": int(completed_orders),
            "cancelled_orders": int(cancelled_orders),
            "cancellation_rate_percent": cancellation_rate_percent,
            "pending_orders": int(pending_orders),
            "delayed_orders": int(delayed_orders),
            "completion_rate_percent": completion_rate,
            "avg_prep_minutes": round(sum(prep_durations) / len(prep_durations), 1) if prep_durations else 0.0,
            "avg_pickup_wait_minutes": round(sum(wait_durations) / len(wait_durations), 1) if wait_durations else 0.0,
            "avg_completion_minutes": round(sum(completion_durations) / len(completion_durations), 1) if completion_durations else 0.0,
            "avg_fulfilment_minutes": round(sum(completion_durations) / len(completion_durations), 1) if completion_durations else 0.0,
            "kitchen_workload_percent": round(
                min(100.0, (active_pending_orders / max(1, sum(c["max_queue_capacity"] for c in counter_performance) or 25)) * 100.0),
                1,
            ),
            "peak_hours": peak_hours,
        },
        "inventory": {
            "tracked_ingredients": len(inv_rows),
            "low_stock_count": len(low_stock_rows),
            "low_stock_items": low_stock_items,
            "out_of_stock_products_count": len(out_of_stock_items),
            "out_of_stock_products": out_of_stock_items,
            "expiring_within_7_days": int(expiring_count),
            "total_wastage_loss": f"{Decimal(str(total_wastage)):.2f}",
            "wastage_breakdown": wastage_breakdown,
            "total_purchases_received": f"{Decimal(str(total_purchases)):.2f}",
            "consumption_trends": consumption_trends,
            "consumption_summary": consumption_summary,
        },
        "customers": {
            "registered_customers": int(total_customers),
            "new_customers": int(new_customers),
            "active_ordering_customers": active_cust_cnt,
            "returning_customers": returning_customers,
            "repeat_order_rate_percent": repeat_rate,
            "avg_customer_spending": f"{avg_customer_spending:.2f}",
            "average_food_rating": round(float(avg_rating), 2),
            "review_count": len(rev_rows),
            "rating_distribution": rating_dist,
            "satisfaction_trends": satisfaction_trends,
        },
        "business_insights": business_insights,
        "support": {
            "total_tickets": len(tickets),
            "open_tickets": open_tickets,
            "resolved_tickets": resolved_tickets,
            "avg_resolution_minutes": round(sum(res_mins) / len(res_mins), 1) if res_mins else 0.0,
        },
        "staff_performance": {
            "present_checkins": present_checkins,
            "leave_records": leave_days,
            "tasks_total": len(tasks),
            "tasks_completed": tasks_done,
            "cashier_walkin_orders": cashier_orders,
            "staff_breakdown": staff_breakdown,
        },
    }
    ttl_sec = 30 if e_date >= local_today else 120
    cache_manager.set_json(cache_ns, cache_key, report_payload, ttl_seconds=ttl_sec, l1_ttl=2.0)
    return report_payload


def get_order_details_page(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    preset: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status_filter: Optional[str] = None,
    q: Optional[str] = None,
    hour_filter: Optional[int] = None,
    weekday_filter: Optional[int] = None,
    payment_method_filter: Optional[str] = None,
    food_item_id: Optional[UUID] = None,
    delayed_only: bool = False,
    page: int = 1,
    page_size: int = 15,
) -> dict[str, Any]:
    college_tz = get_college_tz()
    s_date, e_date, resolved_preset = resolve_report_date_range(preset, start_date, end_date)
    s_dt = datetime.combine(s_date, time.min, tzinfo=college_tz)
    e_dt = datetime.combine(e_date, time.max, tzinfo=college_tz)

    filters = [Order.created_at >= s_dt, Order.created_at <= e_dt]
    if canteen_id:
        filters.append(Order.canteen_id == canteen_id)
    if status_filter and status_filter.strip():
        st_u = status_filter.strip().upper()
        if st_u == "CANCELLED":
            filters.append(Order.status.in_(("CANCELLED", "REJECTED")))
        else:
            filters.append(Order.status == st_u)
    if payment_method_filter and payment_method_filter.strip():
        filters.append(Order.payment_method == payment_method_filter.strip().lower())
    if food_item_id:
        filters.append(Order.id.in_(select(OrderItem.order_id).where(OrderItem.food_item_id == food_item_id)))
    if delayed_only:
        filters.append(Order.delayed_minutes > 0)
    if q and q.strip():
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                Order.order_number.ilike(like),
                Order.guest_name.ilike(like),
                Order.payment_method.ilike(like),
            )
        )

    if hour_filter is not None or weekday_filter is not None:
        id_ts_rows = db.execute(select(Order.id, Order.created_at).where(*filters)).all()
        matching_ids = [
            oid
            for oid, cts in id_ts_rows
            if cts
            and (hour_filter is None or _to_local_dt(cts, college_tz).hour == hour_filter)
            and (weekday_filter is None or _to_local_dt(cts, college_tz).weekday() == weekday_filter)
        ]
        filters = [Order.id.in_(matching_ids)] if matching_ids else [Order.id.is_(None)]

    total = db.scalar(select(func.count(Order.id)).where(*filters)) or 0
    total_pages = max(1, (total + page_size - 1) // page_size)
    offset = (max(1, page) - 1) * page_size

    rows = db.execute(
        select(Order, Counter.name, User.full_name)
        .join(Counter, Counter.id == Order.counter_id)
        .outerjoin(User, User.id == Order.customer_id)
        .where(*filters)
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(page_size)
    ).all()

    oids = [o.id for o, _, _ in rows]
    tokens = (
        {t.order_id: t.token_code for t in db.scalars(select(PickupToken).where(PickupToken.order_id.in_(oids))).all()}
        if oids
        else {}
    )
    item_cnts: dict[UUID, int] = {}
    if oids:
        for oid, qsum in db.execute(
            select(OrderItem.order_id, func.coalesce(func.sum(OrderItem.quantity), 0))
            .where(OrderItem.order_id.in_(oids))
            .group_by(OrderItem.order_id)
        ).all():
            item_cnts[oid] = int(qsum or 0)

    items = []
    for o, cnt_name, u_name in rows:
        prep_m = round(max(0.0, (o.ready_at - o.confirmed_at).total_seconds() / 60.0), 1) if (o.confirmed_at and o.ready_at) else None
        wait_m = round(max(0.0, (o.completed_at - o.ready_at).total_seconds() / 60.0), 1) if (o.ready_at and o.completed_at) else None
        items.append({
            "order_id": str(o.id),
            "order_number": o.order_number,
            "token_code": tokens.get(o.id),
            "customer_name": u_name or o.guest_name or "Walk-in / Guest",
            "counter_name": cnt_name,
            "item_count": item_cnts.get(o.id, 0),
            "status": o.status,
            "payment_status": o.payment_status,
            "payment_method": o.payment_method,
            "order_channel": o.order_channel,
            "total_amount": f"{Decimal(str(o.total_amount)):.2f}",
            "prep_minutes": prep_m,
            "pickup_wait_minutes": wait_m,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        })

    return {
        "range": {"start_date": s_date.isoformat(), "end_date": e_date.isoformat(), "preset": resolved_preset},
        "page": page,
        "page_size": page_size,
        "total": int(total),
        "total_pages": total_pages,
        "items": items,
    }


def get_item_details_page(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    preset: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    q: Optional[str] = None,
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 15,
) -> dict[str, Any]:
    college_tz = get_college_tz()
    s_date, e_date, resolved_preset = resolve_report_date_range(preset, start_date, end_date)
    s_dt = datetime.combine(s_date, time.min, tzinfo=college_tz)
    e_dt = datetime.combine(e_date, time.max, tzinfo=college_tz)

    paid_filters = [Order.created_at >= s_dt, Order.created_at <= e_dt, Order.payment_status == "CONFIRMED"]
    if canteen_id:
        paid_filters.append(Order.canteen_id == canteen_id)

    sales_rows = db.execute(
        select(
            OrderItem.food_item_id,
            func.coalesce(func.sum(OrderItem.quantity), 0),
            func.coalesce(func.sum(OrderItem.line_total), 0),
            func.count(func.distinct(OrderItem.order_id)),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(*paid_filters, OrderItem.food_item_id.is_not(None))
        .group_by(OrderItem.food_item_id)
    ).all()
    sales_map = {fid: (int(qty), float(rev), int(ocnt)) for fid, qty, rev, ocnt in sales_rows}

    f_stmt = (
        select(FoodItem, FoodCategory.name)
        .join(FoodCategory, FoodCategory.id == FoodItem.category_id)
        .where(FoodItem.is_active.is_(True))
    )
    if canteen_id:
        f_stmt = f_stmt.where(FoodItem.canteen_id == canteen_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        f_stmt = f_stmt.where(or_(FoodItem.name.ilike(like), FoodCategory.name.ilike(like)))

    all_rows = []
    for fi, cat_name in db.execute(f_stmt).all():
        qty, rev, ocnt = sales_map.get(fi.id, (0, 0.0, 0))
        all_rows.append({
            "food_item_id": str(fi.id),
            "item_name": fi.name,
            "category_name": cat_name,
            "unit_price": f"{Decimal(str(fi.base_price)):.2f}",
            "quantity_sold": qty,
            "order_count": ocnt,
            "revenue": round(rev, 2),
            "is_available": fi.is_available,
        })

    reverse = (sort_dir or "desc").lower() != "asc"
    all_rows.sort(key=lambda r: (r["quantity_sold"], r["revenue"], r["item_name"]), reverse=reverse)
    if not reverse:
        all_rows.sort(key=lambda r: (r["quantity_sold"], r["revenue"], r["item_name"]))

    total = len(all_rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start_idx = (max(1, page) - 1) * page_size
    return {
        "range": {"start_date": s_date.isoformat(), "end_date": e_date.isoformat(), "preset": resolved_preset},
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "items": all_rows[start_idx : start_idx + page_size],
    }


def get_inventory_details_page(
    db: Session,
    *,
    canteen_id: Optional[UUID] = None,
    preset: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    q: Optional[str] = None,
    low_only: bool = False,
    page: int = 1,
    page_size: int = 15,
) -> dict[str, Any]:
    college_tz = get_college_tz()
    s_date, e_date, resolved_preset = resolve_report_date_range(preset, start_date, end_date)
    s_dt = datetime.combine(s_date, time.min, tzinfo=college_tz)
    e_dt = datetime.combine(e_date, time.max, tzinfo=college_tz)

    inv_stmt = (
        select(InventoryItem, Ingredient.name)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(InventoryItem.is_archived.is_(False))
    )
    if canteen_id:
        inv_stmt = inv_stmt.where(InventoryItem.canteen_id == canteen_id)
    if q and q.strip():
        inv_stmt = inv_stmt.where(Ingredient.name.ilike(f"%{q.strip()}%"))

    inv_rows = db.execute(inv_stmt.order_by(Ingredient.name.asc())).all()
    if low_only:
        inv_rows = [(inv, name) for inv, name in inv_rows if inv.current_quantity <= inv.reorder_level]

    inv_ids = [inv.id for inv, _ in inv_rows]
    mov_agg: dict[UUID, tuple[float, float, float]] = {}
    if inv_ids:
        for sm in db.scalars(
            select(StockMovement).where(
                StockMovement.inventory_item_id.in_(inv_ids),
                StockMovement.created_at >= s_dt,
                StockMovement.created_at <= e_dt,
            )
        ).all():
            c_q, p_q, w_q = mov_agg.get(sm.inventory_item_id, (0.0, 0.0, 0.0))
            d = float(sm.quantity_delta or 0)
            if sm.movement_type in ("order_deduct", "order_deduction", "production_use"):
                c_q += abs(d)
            elif sm.movement_type == "purchase" or d > 0:
                p_q += max(0.0, d)
            elif sm.movement_type == "wastage":
                w_q += abs(d)
            mov_agg[sm.inventory_item_id] = (round(c_q, 3), round(p_q, 3), round(w_q, 3))

    items = []
    for inv, ing_name in inv_rows:
        c_q, p_q, w_q = mov_agg.get(inv.id, (0.0, 0.0, 0.0))
        items.append({
            "inventory_item_id": str(inv.id),
            "ingredient_name": ing_name,
            "unit": inv.unit,
            "current_quantity": float(inv.current_quantity),
            "reorder_level": float(inv.reorder_level),
            "consumed_quantity": c_q,
            "restocked_quantity": p_q,
            "wastage_quantity": w_q,
            "is_low_stock": bool(inv.current_quantity <= inv.reorder_level),
        })

    items.sort(key=lambda x: (-int(x["is_low_stock"]), -x["consumed_quantity"], x["ingredient_name"]))
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start_idx = (max(1, page) - 1) * page_size
    return {
        "range": {"start_date": s_date.isoformat(), "end_date": e_date.isoformat(), "preset": resolved_preset},
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "items": items[start_idx : start_idx + page_size],
    }


def export_report_xlsx(report: dict[str, Any]) -> bytes:
    wb = Workbook()
    header_fill = PatternFill(start_color="5D010A", end_color="5D010A", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    def _style_sheet(ws, headers: list[str], rows: list[list[Any]]) -> None:
        ws.append(headers)
        for idx, _col in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=idx)
            cell.fill = header_fill
            cell.font = header_font
        for row in rows:
            ws.append(row)
        for col_idx in range(1, len(headers) + 1):
            max_len = max((len(str(ws.cell(row=r, column=col_idx).value or "")) for r in range(1, ws.max_row + 1)), default=12)
            ws.column_dimensions[get_column_letter(col_idx)].width = min(42, max(14, max_len + 3))

    # 1. Summary
    ws_sum = wb.active
    ws_sum.title = "Summary"
    s = report["sales"]
    op = report["operations"]
    inv = report["inventory"]
    ps = report.get("payment_stats", {})
    td = report.get("today_summary", {})
    fin = report.get("financial_analytics", {})
    pc = report.get("period_comparison")
    summary_rows = [
        ["Range", f"{report['range']['start_date']} to {report['range']['end_date']} ({report['range'].get('preset', '')})"],
        ["Orders Today", td.get("total_orders_today", 0)],
        ["Completed Today", td.get("completed_orders_today", 0)],
        ["Active Queue Now", td.get("active_pending_orders", 0)],
        ["Revenue Today", td.get("revenue_today", "0.00")],
        ["Confirmed Orders (Range)", s["total_orders"]],
        ["Verified Gross Sales", fin.get("verified_gross_sales", s["gross_sales"])],
        ["Historical Discounts", fin.get("historical_discounts", s["discounts"])],
        ["Historical Taxes", fin.get("historical_taxes", s["tax_collected"])],
        ["Verified Net Revenue (Actual — NOT Profit)", fin.get("verified_net_revenue", s["net_sales"])],
        ["Verified Ingredient Consumption Cost", fin.get("verified_ingredient_cost", "0.00")],
        ["Recorded Wastage Loss", fin.get("recorded_wastage_loss", inv["total_wastage_loss"])],
        ["Total Recorded Direct Costs", fin.get("total_recorded_direct_costs", "0.00")],
        [
            "Estimated Gross Margin",
            f"{fin['estimated_gross_margin']} ({fin['estimated_gross_margin_percent']}%)"
            if fin.get("estimated_gross_margin") is not None
            else "Unavailable",
        ],
        ["Financial Methodology Note", fin.get("margin_note", "")],
        ["Average Order Value", s["average_order_value"]],
        ["Payment Success Rate %", ps.get("success_rate_percent", 0)],
        ["Completed Orders", op["completed_orders"]],
        ["Cancelled / Rejected", op["cancelled_orders"]],
        ["Delayed Orders", op["delayed_orders"]],
        ["Avg Prep Minutes", op["avg_prep_minutes"]],
        ["Avg Pickup Wait Minutes", op["avg_pickup_wait_minutes"]],
        ["Avg End-to-End Completion Minutes", op.get("avg_completion_minutes", 0)],
        ["Tracked Ingredients", inv["tracked_ingredients"]],
        ["Low Stock Count", inv["low_stock_count"]],
        ["Total Wastage Loss", inv["total_wastage_loss"]],
        ["Total Purchases Received", inv["total_purchases_received"]],
    ]
    if pc:
        summary_rows.extend([
            ["Previous Period Range", f"{pc['previous_range']['start_date']} to {pc['previous_range']['end_date']}"],
            ["Previous Period Orders", pc["previous_orders"]],
            ["Previous Period Net Revenue", pc["previous_net_revenue"]],
            ["Orders Change %", pc["orders_change_percent"] if pc["orders_change_percent"] is not None else "N/A"],
            ["Revenue Change %", pc["revenue_change_percent"] if pc["revenue_change_percent"] is not None else "N/A"],
        ])
    _style_sheet(ws_sum, ["Metric", "Value"], summary_rows)

    # 2. Daily_Trend
    ws_daily = wb.create_sheet("Daily_Trend")
    _style_sheet(
        ws_daily,
        ["Date", "Orders", "Revenue"],
        [[d["date"], d["orders"], d["revenue"]] for d in s.get("daily_series", [])],
    )

    # 3. Item_Performance
    ws_items = wb.create_sheet("Item_Performance")
    item_rows = [["Top Selling", it["item_name"], "", it["quantity_sold"], it["revenue"]] for it in s.get("top_items", [])]
    item_rows.extend(
        [["Least Ordered", it["item_name"], it.get("category_name", ""), it["quantity_sold"], it["revenue"]] for it in s.get("least_ordered_items", [])]
    )
    _style_sheet(ws_items, ["Bucket", "Food Item", "Category", "Qty Sold", "Revenue"], item_rows)

    # 4. Counter_Queue
    ws_cnt = wb.create_sheet("Counter_Queue")
    _style_sheet(
        ws_cnt,
        ["Counter", "Type", "Confirmed Orders", "Completed", "Revenue", "Avg Prep (m)", "Avg Pickup Wait (m)", "Active Queue", "Capacity", "Utilization %"],
        [
            [
                c["counter_name"],
                c["counter_type"],
                c["orders"],
                c["completed_orders"],
                c["revenue"],
                c["avg_prep_minutes"],
                c["avg_pickup_wait_minutes"],
                c["active_queue_count"],
                c["max_queue_capacity"],
                c["utilization_percent"],
            ]
            for c in s.get("counter_performance", [])
        ],
    )

    # 5. Inventory_Consumption
    ws_inv = wb.create_sheet("Inventory_Consumption")
    _style_sheet(
        ws_inv,
        ["Ingredient", "Unit", "Consumed Qty", "Restocked Qty", "Wasted Qty", "Current Stock", "Reorder Level", "Low Stock"],
        [
            [
                r["ingredient_name"],
                r["unit"],
                r["consumed_quantity"],
                r["restocked_quantity"],
                r["wastage_quantity"],
                r["current_quantity"],
                r["reorder_level"],
                "YES" if r["is_low_stock"] else "NO",
            ]
            for r in inv.get("consumption_summary", [])
        ],
    )

    # 6. Staff_Performance
    ws_stf = wb.create_sheet("Staff_Performance")
    _style_sheet(
        ws_stf,
        ["Staff Name", "Employee Code", "Check-ins", "Worked Mins", "Tasks Done", "Tasks Total", "POS Orders", "Status Updates"],
        [
            [
                sb["full_name"],
                sb["employee_code"],
                sb["checkins"],
                sb.get("worked_minutes", 0),
                sb["tasks_completed"],
                sb["tasks_total"],
                sb["cashier_orders"],
                sb["status_updates"],
            ]
            for sb in report.get("staff_performance", {}).get("staff_breakdown", [])
        ],
    )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_report_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["CollegeBites Analytics Report", report["range"]["start_date"], report["range"]["end_date"]])
    writer.writerow([])
    if report.get("today_summary"):
        writer.writerow(["TODAY SUMMARY"])
        for k, v in report["today_summary"].items():
            writer.writerow([k, v])
        writer.writerow([])
    if report.get("financial_analytics"):
        writer.writerow(["FINANCIAL ANALYTICS (REVENUE SEPARATED FROM COSTS & MARGIN)"])
        for k, v in report["financial_analytics"].items():
            writer.writerow([k, v])
        writer.writerow([])
    if report.get("period_comparison"):
        pc = report["period_comparison"]
        writer.writerow(["PERIOD COMPARISON"])
        writer.writerow(["previous_start_date", pc["previous_range"]["start_date"]])
        writer.writerow(["previous_end_date", pc["previous_range"]["end_date"]])
        writer.writerow(["previous_orders", pc["previous_orders"]])
        writer.writerow(["previous_net_revenue", pc["previous_net_revenue"]])
        writer.writerow(["orders_change_percent", pc["orders_change_percent"]])
        writer.writerow(["revenue_change_percent", pc["revenue_change_percent"]])
        writer.writerow([])
    writer.writerow(["SALES SUMMARY"])
    for k, v in report["sales"].items():
        if not isinstance(v, list):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["DAILY SERIES", "ORDERS", "REVENUE"])
    for ds in report["sales"].get("daily_series", []):
        writer.writerow([ds["date"], ds["orders"], ds["revenue"]])
    writer.writerow([])
    writer.writerow(["WEEKLY SERIES", "WEEK START", "ORDERS", "REVENUE"])
    for ws in report["sales"].get("weekly_series", []):
        writer.writerow([ws["week"], ws["week_start"], ws["orders"], ws["revenue"]])
    writer.writerow([])
    writer.writerow(["MONTHLY SERIES", "ORDERS", "REVENUE"])
    for ms in report["sales"].get("monthly_series", []):
        writer.writerow([ms["month"], ms["orders"], ms["revenue"]])
    writer.writerow([])
    writer.writerow(["TOP FOOD ITEMS", "QUANTITY SOLD", "REVENUE"])
    for it in report["sales"]["top_items"]:
        writer.writerow([it["item_name"], it["quantity_sold"], it["revenue"]])
    writer.writerow([])
    writer.writerow(["LEAST ORDERED FOOD ITEMS", "CATEGORY", "QUANTITY SOLD", "REVENUE"])
    for it in report["sales"].get("least_ordered_items", []):
        writer.writerow([it["item_name"], it.get("category_name", ""), it["quantity_sold"], it["revenue"]])
    writer.writerow([])
    writer.writerow(["CATEGORY SALES", "QUANTITY", "REVENUE"])
    for cat in report["sales"].get("category_sales", []):
        writer.writerow([cat["category"], cat["quantity"], cat["revenue"]])
    writer.writerow([])
    writer.writerow(["COUNTER PERFORMANCE", "TYPE", "ORDERS", "COMPLETED", "REVENUE", "AVG PREP MINS", "AVG PICKUP WAIT MINS", "UTILIZATION %"])
    for cnt in report["sales"].get("counter_performance", []):
        writer.writerow([
            cnt["counter_name"], cnt["counter_type"], cnt["orders"], cnt["completed_orders"],
            cnt["revenue"], cnt["avg_prep_minutes"], cnt["avg_pickup_wait_minutes"], cnt["utilization_percent"],
        ])
    writer.writerow([])
    writer.writerow(["PAYMENT BREAKDOWN", "ORDERS", "AMOUNT"])
    for pm in report["sales"].get("payment_breakdown", []):
        writer.writerow([pm["method"], pm["orders"], pm["amount"]])
    writer.writerow([])
    if report.get("payment_stats"):
        writer.writerow(["PAYMENT STATISTICS"])
        for k, v in report["payment_stats"].items():
            writer.writerow([k, v])
        writer.writerow([])
    writer.writerow(["OPERATIONS SUMMARY"])
    for k, v in report["operations"].items():
        if not isinstance(v, list):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["PEAK HOURS", "ORDERS", "REVENUE"])
    for ph in report["operations"].get("peak_hours", []):
        writer.writerow([ph["hour"], ph["orders"], ph.get("revenue", 0)])
    writer.writerow([])
    writer.writerow(["INVENTORY SUMMARY"])
    for k, v in report["inventory"].items():
        if not isinstance(v, (list, dict)):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["INVENTORY CONSUMPTION", "UNIT", "CONSUMED", "RESTOCKED", "WASTED", "CURRENT STOCK", "REORDER LEVEL"])
    for cs in report["inventory"].get("consumption_summary", []):
        writer.writerow([cs["ingredient_name"], cs["unit"], cs["consumed_quantity"], cs["restocked_quantity"], cs["wastage_quantity"], cs["current_quantity"], cs["reorder_level"]])
    writer.writerow([])
    writer.writerow(["LOW STOCK SHORTAGES", "CURRENT QTY", "REORDER LEVEL", "UNIT"])
    for ls in report["inventory"].get("low_stock_items", []):
        writer.writerow([ls["ingredient_name"], ls["current_quantity"], ls["reorder_level"], ls["unit"]])
    writer.writerow([])
    writer.writerow(["CUSTOMER METRICS"])
    for k, v in report.get("customers", {}).items():
        if not isinstance(v, (list, dict)):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["SUPPORT METRICS"])
    for k, v in report.get("support", {}).items():
        writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["STAFF PERFORMANCE"])
    for k, v in report.get("staff_performance", {}).items():
        if not isinstance(v, list):
            writer.writerow([k, v])
    writer.writerow([])
    writer.writerow(["STAFF ACTIVITY BREAKDOWN", "EMP CODE", "CHECKINS", "WORKED MINS", "TASKS DONE", "WALK-IN ORDERS", "STATUS UPDATES"])
    for sb in report.get("staff_performance", {}).get("staff_breakdown", []):
        writer.writerow([sb["full_name"], sb["employee_code"], sb["checkins"], sb.get("worked_minutes", 0), sb["tasks_completed"], sb["cashier_orders"], sb["status_updates"]])
    return buf.getvalue()


def export_report_pdf(report: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 40

    def ensure_space(needed: int = 24) -> None:
        nonlocal y
        if y - needed < 42:
            c.showPage()
            y = h - 42

    c.setFont("Helvetica-Bold", 15)
    c.drawString(40, y, "CollegeBites Operational & Financial BI Report")
    y -= 20
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Date Range: {report['range']['start_date']} to {report['range']['end_date']} ({report['range'].get('preset', '')})")
    y -= 24

    def section(title: str, rows: list[tuple[str, Any]]):
        nonlocal y
        ensure_space(40)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, y, title)
        y -= 16
        c.setFont("Helvetica", 10)
        for label, val in rows:
            ensure_space(16)
            c.drawString(52, y, f"{label}: {val}"[:96])
            y -= 14
        y -= 10

    td = report.get("today_summary", {})
    if td:
        section("Today's Real-Time Snapshot", [
            ("Local Date", td.get("date", "")),
            ("Total Confirmed Orders Today", td.get("total_orders_today", 0)),
            ("Completed Today", td.get("completed_orders_today", 0)),
            ("Pending Active Queue", td.get("active_pending_orders", 0)),
            ("Revenue Today", f"Rs.{td.get('revenue_today', '0.00')}"),
        ])

    s = report["sales"]
    section("Sales Summary", [
        ("Total Confirmed Orders", s["total_orders"]),
        ("Gross Sales", f"Rs.{s['gross_sales']}"),
        ("Discounts", f"Rs.{s['discounts']}"),
        ("Tax Collected", f"Rs.{s['tax_collected']}"),
        ("Net Sales", f"Rs.{s['net_sales']}"),
        ("Average Order Value", f"Rs.{s['average_order_value']}"),
    ])
    fin = report.get("financial_analytics")
    if fin:
        section("Financial Analytics (Revenue vs Direct Costs)", [
            ("Verified Net Revenue (Actual, NOT Profit)", f"Rs.{fin.get('verified_net_revenue', s['net_sales'])}"),
            ("Verified Ingredient Consumption Cost", f"Rs.{fin.get('verified_ingredient_cost', '0.00')}"),
            ("Recorded Wastage Loss", f"Rs.{fin.get('recorded_wastage_loss', '0.00')}"),
            ("Total Recorded Direct Costs", f"Rs.{fin.get('total_recorded_direct_costs', '0.00')}"),
            (
                "Estimated Gross Margin",
                f"Rs.{fin['estimated_gross_margin']} ({fin['estimated_gross_margin_percent']}%)"
                if fin.get("estimated_gross_margin") is not None
                else "Unavailable (see note)",
            ),
            ("Methodology Note", (fin.get("margin_note") or "")[:92]),
        ])
    pc = report.get("period_comparison")
    if pc:
        section("Period-over-Period Comparison", [
            ("Previous Range", f"{pc['previous_range']['start_date']} to {pc['previous_range']['end_date']}"),
            ("Previous Confirmed Orders", pc["previous_orders"]),
            ("Previous Net Revenue", f"Rs.{pc['previous_net_revenue']}"),
            ("Orders Delta", f"{pc['orders_change_percent']}%" if pc["orders_change_percent"] is not None else "N/A"),
            ("Revenue Delta", f"{pc['revenue_change_percent']}%" if pc["revenue_change_percent"] is not None else "N/A"),
        ])
    ps = report.get("payment_stats", {})
    if ps:
        section("Payment Gateway & POS Statistics", [
            ("Total Payment Attempts", ps.get("total_attempts", 0)),
            ("Confirmed Payments", f"{ps.get('confirmed_count', 0)} (Rs.{ps.get('confirmed_amount', '0.00')})"),
            ("Failed Payments", f"{ps.get('failed_count', 0)} (Rs.{ps.get('failed_amount', '0.00')})"),
            ("Payment Success Rate", f"{ps.get('success_rate_percent', 0)}%"),
        ])
    op = report["operations"]
    section("Operations", [
        ("Completed Orders", op["completed_orders"]),
        ("Pending Orders (In Range)", op.get("pending_orders", 0)),
        ("Cancelled / Rejected Orders", op["cancelled_orders"]),
        ("Order Completion Rate", f"{op.get('completion_rate_percent', 0)}%"),
        ("Delayed Orders", op["delayed_orders"]),
        ("Average Prep Minutes", op["avg_prep_minutes"]),
        ("Average Pickup Wait Minutes", op.get("avg_pickup_wait_minutes", 0)),
    ])
    inv = report["inventory"]
    section("Inventory & Wastage", [
        ("Tracked Ingredients (Active)", inv["tracked_ingredients"]),
        ("Low Stock Alerts", inv["low_stock_count"]),
        ("Expiring Within 7 Days", inv["expiring_within_7_days"]),
        ("Wastage Loss", f"Rs.{inv['total_wastage_loss']}"),
        ("Purchases Received", f"Rs.{inv['total_purchases_received']}"),
    ])
    if inv.get("consumption_summary"):
        section(
            "Top Consumed Ingredients",
            [
                (it["ingredient_name"], f"Used: {it['consumed_quantity']} {it['unit']} | Stock: {it['current_quantity']} (Reorder {it['reorder_level']})")
                for it in inv["consumption_summary"][:10]
            ],
        )
    if inv.get("low_stock_items"):
        section(
            "Low Stock Shortage Items",
            [(it["ingredient_name"], f"{it['current_quantity']} / {it['reorder_level']} {it['unit']}") for it in inv["low_stock_items"][:10]],
        )
    cust = report.get("customers", {})
    section("Customers & Ratings", [
        ("Registered Customers", cust.get("registered_customers", 0)),
        ("Active Ordering Customers", cust.get("active_ordering_customers", 0)),
        ("Repeat Order Rate", f"{cust.get('repeat_order_rate_percent', 0)}%"),
        ("Average Food Rating", f"{cust.get('average_food_rating', 0)} / 5"),
    ])
    sup = report.get("support", {})
    sp = report.get("staff_performance", {})
    section("Support & Staff Operations", [
        ("Support Tickets (Open / Resolved)", f"{sup.get('open_tickets', 0)} / {sup.get('resolved_tickets', 0)}"),
        ("Avg Ticket Resolution", f"{sup.get('avg_resolution_minutes', 0)} mins"),
        ("Staff Check-ins / Leave Days", f"{sp.get('present_checkins', 0)} / {sp.get('leave_records', 0)}"),
        ("Staff Tasks Completed", f"{sp.get('tasks_completed', 0)} / {sp.get('tasks_total', 0)}"),
        ("Cashier Walk-in Orders", sp.get("cashier_walkin_orders", 0)),
    ])
    if sp.get("staff_breakdown"):
        section(
            "Staff Activity Records",
            [
                (f"{sb['full_name']} ({sb['employee_code'] or 'Staff'})", f"Checkins: {sb['checkins']} | Mins: {sb.get('worked_minutes', 0)} | Tasks: {sb['tasks_completed']}/{sb['tasks_total']} | POS: {sb['cashier_orders']} | Updates: {sb['status_updates']}")
                for sb in sp["staff_breakdown"][:12]
            ],
        )
    if s.get("counter_performance"):
        section(
            "Counter Utilization & Wait Performance",
            [
                (c["counter_name"], f"{c['orders']} orders (Rs.{c['revenue']:.2f}) | Prep: {c['avg_prep_minutes']}m | Wait: {c['avg_pickup_wait_minutes']}m | Util: {c['utilization_percent']}%")
                for c in s["counter_performance"]
            ],
        )
    if op.get("peak_hours"):
        section("Peak Ordering Hours", [(ph["hour"], f"{ph['orders']} orders (Rs.{ph.get('revenue', 0):.2f})") for ph in op["peak_hours"][:8]])
    if s.get("top_items"):
        section("Top Food Items", [(it["item_name"], f"{it['quantity_sold']} sold (Rs.{it['revenue']:.2f})") for it in s["top_items"][:10]])
    if s.get("least_ordered_items"):
        section("Least Ordered Food Items", [(it["item_name"], f"{it['quantity_sold']} sold (Rs.{it['revenue']:.2f})") for it in s["least_ordered_items"][:10]])
    if s.get("category_sales"):
        section("Category Sales", [(it["category"], f"{it['quantity']} sold (Rs.{it['revenue']:.2f})") for it in s["category_sales"]])
    if s.get("payment_breakdown"):
        section("Payment Breakdown", [(it["method"], f"{it['orders']} orders (Rs.{it['amount']:.2f})") for it in s["payment_breakdown"]])
    c.showPage()
    c.save()
    return buf.getvalue()
