import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import settings
from app.core.redis_client import safe_redis
from app.core.security import generate_guest_access_token, mask_mobile, sha256_hex
from app.core.time_utils import get_college_tz, now_college, today_college
from app.integrations.razorpay_client import razorpay_gateway
from app.models.college import Canteen, Counter, DiningTable, Kitchen, LocationQRCode
from app.models.inventory import InventoryItem
from app.models.menu import FoodAddon, FoodCategory, FoodItem, FoodItemAddon, FoodVariant, Recipe, RecipeIngredient
from app.models.order import (
    Cart,
    Order,
    OrderCancellation,
    OrderItem,
    OrderItemCustomization,
    OrderStatusHistory,
    PickupSlot,
    SlotReservation,
)
from app.models.payment import OrderQRCode, Payment, PaymentTransaction, PickupToken
from app.models.promotion import Coupon, CouponRedemption, LoyaltyAccount, LoyaltyTransaction
from app.schemas.order import CheckoutItemDirectIn, CheckoutRequest, OrderItemOut, OrderOut, PickupSlotOut
from app.services.audit_service import record_audit_log
from app.services.cart_service import evaluate_coupon_discount, get_active_cart
from app.services.college_service import compute_canteen_live_status, get_college_config_snapshot, get_or_create_college_settings
from app.services.menu_service import compute_schedule_availability_map
from app.websockets import emit_order_event_sync

_LAST_SLOT_CLEANUP_MONOTONIC: float = 0.0

ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"PAYMENT_PENDING", "PAYMENT_FAILED", "CANCELLED"},
    "PAYMENT_PENDING": {"PAYMENT_CONFIRMED", "PAYMENT_FAILED", "CANCELLED"},
    "PAYMENT_CONFIRMED": {"PLACED"},
    "PLACED": {"ACCEPTED", "REJECTED", "CANCELLED"},
    "ACCEPTED": {"PREPARING", "REJECTED", "CANCELLED"},
    "PREPARING": {"READY"},
    "READY": {"COMPLETED"},
    "COMPLETED": set(),
    "PAYMENT_FAILED": set(),
    "CANCELLED": set(),
    "REJECTED": set(),
}


def _quantize(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"))


_ORDER_SEQ_LOCK = threading.Lock()
_ORDER_SEQ_FALLBACK: dict[str, int] = {}


def _generate_order_number(db: Session) -> str:
    """Lock-free monotonic order number generator (PG sequence; thread-safe monotonic counter on SQLite)."""
    today_str = today_college().strftime("%Y%m%d")
    prefix = f"CB-{today_str}-"
    if db.bind and db.bind.dialect.name == "postgresql":
        try:
            with db.begin_nested():
                seq_val = int(db.execute(text("SELECT nextval('order_number_seq')")).scalar_one())
            return f"{prefix}{seq_val:06d}"
        except Exception:
            # Ensure sequence exists in fresh PostgreSQL environments without poisoning outer transaction
            with db.begin_nested():
                db.execute(text("CREATE SEQUENCE IF NOT EXISTS order_number_seq START WITH 1 INCREMENT BY 1"))
                seq_val = int(db.execute(text("SELECT nextval('order_number_seq')")).scalar_one())
            return f"{prefix}{seq_val:06d}"

    with _ORDER_SEQ_LOCK:
        max_num = db.scalar(select(func.max(Order.order_number)).where(Order.order_number.like(f"{prefix}%")))
        db_seq = 0
        if max_num:
            try:
                db_seq = int(max_num.rsplit("-", 1)[-1])
            except ValueError:
                db_seq = 0
        seq = max(db_seq, _ORDER_SEQ_FALLBACK.get(today_str, 0)) + 1
        while True:
            candidate = f"{prefix}{seq:06d}"
            exists = db.scalar(select(Order.id).where(Order.order_number == candidate))
            if not exists:
                _ORDER_SEQ_FALLBACK[today_str] = seq
                return candidate
            seq += 1


def rollback_unpaid_incentives(db: Session, order: Order) -> None:
    """Restore redeemed loyalty points ONLY when payment was never confirmed."""
    if order.payment_status == "CONFIRMED":
        return

    if order.customer_id:
        redeemed_txns = db.scalars(
            select(LoyaltyTransaction).where(
                LoyaltyTransaction.order_id == order.id,
                LoyaltyTransaction.transaction_type == "redeem",
            )
        ).all()
        already_restored = db.scalar(
            select(LoyaltyTransaction.id).where(
                LoyaltyTransaction.order_id == order.id,
                LoyaltyTransaction.transaction_type == "redeem_restore",
            )
        )
        if redeemed_txns and not already_restored:
            acct = db.scalar(
                select(LoyaltyAccount).where(LoyaltyAccount.user_id == order.customer_id).with_for_update()
            )
            if acct:
                pts_to_restore = sum((-t.points_delta for t in redeemed_txns if t.points_delta < 0), 0)
                if pts_to_restore > 0:
                    acct.points_balance += pts_to_restore
                    db.add(
                        LoyaltyTransaction(
                            loyalty_account_id=acct.id,
                            order_id=order.id,
                            points_delta=pts_to_restore,
                            transaction_type="redeem_restore",
                            description=f"Restored redeemed points from unpaid order {order.order_number}",
                        )
                    )


def release_expired_slot_reservations(db: Session) -> int:
    """Release expired pending online checkout slot reservations cleanly."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(SlotReservation)
        .where(
            SlotReservation.status == "reserved",
            SlotReservation.expires_at.is_not(None),
            SlotReservation.expires_at <= now,
        )
        .limit(50)
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    expired_resvs = db.scalars(stmt).all()
    released = 0
    for resv in expired_resvs:
        order = db.scalar(select(Order).where(Order.id == resv.order_id).with_for_update())
        if not order or order.payment_status == "CONFIRMED" or order.status != "PAYMENT_PENDING":
            continue
        resv.status = "released"
        slot = db.scalar(select(PickupSlot).where(PickupSlot.id == resv.pickup_slot_id).with_for_update())
        if slot and slot.reserved_count > 0:
            slot.reserved_count -= 1
            safe_redis(lambda r: r.decr(f"cb:slot:{slot.id}:reserved"))
        order.payment_status = "FAILED"
        transition_order_status(db, order, "PAYMENT_FAILED", reason="Checkout payment window expired")
        pay = db.scalar(select(Payment).where(Payment.order_id == order.id, Payment.status == "PENDING"))
        if pay:
            pay.status = "FAILED"
            pay.failure_reason = "Checkout window expired"
        rollback_unpaid_incentives(db, order)
        try:
            from app.services.inventory_service import release_inventory_reservation_for_order
            release_inventory_reservation_for_order(db, order)
        except ImportError:
            pass
        released += 1
    if released:
        db.commit()
    return released


def _serialize_order_with_maps(
    order: Order,
    *,
    canteen: Optional[Canteen],
    counter: Optional[Counter],
    token_row: Optional[PickupToken],
    qr_row: Optional[OrderQRCode],
    pay_row: Optional[Payment],
    policy_text: str,
    raw_guest_token: Optional[str] = None,
    queue_metrics: Optional[dict] = None,
) -> OrderOut:
    items_out = [OrderItemOut.model_validate(item) for item in order.items]
    return OrderOut(
        id=order.id,
        order_number=order.order_number,
        canteen_id=order.canteen_id,
        canteen_name=canteen.name if canteen else None,
        counter_id=order.counter_id,
        counter_name=counter.name if counter else None,
        kitchen_id=order.kitchen_id,
        table_id=order.table_id,
        customer_id=order.customer_id,
        is_guest=order.is_guest,
        guest_name=order.guest_name,
        guest_phone_masked=mask_mobile(order.guest_phone) if order.guest_phone else None,
        order_type=order.order_type,
        order_channel=order.order_channel,
        status=order.status,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        subtotal_amount=order.subtotal_amount,
        discount_amount=order.discount_amount,
        tax_amount=order.tax_amount,
        total_amount=order.total_amount,
        coupon_code=order.coupon_code,
        estimated_prep_minutes=order.estimated_prep_minutes,
        estimated_pickup_at=order.estimated_pickup_at,
        delayed_minutes=order.delayed_minutes,
        delay_reason=order.delay_reason,
        is_priority=order.is_priority,
        queue_position=(queue_metrics or {}).get("queue_position"),
        orders_ahead_count=(queue_metrics or {}).get("orders_ahead_count"),
        counter_queue_position=(queue_metrics or {}).get("counter_queue_position"),
        dynamic_wait_minutes=(queue_metrics or {}).get("dynamic_wait_minutes"),
        waiting_time_available=(queue_metrics or {}).get("waiting_time_available", True),
        waiting_time_message=(queue_metrics or {}).get("waiting_time_message"),
        last_updated_at=(queue_metrics or {}).get("last_updated_at"),
        pickup_token_code=token_row.token_code if token_row else None,
        qr_verification_path=qr_row.verification_path if qr_row else None,
        qr_token_raw=qr_row.qr_payload_encoded if qr_row else None,
        guest_access_token=raw_guest_token,
        razorpay_order_id=pay_row.provider_order_id if (pay_row and pay_row.provider == "razorpay") else None,
        razorpay_key_id=razorpay_gateway.public_key_id if order.payment_method == "razorpay" else None,
        cancellation_policy_text=policy_text,
        created_at=order.created_at,
        confirmed_at=order.confirmed_at,
        accepted_at=order.accepted_at,
        preparing_at=order.preparing_at,
        ready_at=order.ready_at,
        completed_at=order.completed_at,
        items=items_out,
        status_history=sorted(order.status_history, key=lambda s: s.created_at),
    )


def serialize_orders_batch(db: Session, orders: list[Order]) -> list[OrderOut]:
    if not orders:
        return []
    oids = [o.id for o in orders]
    cids = list({o.canteen_id for o in orders})
    canteens_list = (
        db.scalars(
            select(Canteen)
            .options(joinedload(Canteen.counters), joinedload(Canteen.operating_hours))
            .where(Canteen.id.in_(cids))
        )
        .unique()
        .all()
    )
    canteens = {c.id: c for c in canteens_list}
    counters: dict[UUID, Counter] = {}
    active_counter_counts: dict[UUID, int] = {}
    for c in canteens_list:
        active_cnt = 0
        for cnt in c.counters:
            counters[cnt.id] = cnt
            if cnt.is_active:
                active_cnt += 1
        active_counter_counts[c.id] = active_cnt
    tokens = {t.order_id: t for t in db.scalars(select(PickupToken).where(PickupToken.order_id.in_(oids))).all()}
    qrs = {q.order_id: q for q in db.scalars(select(OrderQRCode).where(OrderQRCode.order_id.in_(oids))).all()}
    pays: dict[UUID, Payment] = {}
    for p in db.scalars(select(Payment).where(Payment.order_id.in_(oids)).order_by(Payment.created_at.desc())).all():
        if p.order_id not in pays:
            pays[p.order_id] = p
    college_cfg = get_college_config_snapshot(db)
    policy_text = college_cfg.get("cancellation_policy_text") or ""
    from app.services.queue_service import compute_order_queue_metrics_map

    q_metrics_map = compute_order_queue_metrics_map(
        db,
        orders,
        precomputed_canteens=canteens,
        precomputed_active_counter_counts=active_counter_counts,
        precomputed_tz_name=college_cfg.get("college_timezone"),
    )
    return [
        _serialize_order_with_maps(
            o,
            canteen=canteens.get(o.canteen_id),
            counter=counters.get(o.counter_id),
            token_row=tokens.get(o.id),
            qr_row=qrs.get(o.id),
            pay_row=pays.get(o.id),
            policy_text=policy_text,
            queue_metrics=q_metrics_map.get(o.id),
        )
        for o in orders
    ]


def serialize_order(db: Session, order: Order, *, raw_guest_token: Optional[str] = None) -> OrderOut:
    canteen = db.get(Canteen, order.canteen_id)
    counter = db.get(Counter, order.counter_id)
    token_row = db.scalar(select(PickupToken).where(PickupToken.order_id == order.id))
    qr_row = db.scalar(select(OrderQRCode).where(OrderQRCode.order_id == order.id))
    pay_row = db.scalar(select(Payment).where(Payment.order_id == order.id).order_by(Payment.created_at.desc()))
    policy_text = get_college_config_snapshot(db).get("cancellation_policy_text") or ""
    from app.services.queue_service import compute_order_queue_metrics_map

    q_metrics = compute_order_queue_metrics_map(
        db, [order], precomputed_canteens={canteen.id: canteen} if canteen else None
    ).get(order.id)
    return _serialize_order_with_maps(
        order,
        canteen=canteen,
        counter=counter,
        token_row=token_row,
        qr_row=qr_row,
        pay_row=pay_row,
        policy_text=policy_text,
        raw_guest_token=raw_guest_token,
        queue_metrics=q_metrics,
    )


def list_pickup_slots(db: Session, canteen_id: UUID) -> list[PickupSlotOut]:
    from app.core.cache import NS_QUEUE, cache_manager

    cache_ns = f"{NS_QUEUE}:{canteen_id}"
    hit, cached = cache_manager.get_json(cache_ns, "pickup_slots", l1_ttl=2.0)
    if hit and isinstance(cached, list):
        return [PickupSlotOut.model_validate(x) for x in cached]

    today = today_college()
    slots = db.scalars(
        select(PickupSlot)
        .where(
            PickupSlot.canteen_id == canteen_id,
            PickupSlot.is_active.is_(True),
            PickupSlot.slot_date >= today,
        )
        .order_by(PickupSlot.slot_date.asc(), PickupSlot.start_time.asc())
    ).all()
    results: list[PickupSlotOut] = []
    for s in slots:
        out = PickupSlotOut.model_validate(s)
        out.available_count = max(0, s.capacity - s.reserved_count)
        results.append(out)
    cache_manager.set_json(
        cache_ns,
        "pickup_slots",
        [r.model_dump(mode="json") for r in results],
        ttl_seconds=10,
        l1_ttl=2.0,
    )
    return results


def checkout_order(
    db: Session,
    payload: CheckoutRequest,
    *,
    user_id: Optional[UUID] = None,
    guest_session_id: Optional[str] = None,
    cashier_user_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
) -> OrderOut:
    # 1. Scoped idempotency protection (never leaks across users/guests)
    if payload.idempotency_key:
        idem_stmt = (
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
            .where(Order.idempotency_key == payload.idempotency_key)
        )
        if user_id:
            idem_stmt = idem_stmt.where(Order.customer_id == user_id)
        elif payload.guest_phone:
            idem_stmt = idem_stmt.where(Order.is_guest.is_(True), Order.guest_phone == payload.guest_phone.strip())
        else:
            idem_stmt = idem_stmt.where(Order.is_guest.is_(True))
        existing_order = db.scalar(idem_stmt)
        if existing_order:
            return serialize_order(db, existing_order)

    if not payload.accepted_policy:
        raise HTTPException(status_code=400, detail="You must acknowledge the college cancellation and payment policy before checkout")

    global _LAST_SLOT_CLEANUP_MONOTONIC
    now_mono = time.monotonic()
    if payload.pickup_slot_id or (now_mono - _LAST_SLOT_CLEANUP_MONOTONIC) >= 30.0:
        _LAST_SLOT_CLEANUP_MONOTONIC = now_mono
        release_expired_slot_reservations(db)

    college = get_or_create_college_settings(db)
    canteen = db.get(Canteen, payload.canteen_id)
    if not canteen or not canteen.is_active:
        raise HTTPException(status_code=404, detail="Selected canteen is unavailable")

    is_open, _crowd, eta, active_count = compute_canteen_live_status(db, canteen)
    if not is_open:
        raise HTTPException(status_code=400, detail="Canteen is currently closed, paused, or on holiday")
    if canteen.auto_throttle_enabled and active_count >= canteen.max_concurrent_orders:
        raise HTTPException(status_code=429, detail="Canteen queue is at full capacity. Please retry shortly.")

    # Strict NO-CASH, RAZORPAY-ONLY online payment policy (plus authorized cashier POS terminals)
    if payload.payment_method in ("cash", "pay_at_pickup"):
        raise HTTPException(
            status_code=400,
            detail="Cash and Pay-at-Pickup are disabled. Only Razorpay online payments (or authorized counter POS) are accepted.",
        )
    if payload.payment_method not in ("razorpay", "upi_pos", "card_pos"):
        raise HTTPException(status_code=400, detail="Only Razorpay is supported for online checkout.")
    if payload.payment_method == "razorpay" and not (college.razorpay_enabled and canteen.allow_online_payment):
        raise HTTPException(status_code=400, detail="Razorpay online payment is disabled for this canteen")
    if payload.payment_method in ("upi_pos", "card_pos") and not cashier_user_id:
        raise HTTPException(status_code=403, detail="POS terminal payment methods require authorized cashier staff")

    now = datetime.now(timezone.utc)
    # Resolve location QR if passed
    location_qr_id: Optional[UUID] = None
    counter_id = payload.counter_id
    table_id = payload.table_id
    if payload.location_qr_code:
        loc_qr = db.scalar(select(LocationQRCode).where(LocationQRCode.code == payload.location_qr_code.strip()))
        if not loc_qr or not loc_qr.is_active or loc_qr.revoked_at is not None or (loc_qr.expires_at and loc_qr.expires_at <= now):
            raise HTTPException(status_code=400, detail="Scanned location QR code is invalid, expired, or revoked")
        if loc_qr.canteen_id != canteen.id:
            raise HTTPException(status_code=400, detail="Location QR belongs to a different canteen")
        location_qr_id = loc_qr.id
        counter_id = counter_id or loc_qr.counter_id
        table_id = table_id or loc_qr.table_id

    if table_id:
        table = db.get(DiningTable, table_id)
        if not table or table.canteen_id != canteen.id:
            raise HTTPException(status_code=400, detail="Invalid dining table")

    # Validate guest / customer identity (direct guest checkout without OTP; walk-in cashier POS exempt)
    is_guest = user_id is None
    if is_guest and not cashier_user_id:
        if not payload.guest_name or not payload.guest_phone:
            raise HTTPException(status_code=400, detail="Guest name and mobile number are required")

    # Gather line items from cart or direct payload
    line_specs: list[CheckoutItemDirectIn] = list(payload.direct_items)
    cart: Optional[Cart] = None
    if not line_specs and payload.use_cart:
        cart = get_active_cart(db, canteen.id, user_id=user_id, guest_session_id=guest_session_id, create_if_missing=False)
        if cart:
            for ci in cart.items:
                spice = next((c.option_value for c in ci.customizations if c.customization_type == "spice"), None)
                sugar = next((c.option_value for c in ci.customizations if c.customization_type == "sugar"), None)
                rems = [c.option_value for c in ci.customizations if c.customization_type == "remove_ingredient"]
                addons = [
                    {"addon_id": c.addon_id, "quantity": c.quantity}
                    for c in ci.customizations
                    if c.customization_type == "addon" and c.addon_id
                ]
                line_specs.append(
                    CheckoutItemDirectIn(
                        food_item_id=ci.food_item_id,
                        variant_id=ci.variant_id,
                        quantity=ci.quantity,
                        spice_level=spice,
                        sugar_level=sugar,
                        removed_ingredients=rems,
                        addons=addons,
                        special_instructions=ci.special_instructions,
                    )
                )

    if payload.coupon_code and payload.coupon_code.strip():
        raise HTTPException(
            status_code=400,
            detail="Discounts and promotional coupon codes are disabled. All items are billed at exact listed prices.",
        )
    if payload.redeem_loyalty_points and payload.redeem_loyalty_points > 0:
        raise HTTPException(
            status_code=400,
            detail="Loyalty point discounts are disabled. All items are billed at exact listed prices.",
        )

    if not line_specs:
        raise HTTPException(status_code=400, detail="Cart is empty; add items before checkout")

    # Resolve counter & kitchen dynamically (express routing & multi-counter load balancing)
    first_food = db.get(FoodItem, line_specs[0].food_item_id)
    spec_foods = db.scalars(select(FoodItem).where(FoodItem.id.in_([s.food_item_id for s in line_specs]))).all()
    total_qty = sum(int(s.quantity or 1) for s in line_specs)
    fastest_prep = max((int(f.prep_time_minutes or 10) for f in spec_foods), default=10)
    is_express_eligible = total_qty <= 3 and fastest_prep <= 6

    from app.services.queue_service import select_optimal_counter

    counter_id, _routing_mode = select_optimal_counter(
        db,
        canteen_id=canteen.id,
        explicit_counter_id=counter_id,
        food_preferred_counter_id=first_food.counter_id if first_food else None,
        is_express_eligible=is_express_eligible,
    )

    kitchen_id = first_food.kitchen_id if (first_food and first_food.kitchen_id) else None
    if not kitchen_id:
        default_kitchen = db.scalar(
            select(Kitchen).where(Kitchen.canteen_id == canteen.id, Kitchen.is_active.is_(True)).order_by(Kitchen.code)
        )
        kitchen_id = default_kitchen.id if default_kitchen else None

    # Validate pickup slot capacity atomically with FOR UPDATE + Redis (guarding rollback immediately)
    pickup_slot: Optional[PickupSlot] = None
    redis_slot_key: Optional[str] = None
    redis_incremented = False
    if payload.pickup_slot_id:
        pickup_slot = db.scalar(
            select(PickupSlot).where(PickupSlot.id == payload.pickup_slot_id).with_for_update()
        )
        if not pickup_slot or pickup_slot.canteen_id != canteen.id or not pickup_slot.is_active:
            raise HTTPException(status_code=400, detail="Invalid or inactive pickup slot")
        if pickup_slot.slot_date < today_college():
            raise HTTPException(status_code=400, detail="Selected pickup slot date is in the past")
        if pickup_slot.reserved_count >= pickup_slot.capacity:
            raise HTTPException(status_code=409, detail="Selected pickup slot is full")
        rkey = f"cb:slot:{pickup_slot.id}:reserved"

        def _reserve_slot_cache(redis_client):
            if not redis_client.exists(rkey):
                redis_client.set(rkey, pickup_slot.reserved_count, ex=86400)
            return redis_client.incr(rkey)

        new_count = safe_redis(_reserve_slot_cache)
        if new_count is not None and new_count > pickup_slot.capacity:
            safe_redis(lambda r: r.decr(rkey))
            raise HTTPException(status_code=409, detail="Selected pickup slot capacity reached")
        if new_count is not None:
            redis_slot_key = rkey
            redis_incremented = True
        pickup_slot.reserved_count += 1

    try:
        # Recalculate ALL prices strictly on backend using batched lookups
        subtotal = Decimal("0.00")
        max_item_prep = canteen.default_prep_time_minutes
        prepared_items: list[tuple[FoodItem, Optional[FoodVariant], int, Decimal, Decimal, Decimal, Optional[str], list[dict]]] = []

        spec_food_map = {f.id: f for f in spec_foods}
        spec_food_ids = list(spec_food_map.keys())
        spec_cat_ids = list({f.category_id for f in spec_foods})
        spec_cat_map = {c.id: c for c in db.scalars(select(FoodCategory).where(FoodCategory.id.in_(spec_cat_ids))).all()} if spec_cat_ids else {}
        spec_variant_ids = list({s.variant_id for s in line_specs if s.variant_id})
        spec_variant_map = {v.id: v for v in db.scalars(select(FoodVariant).where(FoodVariant.id.in_(spec_variant_ids))).all()} if spec_variant_ids else {}
        spec_recipes = {r.food_item_id: r for r in db.scalars(select(Recipe).where(Recipe.food_item_id.in_(spec_food_ids))).all()} if spec_food_ids else {}
        spec_recipe_ids = [r.id for r in spec_recipes.values()]
        spec_reqs_by_recipe: dict[UUID, list[RecipeIngredient]] = {}
        if spec_recipe_ids:
            for req in db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(spec_recipe_ids))).all():
                spec_reqs_by_recipe.setdefault(req.recipe_id, []).append(req)
        spec_addon_ids = list({ad.addon_id for s in line_specs for ad in s.addons})
        spec_addon_map = {a.id: a for a in db.scalars(select(FoodAddon).where(FoodAddon.id.in_(spec_addon_ids))).all()} if spec_addon_ids else {}
        spec_addon_links = (
            {
                (lnk.food_item_id, lnk.addon_id): lnk
                for lnk in db.scalars(
                    select(FoodItemAddon).where(
                        FoodItemAddon.food_item_id.in_(spec_food_ids),
                        FoodItemAddon.addon_id.in_(spec_addon_ids),
                    )
                ).all()
            }
            if (spec_food_ids and spec_addon_ids)
            else {}
        )

        sched_target_dt = (
            datetime.combine(pickup_slot.slot_date, pickup_slot.start_time, tzinfo=get_college_tz())
            if pickup_slot
            else None
        )
        sched_map = compute_schedule_availability_map(
            db,
            [s.food_item_id for s in line_specs],
            target_dt=sched_target_dt,
            food_items_map=spec_food_map,
        )
        needed_ingredients: dict[UUID, Decimal] = {}

        for spec in line_specs:
            food = spec_food_map.get(spec.food_item_id)
            if not food or food.canteen_id != canteen.id or not food.is_active:
                raise HTTPException(status_code=400, detail="Food item not found in canteen")
            cat = spec_cat_map.get(food.category_id)
            if not cat or not cat.is_active:
                raise HTTPException(status_code=400, detail=f"{food.name}'s category is currently inactive")
            if not food.is_available or food.insufficient_ingredients:
                raise HTTPException(status_code=400, detail=f"{food.name} is currently out of stock or unavailable")
            if not sched_map.get(food.id, True):
                raise HTTPException(status_code=400, detail=f"{food.name} is outside its scheduled serving hours or validity period")

            recipe = spec_recipes.get(food.id)
            if recipe:
                for req in spec_reqs_by_recipe.get(recipe.id, ()):
                    per_unit = (req.quantity_required * Decimal(spec.quantity)) / Decimal(max(1, recipe.yield_portions))
                    needed_ingredients[req.ingredient_id] = needed_ingredients.get(req.ingredient_id, Decimal("0.000")) + per_unit

            max_item_prep = max(max_item_prep, food.prep_time_minutes)
            variant: Optional[FoodVariant] = None
            unit_price = food.base_price
            if spec.variant_id:
                variant = spec_variant_map.get(spec.variant_id)
                if not variant or variant.food_item_id != food.id or not variant.is_available:
                    raise HTTPException(status_code=400, detail=f"Selected variant for {food.name} is unavailable")
                unit_price = variant.absolute_price if variant.absolute_price is not None else (food.base_price + variant.price_delta)
            unit_price = _quantize(unit_price)

            addon_per_unit = Decimal("0.00")
            cust_dicts: list[dict] = []
            if spec.spice_level:
                cust_dicts.append({"customization_type": "spice", "option_name": "Spice Level", "option_value": spec.spice_level, "quantity": 1, "unit_price": Decimal("0.00"), "total_price": Decimal("0.00")})
            if spec.sugar_level:
                cust_dicts.append({"customization_type": "sugar", "option_name": "Sugar Level", "option_value": spec.sugar_level, "quantity": 1, "unit_price": Decimal("0.00"), "total_price": Decimal("0.00")})
            for rem in spec.removed_ingredients:
                cust_dicts.append({"customization_type": "remove_ingredient", "option_name": "Remove", "option_value": rem, "quantity": 1, "unit_price": Decimal("0.00"), "total_price": Decimal("0.00")})

            for ad in spec.addons:
                link = spec_addon_links.get((food.id, ad.addon_id))
                addon = spec_addon_map.get(ad.addon_id)
                if not link or not addon or not addon.is_available:
                    raise HTTPException(status_code=400, detail="Invalid or unavailable add-on")
                if ad.quantity > link.max_quantity:
                    raise HTTPException(status_code=400, detail=f"Maximum {link.max_quantity} allowed for {addon.name}")
                line_addon_total = _quantize(addon.price * ad.quantity)
                addon_per_unit += line_addon_total
                cust_dicts.append({
                    "addon_id": addon.id,
                    "customization_type": "addon",
                    "option_name": addon.name,
                    "option_value": f"x{ad.quantity}",
                    "quantity": ad.quantity,
                    "unit_price": addon.price,
                    "total_price": line_addon_total,
                })

            line_sub = _quantize((unit_price + addon_per_unit) * spec.quantity)
            subtotal += line_sub
            prepared_items.append((food, variant, spec.quantity, unit_price, addon_per_unit, line_sub, spec.special_instructions, cust_dicts))

        if needed_ingredients:
            try:
                from app.services.inventory_service import reserve_inventory_for_order
                reserve_inventory_for_order(db, canteen.id, needed_ingredients)
            except ImportError:
                pass

        # Active pricing policy: exact listed prices only.
        # Discount = 0, Additional checkout tax = 0, Extra item charges = 0, Final Payable = Subtotal.
        subtotal = _quantize(subtotal)
        discount = Decimal("0.00")
        tax_amount = Decimal("0.00")
        total_amount = subtotal
        if cart and cart.coupon_code:
            cart.coupon_code = None

        if pickup_slot:
            redis_slot_key = f"cb:slot:{pickup_slot.id}:reserved"
            redis_incremented = True

        complexity_bonus = min(12, max(0, len(line_specs) - 1) * 2)
        est_prep = max(eta, max_item_prep + complexity_bonus)
        raw_guest_token = None
        guest_token_hash = None
        if is_guest:
            raw_guest_token, guest_token_hash = generate_guest_access_token()

        order = Order(
            order_number=_generate_order_number(db),
            idempotency_key=payload.idempotency_key,
            canteen_id=canteen.id,
            counter_id=counter_id,
            kitchen_id=kitchen_id,
            table_id=table_id,
            customer_id=user_id,
            cashier_id=cashier_user_id,
            pickup_slot_id=pickup_slot.id if pickup_slot else None,
            location_qr_id=location_qr_id,
            is_guest=is_guest,
            guest_name=payload.guest_name.strip() if payload.guest_name else None,
            guest_phone=payload.guest_phone.strip() if payload.guest_phone else None,
            guest_email=payload.guest_email.strip() if payload.guest_email else None,
            guest_access_token_hash=guest_token_hash,
            order_type=payload.order_type,
            order_channel=payload.order_channel,
            status="PAYMENT_PENDING",
            payment_status="PENDING",
            payment_method=payload.payment_method,
            subtotal_amount=subtotal,
            discount_amount=discount,
            tax_amount=tax_amount,
            total_amount=total_amount,
            coupon_code=None,
            estimated_prep_minutes=est_prep,
            estimated_pickup_at=now + timedelta(minutes=est_prep),
            notes=payload.notes,
        )
        db.add(order)
        db.flush()

        for food, variant, qty, unit_p, addon_u, line_sub, instr, custs in prepared_items:
            item_tax = Decimal("0.00")
            line_total = line_sub
            oi = OrderItem(
                order_id=order.id,
                food_item_id=food.id,
                variant_id=variant.id if variant else None,
                station_id=getattr(food, "station_id", None),
                prep_status="PENDING",
                item_name=food.name,
                variant_name=variant.name if variant else None,
                quantity=qty,
                unit_price=unit_p,
                addon_total_per_unit=addon_u,
                line_subtotal=line_sub,
                tax_amount=item_tax,
                line_total=line_total,
                special_instructions=instr,
            )
            db.add(oi)
            db.flush()
            for c in custs:
                db.add(OrderItemCustomization(order_item_id=oi.id, **c))

        db.add(OrderStatusHistory(order_id=order.id, from_status="CREATED", to_status="PAYMENT_PENDING", changed_by_user_id=user_id or cashier_user_id, reason="Order created and awaiting payment"))

        if pickup_slot:
            slot_exp = (now + timedelta(minutes=15)) if payload.payment_method == "razorpay" else None
            db.add(SlotReservation(pickup_slot_id=pickup_slot.id, order_id=order.id, status="reserved", expires_at=slot_exp))

        # Create payment request (Razorpay online or authorized counter POS)
        provider = "razorpay" if payload.payment_method == "razorpay" else "counter_pos"
        provider_order_id = None
        gateway_meta: dict = {}
        if provider == "razorpay":
            rzp_order = razorpay_gateway.create_order(
                amount_inr=total_amount,
                receipt_ref=order.order_number,
                notes={"order_number": order.order_number, "canteen": canteen.code},
            )
            provider_order_id = rzp_order["id"]
            gateway_meta = {
                "razorpay_order_id": rzp_order["id"],
                "amount_paise": rzp_order.get("amount"),
                "currency": rzp_order.get("currency", "INR"),
            }

        payment = Payment(
            order_id=order.id,
            provider=provider,
            method=payload.payment_method,
            provider_order_id=provider_order_id,
            amount=total_amount,
            currency="INR",
            status="PENDING",
            gateway_metadata=gateway_meta,
        )
        db.add(payment)
        db.flush()
        db.add(
            PaymentTransaction(
                payment_id=payment.id,
                order_id=order.id,
                transaction_type="initiate",
                amount=total_amount,
                status="PENDING",
                external_reference=provider_order_id,
            )
        )

        if cart:
            cart.status = "converted"

        record_audit_log(
            db,
            action="order.checkout_created",
            entity_type="order",
            entity_id=order.order_number,
            actor_user_id=user_id or cashier_user_id,
            ip_address=ip_address,
            details={"total_amount": str(total_amount), "payment_method": payload.payment_method, "is_guest": is_guest},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if redis_incremented and redis_slot_key:
            safe_redis(lambda r: r.decr(redis_slot_key))
        if payload.idempotency_key:
            dup_stmt = (
                select(Order)
                .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
                .where(Order.idempotency_key == payload.idempotency_key)
            )
            existing_dup = db.scalar(dup_stmt)
            if existing_dup:
                same_owner = (
                    (user_id is not None and existing_dup.customer_id == user_id)
                    or (user_id is None and existing_dup.is_guest and (not payload.guest_phone or existing_dup.guest_phone == payload.guest_phone.strip()))
                )
                if same_owner:
                    return serialize_order(db, existing_dup)
                raise HTTPException(status_code=409, detail="Idempotency key already used for another order")
        raise
    except Exception:
        db.rollback()
        if redis_incremented and redis_slot_key:
            safe_redis(lambda r: r.decr(redis_slot_key))
        raise

    db.expire_all()
    loaded = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order.id)
    )
    out = serialize_order(db, loaded, raw_guest_token=raw_guest_token)
    emit_order_event_sync(
        str(order.canteen_id),
        str(order.id),
        "order.created",
        {"order_number": order.order_number, "status": order.status, "payment_status": order.payment_status},
    )
    return out


def transition_order_status(
    db: Session,
    order: Order,
    to_status: str,
    *,
    actor_user_id: Optional[UUID] = None,
    reason: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> Order:
    allowed = ALLOWED_STATUS_TRANSITIONS.get(order.status, set())
    if to_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid order status transition from {order.status} to {to_status}",
        )
    now = datetime.now(timezone.utc)
    from_status = order.status
    order.status = to_status
    if to_status == "PAYMENT_CONFIRMED":
        order.confirmed_at = now
    elif to_status == "ACCEPTED":
        order.accepted_at = now
    elif to_status == "PREPARING":
        order.preparing_at = now
    elif to_status == "READY":
        order.ready_at = now
    elif to_status == "COMPLETED":
        order.completed_at = now

    db.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=from_status,
            to_status=to_status,
            changed_by_user_id=actor_user_id,
            reason=reason,
            metadata_json=metadata or {},
        )
    )
    return order


def cancel_or_reject_order(
    db: Session,
    order_id: UUID,
    *,
    cancellation_type: str,
    reason: str,
    actor_user_id: Optional[UUID],
    finance_note: Optional[str] = None,
    guest_access_token: Optional[str] = None,
    is_staff: bool = False,
    staff_canteen_id: Optional[UUID] = None,
    staff_counter_id: Optional[UUID] = None,
) -> OrderOut:
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.id == order_id)
        .with_for_update()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if is_staff:
        if staff_canteen_id and order.canteen_id != staff_canteen_id:
            raise HTTPException(status_code=403, detail="Staff user is not authorized for this canteen")
        if staff_counter_id and order.counter_id != staff_counter_id:
            raise HTTPException(status_code=403, detail="Counter staff user is not authorized for this counter")
    else:
        if order.is_guest:
            if not guest_access_token or order.guest_access_token_hash != sha256_hex(guest_access_token):
                if actor_user_id is None and not guest_access_token:
                    raise HTTPException(status_code=401, detail="Authentication or valid guest token required")
                raise HTTPException(status_code=403, detail="Valid guest access token required")
        elif actor_user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required to cancel this order")
        elif order.customer_id != actor_user_id:
            raise HTTPException(status_code=403, detail="Not authorized to cancel this order")

    was_unpaid_pending = order.status in ("CREATED", "PAYMENT_PENDING") and order.payment_status != "CONFIRMED"
    target_status = "REJECTED" if cancellation_type == "rejected" else "CANCELLED"
    transition_order_status(db, order, target_status, actor_user_id=actor_user_id, reason=reason)
    if was_unpaid_pending:
        try:
            from app.services.inventory_service import release_inventory_reservation_for_order
            release_inventory_reservation_for_order(db, order)
        except ImportError:
            pass

    now = datetime.now(timezone.utc)
    # Revoke active token/QR if already generated so cancelled order cannot be collected
    tok = db.scalar(select(PickupToken).where(PickupToken.order_id == order.id))
    if tok and tok.status == "ACTIVE":
        tok.status = "REVOKED"
    qr = db.scalar(select(OrderQRCode).where(OrderQRCode.order_id == order.id))
    if qr and qr.revoked_at is None:
        qr.revoked_at = now
        qr.revocation_reason = f"Order {target_status.lower()}: {reason}"

    if order.payment_status != "CONFIRMED":
        rollback_unpaid_incentives(db, order)

    # Release reserved slot if not yet fulfilled
    resv = db.scalar(select(SlotReservation).where(SlotReservation.order_id == order.id))
    if resv and resv.status == "reserved":
        resv.status = "released"
        slot = db.scalar(select(PickupSlot).where(PickupSlot.id == resv.pickup_slot_id).with_for_update())
        if slot and slot.reserved_count > 0:
            slot.reserved_count -= 1
            safe_redis(lambda r: r.decr(f"cb:slot:{slot.id}:reserved"))

    # Payment is retained with ZERO automated refunds per policy
    db.add(
        OrderCancellation(
            order_id=order.id,
            cancellation_type=cancellation_type,
            reason=reason,
            cancelled_by_user_id=actor_user_id,
            payment_retained=True,
            finance_note=finance_note,
        )
    )
    record_audit_log(
        db,
        action=f"order.{cancellation_type}",
        entity_type="order",
        entity_id=order.order_number,
        actor_user_id=actor_user_id,
        details={"reason": reason, "payment_retained": True, "refund_initiated": False},
    )
    if cancellation_type == "cancelled":
        try:
            from app.services.notification_service import notify_customer_order_event
            notify_customer_order_event(
                db,
                order,
                event_type="order_cancelled",
                title=f"Order {order.order_number} Cancelled",
                message=f"Order {order.order_number} was cancelled ({reason}). Payment records remain stored per campus policy.",
                send_external=True,
            )
        except ImportError:
            pass
    db.commit()
    db.refresh(order)
    emit_order_event_sync(str(order.canteen_id), str(order.id), f"order.{target_status.lower()}", {"status": order.status})
    return serialize_order(db, order)


def get_order_authorized(
    db: Session,
    order_id_or_number: str,
    *,
    user_id: Optional[UUID] = None,
    is_staff: bool = False,
    staff_canteen_id: Optional[UUID] = None,
    staff_counter_id: Optional[UUID] = None,
    guest_access_token: Optional[str] = None,
) -> OrderOut:
    stmt = select(Order).options(
        selectinload(Order.items).selectinload(OrderItem.customizations),
        selectinload(Order.status_history),
    )
    try:
        oid = UUID(order_id_or_number)
        order = db.scalar(stmt.where(Order.id == oid))
    except ValueError:
        order = db.scalar(stmt.where(Order.order_number == order_id_or_number))

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if is_staff:
        if staff_canteen_id and order.canteen_id != staff_canteen_id:
            raise HTTPException(status_code=403, detail="Staff user is not authorized for this canteen")
        if staff_counter_id and order.counter_id != staff_counter_id:
            raise HTTPException(status_code=403, detail="Counter staff user is not authorized for this counter")
    else:
        if order.is_guest:
            if not guest_access_token or order.guest_access_token_hash != sha256_hex(guest_access_token):
                if user_id is None and not guest_access_token:
                    raise HTTPException(status_code=401, detail="Authentication or valid guest token required")
                raise HTTPException(status_code=403, detail="Valid guest access token required")
        elif user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required to view this order")
        elif order.customer_id != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to view this order")

    return serialize_order(db, order)


def lookup_guest_orders(
    db: Session, *, order_number: str, guest_contact: str
) -> list[OrderOut]:
    clean_num = order_number.strip().upper()
    clean_target = guest_contact.strip()
    digits = "".join(ch for ch in clean_target if ch.isdigit())
    phone_candidates = {clean_target}
    if len(digits) == 10:
        phone_candidates.update({digits, f"+91{digits}", f"91{digits}"})
    elif len(digits) == 12 and digits.startswith("91"):
        phone_candidates.update({f"+{digits}", digits, digits[-10:]})
    where_clause = (
        Order.guest_email == clean_target.lower()
        if "@" in clean_target
        else Order.guest_phone.in_(phone_candidates)
    )
    order = db.scalar(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.customizations), selectinload(Order.status_history))
        .where(Order.is_guest.is_(True), Order.order_number == clean_num, where_clause)
    )
    if not order:
        raise HTTPException(status_code=404, detail="No matching guest order found for this order number and contact")
    raw_tok, tok_hash = generate_guest_access_token()
    order.guest_access_token_hash = tok_hash
    db.commit()
    return [serialize_order(db, order, raw_guest_token=raw_tok)]
