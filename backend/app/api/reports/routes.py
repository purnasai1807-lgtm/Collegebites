from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import (
    ROLE_CANTEEN_MANAGER,
    ROLE_COLLEGE_ADMIN,
    ROLE_SUPER_ADMIN,
    AuthenticatedPrincipal,
    require_roles,
    scoped_canteen_for_principal,
)
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports & Analytics"])

REPORT_ROLES = (ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER)


@router.get("/dashboard")
def get_dashboard_report(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    category_id: Optional[UUID] = Query(default=None),
    food_item_id: Optional[UUID] = Query(default=None),
    compare_previous: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    return report_service.get_analytics_report(
        db,
        canteen_id=scoped_cid,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
        food_item_id=food_item_id,
        compare_previous=compare_previous,
    )


@router.get("/details/orders")
def get_report_orders_detail(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    hour: Optional[int] = Query(default=None, ge=0, le=23),
    weekday: Optional[int] = Query(default=None, ge=0, le=6),
    payment_method: Optional[str] = Query(default=None),
    food_item_id: Optional[UUID] = Query(default=None),
    delayed_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    return report_service.get_order_details_page(
        db,
        canteen_id=scoped_cid,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        status_filter=status,
        q=q,
        hour_filter=hour,
        weekday_filter=weekday,
        payment_method_filter=payment_method,
        food_item_id=food_item_id,
        delayed_only=delayed_only,
        page=page,
        page_size=page_size,
    )


@router.get("/details/items")
def get_report_items_detail(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    q: Optional[str] = Query(default=None),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    return report_service.get_item_details_page(
        db,
        canteen_id=scoped_cid,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        q=q,
        sort_dir=sort,
        page=page,
        page_size=page_size,
    )


@router.get("/details/inventory")
def get_report_inventory_detail(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    q: Optional[str] = Query(default=None),
    low_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=100),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    return report_service.get_inventory_details_page(
        db,
        canteen_id=scoped_cid,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        q=q,
        low_only=low_only,
        page=page,
        page_size=page_size,
    )


@router.get("/export/csv")
def export_csv(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    category_id: Optional[UUID] = Query(default=None),
    food_item_id: Optional[UUID] = Query(default=None),
    compare_previous: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    report = report_service.get_analytics_report(
        db,
        canteen_id=scoped_cid,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
        food_item_id=food_item_id,
        compare_previous=compare_previous,
    )
    csv_text = report_service.export_report_csv(report)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=collegebites-report.csv"},
    )


@router.get("/export/pdf")
def export_pdf(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    category_id: Optional[UUID] = Query(default=None),
    food_item_id: Optional[UUID] = Query(default=None),
    compare_previous: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    report = report_service.get_analytics_report(
        db,
        canteen_id=scoped_cid,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
        food_item_id=food_item_id,
        compare_previous=compare_previous,
    )
    pdf_bytes = report_service.export_report_pdf(report)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=collegebites-report.pdf"},
    )


@router.get("/export/xlsx")
def export_xlsx(
    canteen_id: Optional[UUID] = Query(default=None),
    preset: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    category_id: Optional[UUID] = Query(default=None),
    food_item_id: Optional[UUID] = Query(default=None),
    compare_previous: bool = Query(default=False),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    report = report_service.get_analytics_report(
        db,
        canteen_id=scoped_cid,
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
        food_item_id=food_item_id,
        compare_previous=compare_previous,
    )
    xlsx_bytes = report_service.export_report_xlsx(report)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=collegebites-bi-report.xlsx"},
    )


@router.get("/operations-control-center")
def get_operations_control_center(
    canteen_id: Optional[UUID] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    order_status: Optional[str] = Query(default=None),
    product_id: Optional[UUID] = Query(default=None),
    product_q: Optional[str] = Query(default=None),
    operational_category: str = Query(
        default="all",
        pattern="^(all|orders|meal_plans|inventory|procurement|events|support|sales)$",
    ),
    principal: AuthenticatedPrincipal = Depends(require_roles(*REPORT_ROLES)),
    db: Session = Depends(get_db),
):
    from datetime import datetime, time, timezone
    from decimal import Decimal
    from sqlalchemy import func, select
    from app.models.engagement import SupportTicket
    from app.models.event import CollegeEvent, EventBulkOrder
    from app.models.inventory import InventoryItem, PurchaseOrder
    from app.models.meal_plan import MealPlan, MealPlanRedemption, StudentMealSubscription
    from app.models.menu import FoodItem, Ingredient
    from app.models.order import Order, OrderItem
    from app.models.payment import Invoice, PickupToken
    from app.models.promotion import Coupon
    from app.services import inventory_service

    from app.core.cache import NS_REPORTS, cache_manager

    scoped_cid = scoped_canteen_for_principal(principal, canteen_id)
    cache_ns = f"{NS_REPORTS}:{scoped_cid}" if scoped_cid else NS_REPORTS
    cache_key = (
        f"occ:{scoped_cid or 'all'}:{start_date}:{end_date}:{order_status}:"
        f"{product_id}:{(product_q or '').strip().lower()}:{operational_category}"
    )
    hit, cached = cache_manager.get_json(cache_ns, cache_key, l1_ttl=2.0)
    if hit and isinstance(cached, dict):
        return cached

    # 1. Orders query with date, status, and product filters
    ord_stmt = select(Order).where(Order.payment_status == "CONFIRMED")
    if scoped_cid:
        ord_stmt = ord_stmt.where(Order.canteen_id == scoped_cid)
    if start_date:
        ord_stmt = ord_stmt.where(Order.created_at >= datetime.combine(start_date, time.min, tzinfo=timezone.utc))
    if end_date:
        ord_stmt = ord_stmt.where(Order.created_at <= datetime.combine(end_date, time.max, tzinfo=timezone.utc))
    if order_status and order_status != "all":
        ord_stmt = ord_stmt.where(Order.status == order_status.upper())

    if product_id or (product_q and product_q.strip()):
        oi_sub = select(OrderItem.order_id)
        if product_id:
            oi_sub = oi_sub.where(OrderItem.food_item_id == product_id)
        if product_q and product_q.strip():
            oi_sub = oi_sub.where(OrderItem.item_name.ilike(f"%{product_q.strip()}%"))
        ord_stmt = ord_stmt.where(Order.id.in_(oi_sub))

    orders = list(db.scalars(ord_stmt.order_by(Order.created_at.desc()).limit(250)).all())
    oids = [o.id for o in orders]
    tokens = (
        {t.order_id: t.token_code for t in db.scalars(select(PickupToken).where(PickupToken.order_id.in_(oids))).all()}
        if oids
        else {}
    )

    def _fmt_ord(o: Order) -> dict:
        return {
            "id": str(o.id),
            "order_number": o.order_number,
            "canteen_id": str(o.canteen_id),
            "order_type": o.order_type,
            "status": o.status,
            "payment_status": o.payment_status,
            "pickup_token_code": tokens.get(o.id),
            "total_amount": str(Decimal(str(o.total_amount)).quantize(Decimal("0.01"))),
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }

    pending_orders = [_fmt_ord(o) for o in orders if o.status in ("PLACED", "ACCEPTED")]
    preparing_orders = [_fmt_ord(o) for o in orders if o.status == "PREPARING"]
    ready_orders = [_fmt_ord(o) for o in orders if o.status == "READY"]
    completed_orders = [_fmt_ord(o) for o in orders if o.status == "COMPLETED"]
    current_orders = [_fmt_ord(o) for o in orders if o.status in ("PLACED", "ACCEPTED", "PREPARING", "READY")]

    # 2. Meal plans & redemptions
    mp_stmt = select(MealPlan).where(MealPlan.is_active.is_(True))
    sub_stmt = select(StudentMealSubscription).where(StudentMealSubscription.status == "active")
    red_stmt = select(MealPlanRedemption)
    if scoped_cid:
        mp_stmt = mp_stmt.where((MealPlan.canteen_id == scoped_cid) | (MealPlan.canteen_id.is_(None)))
        sub_stmt = sub_stmt.where(
            (StudentMealSubscription.canteen_id == scoped_cid) | (StudentMealSubscription.canteen_id.is_(None))
        )
        red_stmt = red_stmt.where(MealPlanRedemption.canteen_id == scoped_cid)
    active_plans = list(db.scalars(mp_stmt).all())
    active_subs = list(db.scalars(sub_stmt).all())
    recent_redemptions = list(db.scalars(red_stmt.order_by(MealPlanRedemption.redeemed_at.desc()).limit(50)).all())

    # 3. Inventory alerts & low-stock items
    inv_stmt = (
        select(InventoryItem, Ingredient)
        .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
        .where(
            InventoryItem.is_archived.is_(False),
            InventoryItem.current_quantity <= InventoryItem.reorder_level,
        )
    )
    if scoped_cid:
        inv_stmt = inv_stmt.where(InventoryItem.canteen_id == scoped_cid)
    low_stock_rows = db.execute(inv_stmt.order_by(InventoryItem.current_quantity.asc())).all()
    low_stock_items = [
        {
            "inventory_item_id": str(inv.id),
            "ingredient_id": str(ing.id),
            "name": ing.name,
            "sku": ing.sku,
            "current_quantity": str(inv.current_quantity),
            "reorder_level": str(inv.reorder_level),
            "unit": inv.unit,
            "is_out_of_stock": inv.current_quantity <= Decimal("0.000"),
        }
        for inv, ing in low_stock_rows
    ]
    blocked_food_stmt = select(FoodItem).where(FoodItem.insufficient_ingredients.is_(True), FoodItem.is_active.is_(True))
    if scoped_cid:
        blocked_food_stmt = blocked_food_stmt.where(FoodItem.canteen_id == scoped_cid)
    blocked_dishes = [{"id": str(f.id), "name": f.name} for f in db.scalars(blocked_food_stmt).all()]

    # 4. Pending Purchase Orders & Vendor Outstanding Balances
    po_stmt = select(PurchaseOrder).where(
        PurchaseOrder.status.in_(["pending_approval", "approved", "ordered", "partial", "partially_received"])
    )
    if scoped_cid:
        po_stmt = po_stmt.where(PurchaseOrder.canteen_id == scoped_cid)
    pending_pos = list(db.scalars(po_stmt.order_by(PurchaseOrder.created_at.desc()).limit(50)).all())
    suppliers_with_metrics = inventory_service.list_suppliers(db)
    vendors_with_balance = [
        {
            "supplier_id": s["id"],
            "supplier_name": s["name"],
            "total_billed_amount": s["total_billed_amount"],
            "total_paid_amount": s["total_paid_amount"],
            "outstanding_balance": s["outstanding_balance"],
            "pending_orders_count": s["pending_orders_count"],
        }
        for s in suppliers_with_metrics
        if Decimal(str(s.get("outstanding_balance") or "0.00")) > Decimal("0.00")
    ]
    total_vendor_outstanding = sum(
        (Decimal(str(v["outstanding_balance"])) for v in vendors_with_balance), Decimal("0.00")
    ).quantize(Decimal("0.01"))

    # 5. Event Bulk Orders
    ebo_stmt = select(EventBulkOrder)
    if scoped_cid:
        ebo_stmt = ebo_stmt.where(EventBulkOrder.canteen_id == scoped_cid)
    bulk_orders = list(db.scalars(ebo_stmt.order_by(EventBulkOrder.created_at.desc()).limit(50)).all())
    ev_ids = {b.event_id for b in bulk_orders}
    ev_map = (
        {e.id: e.name for e in db.scalars(select(CollegeEvent).where(CollegeEvent.id.in_(ev_ids))).all()}
        if ev_ids
        else {}
    )

    # 6. Support Tickets
    sup_stmt = select(SupportTicket)
    if scoped_cid:
        sup_stmt = sup_stmt.where(SupportTicket.canteen_id == scoped_cid)
    tickets = list(db.scalars(sup_stmt.order_by(SupportTicket.created_at.desc()).limit(50)).all())

    # 7. Sales & Operational Summaries
    orders_rev = sum((Decimal(str(o.total_amount)) for o in orders if o.status != "CANCELLED"), Decimal("0.00")).quantize(Decimal("0.01"))
    meal_rev = sum(
        (Decimal(str(s.total_amount)) for s in active_subs if s.payment_status == "CONFIRMED"), Decimal("0.00")
    ).quantize(Decimal("0.01"))
    event_rev = sum(
        (Decimal(str(b.total_amount)) for b in bulk_orders if b.payment_status == "CONFIRMED" and b.status not in ("rejected", "cancelled")),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))
    inv_cnt_stmt = select(func.count(Invoice.id))
    if scoped_cid:
        inv_cnt_stmt = inv_cnt_stmt.where((Invoice.canteen_id == scoped_cid) | (Invoice.canteen_id.is_(None)))
    invoices_count = db.scalar(inv_cnt_stmt) or 0
    active_coupons_count = db.scalar(select(func.count(Coupon.id)).where(Coupon.is_active.is_(True))) or 0

    occ_payload = {
        "filters_applied": {
            "canteen_id": str(scoped_cid) if scoped_cid else None,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "order_status": order_status,
            "product_id": str(product_id) if product_id else None,
            "product_q": product_q,
            "operational_category": operational_category,
        },
        "current_orders": current_orders,
        "pending_orders": pending_orders,
        "preparing_orders": preparing_orders,
        "ready_orders": ready_orders,
        "completed_orders": completed_orders,
        "active_meal_plans": {
            "plans_count": len(active_plans),
            "active_subscriptions_count": len(active_subs),
            "total_remaining_meals": sum(s.remaining_meals for s in active_subs),
            "plans": [
                {"id": str(p.id), "code": p.code, "name": p.name, "plan_type": p.plan_type, "price": str(p.price), "total_meals": p.total_meals}
                for p in active_plans
            ],
        },
        "meal_plan_redemptions": {
            "recent_count": len(recent_redemptions),
            "total_meals_redeemed_recent": sum(r.meals_deducted for r in recent_redemptions),
            "redemptions": [
                {
                    "id": str(r.id),
                    "redemption_number": r.redemption_number,
                    "meal_item_name": r.meal_item_name,
                    "meals_deducted": r.meals_deducted,
                    "remaining_meals_after": r.remaining_meals_after,
                    "redeemed_at": r.redeemed_at.isoformat() if r.redeemed_at else None,
                }
                for r in recent_redemptions[:20]
            ],
        },
        "inventory_alerts": {
            "low_stock_count": len(low_stock_items),
            "out_of_stock_count": sum(1 for i in low_stock_items if i["is_out_of_stock"]),
            "blocked_food_items_count": len(blocked_dishes),
            "blocked_food_items": blocked_dishes,
        },
        "low_stock_items": low_stock_items,
        "pending_purchase_orders": [
            {
                "id": str(p.id),
                "po_number": p.po_number,
                "status": p.status,
                "total_cost": str(Decimal(str(p.total_cost)).quantize(Decimal("0.01"))),
                "expected_delivery_date": p.expected_delivery_date.isoformat() if p.expected_delivery_date else None,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in pending_pos
        ],
        "vendor_outstanding_balances": {
            "total_outstanding_amount": str(total_vendor_outstanding),
            "vendors_with_balance_count": len(vendors_with_balance),
            "vendors": vendors_with_balance,
        },
        "event_bulk_orders": {
            "total_count": len(bulk_orders),
            "pending_approval_count": sum(1 for b in bulk_orders if b.status == "pending_approval"),
            "active_count": sum(1 for b in bulk_orders if b.status in ("approved", "preparing", "ready")),
            "completed_count": sum(1 for b in bulk_orders if b.status == "completed"),
            "orders": [
                {
                    "id": str(b.id),
                    "bulk_order_number": b.bulk_order_number,
                    "event_name": ev_map.get(b.event_id, "College Event"),
                    "status": b.status,
                    "payment_status": b.payment_status,
                    "total_quantity": b.total_quantity,
                    "total_amount": str(Decimal(str(b.total_amount)).quantize(Decimal("0.01"))),
                    "group_pickup_token": b.group_pickup_token,
                    "scheduled_pickup_at": b.scheduled_pickup_at.isoformat() if b.scheduled_pickup_at else None,
                }
                for b in bulk_orders[:25]
            ],
        },
        "support_tickets": {
            "total_count": len(tickets),
            "open_count": sum(1 for t in tickets if t.status == "open"),
            "in_progress_count": sum(1 for t in tickets if t.status in ("in_progress", "assigned")),
            "resolved_count": sum(1 for t in tickets if t.status == "resolved"),
            "closed_count": sum(1 for t in tickets if t.status == "closed"),
            "tickets": [
                {
                    "id": str(t.id),
                    "ticket_number": t.ticket_number,
                    "category": t.category,
                    "priority": t.priority,
                    "status": t.status,
                    "subject": t.subject,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tickets[:25]
            ],
        },
        "sales_and_operational_summaries": {
            "orders_revenue": str(orders_rev),
            "active_meal_plans_revenue": str(meal_rev),
            "event_bulk_orders_revenue": str(event_rev),
            "combined_verified_revenue": str((orders_rev + meal_rev + event_rev).quantize(Decimal("0.01"))),
            "total_orders_count": len(orders),
            "current_active_orders_count": len(current_orders),
            "pending_orders_count": len(pending_orders),
            "preparing_orders_count": len(preparing_orders),
            "ready_orders_count": len(ready_orders),
            "completed_orders_count": len(completed_orders),
            "invoices_issued_count": int(invoices_count),
            "active_promotional_campaigns_count": int(active_coupons_count),
        },
    }
    if operational_category != "all":
        section_map = {
            "orders": {
                "current_orders": current_orders,
                "pending_orders": pending_orders,
                "preparing_orders": preparing_orders,
                "ready_orders": ready_orders,
                "completed_orders": completed_orders,
            },
            "meal_plans": {
                "active_meal_plans": occ_payload["active_meal_plans"],
                "meal_plan_redemptions": occ_payload["meal_plan_redemptions"],
            },
            "inventory": {
                "inventory_alerts": occ_payload["inventory_alerts"],
                "low_stock_items": low_stock_items,
            },
            "procurement": {
                "pending_purchase_orders": occ_payload["pending_purchase_orders"],
                "vendor_outstanding_balances": occ_payload["vendor_outstanding_balances"],
            },
            "events": {"event_bulk_orders": occ_payload["event_bulk_orders"]},
            "support": {"support_tickets": occ_payload["support_tickets"]},
            "sales": {"sales_and_operational_summaries": occ_payload["sales_and_operational_summaries"]},
        }
        occ_payload["selected_category_data"] = section_map.get(operational_category, {})
    cache_manager.set_json(cache_ns, cache_key, occ_payload, ttl_seconds=10, l1_ttl=2.0)
    return occ_payload

