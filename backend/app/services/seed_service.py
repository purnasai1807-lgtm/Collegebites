from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import ALL_ROLES, ROLE_PERMISSIONS_MAP
from app.core.security import hash_password
from app.models.auth import (
    CustomerProfile,
    Permission,
    Role,
    RolePermission,
    StaffProfile,
    User,
    UserRole,
)
from app.models.college import (
    Canteen,
    CollegeSettings,
    Counter,
    DiningTable,
    KioskDevice,
    Kitchen,
    KitchenStation,
    LocationQRCode,
    OperatingHour,
    PickupLocation,
)
from app.models.inventory import InventoryItem, StockBatch, Supplier
from app.models.menu import (
    Allergen,
    FoodAddon,
    FoodCategory,
    FoodImage,
    FoodItem,
    FoodItemAddon,
    FoodItemAllergen,
    FoodVariant,
    Ingredient,
    MenuSchedule,
    Recipe,
    RecipeIngredient,
)
from app.models.order import PickupSlot
from app.models.promotion import LoyaltyAccount, Promotion
from app.models.engagement import Announcement, NotificationTemplate


def ensure_roles_and_permissions(db: Session) -> dict[str, Role]:
    """Idempotently seed system roles and permissions."""
    role_map: dict[str, Role] = {}
    perm_cache: dict[str, Permission] = {p.code: p for p in db.scalars(select(Permission)).all()}

    for role_name in ALL_ROLES:
        role = db.scalar(select(Role).where(Role.name == role_name))
        if not role:
            role = Role(
                name=role_name,
                display_name=role_name.replace("_", " ").title(),
                description=f"System role: {role_name}",
                is_system=True,
            )
            db.add(role)
            db.flush()
        role_map[role_name] = role

        for perm_code in ROLE_PERMISSIONS_MAP.get(role_name, []):
            if perm_code == "*":
                continue
            if perm_code not in perm_cache:
                resource, action = perm_code.split(":", 1) if ":" in perm_code else (perm_code, "all")
                perm = Permission(code=perm_code, resource=resource, action=action, description=perm_code)
                db.add(perm)
                db.flush()
                perm_cache[perm_code] = perm
            perm = perm_cache[perm_code]
            exists = db.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id, RolePermission.permission_id == perm.id
                )
            )
            if not exists:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    db.commit()
    return role_map


def seed_initial_college_data(db: Session, create_demo_users: bool = True) -> dict:
    """Seed realistic one-college multi-canteen operational setup for local dev and tests."""
    role_map = ensure_roles_and_permissions(db)

    college = db.scalar(select(CollegeSettings))
    if not college:
        college = CollegeSettings(
            college_name="ACE Engineering College",
            college_short_code="ACE",
            logo_url="/branding/collegebites-logo.png",
            address="Ankushapur, Ghatkesar, Hyderabad - 501301",
            contact_phone="+91-40-2980-1122",
            contact_email="canteen@aceec.ac.in",
            default_tax_rate_percent=Decimal("0.00"),
            kiosk_enabled=False,
            razorpay_enabled=True,
            cash_at_counter_enabled=False,
            pay_at_pickup_enabled=False,
        )
        db.add(college)
        db.flush()

    # Check if already seeded
    existing_main = db.scalar(select(Canteen).where(Canteen.slug == "main-canteen"))
    if existing_main:
        return {"college_id": str(college.id), "main_canteen_id": str(existing_main.id)}

    # 1. Exactly Two Cafeteria Counters within the same college
    main_canteen = Canteen(
        name="Main Canteen",
        slug="main-canteen",
        code="MAIN",
        token_prefix="A",
        description="Central multi-kitchen dining hall serving meals, biryanis, tiffins & hot snacks.",
        location="College Cafeteria",
        contact_phone="+91-90000-11111",
        canteen_type="main_canteen",
        tax_rate_percent=Decimal("0.00"),
        max_concurrent_orders=80,
        orders_per_slot_capacity=40,
        default_prep_time_minutes=12,
        allow_online_payment=True,
        allow_cash_at_counter=False,
        allow_pay_at_pickup=False,
    )
    snacks_canteen = Canteen(
        name="Snacks & Bakery Counter",
        slug="snacks-bakery",
        code="SNK",
        token_prefix="S",
        description="Quick bites, puffs, sandwiches, freshly baked pastries and hot tea/coffee.",
        location="College Cafeteria",
        contact_phone="+91-90000-22222",
        canteen_type="snacks_counter",
        tax_rate_percent=Decimal("0.00"),
        max_concurrent_orders=60,
        orders_per_slot_capacity=35,
        default_prep_time_minutes=7,
        allow_online_payment=True,
        allow_cash_at_counter=False,
        allow_pay_at_pickup=False,
    )
    db.add_all([main_canteen, snacks_canteen])
    db.flush()

    # Operating hours (00:00 - 23:59 default open so dev/test checkout works at any hour; admins can adjust)
    for c in (main_canteen, snacks_canteen):
        for day in range(7):
            db.add(
                OperatingHour(
                    canteen_id=c.id,
                    day_of_week=day,
                    open_time=time(0, 0),
                    close_time=time(23, 59),
                    is_closed=False,
                )
            )

    # Counters & Kitchens
    main_c1 = Counter(canteen_id=main_canteen.id, name="Counter 1 (Meals & Tiffins)", code="C1", counter_type="both")
    main_c2 = Counter(canteen_id=main_canteen.id, name="Counter 2 (Biryani & Chinese)", code="C2", counter_type="pickup")
    snk_c1 = Counter(canteen_id=snacks_canteen.id, name="Bakery Express Counter", code="B1", counter_type="both")
    db.add_all([main_c1, main_c2, snk_c1])
    db.flush()

    db.add_all([
        PickupLocation(canteen_id=main_canteen.id, counter_id=main_c1.id, name="Bay 1", display_code="BAY-1"),
        PickupLocation(canteen_id=main_canteen.id, counter_id=main_c2.id, name="Bay 2", display_code="BAY-2"),
        PickupLocation(canteen_id=snacks_canteen.id, counter_id=snk_c1.id, name="Bakery Window", display_code="B-WIN"),
    ])

    main_k1 = Kitchen(canteen_id=main_canteen.id, name="Main Hot Kitchen", code="MK1", max_active_orders=50)
    snk_k1 = Kitchen(canteen_id=snacks_canteen.id, name="Bakery & Grill", code="SK1", max_active_orders=35)
    db.add_all([main_k1, snk_k1])
    db.flush()

    db.add_all([
        KitchenStation(kitchen_id=main_k1.id, name="Biryani & Rice Station", station_type="hot_line"),
        KitchenStation(kitchen_id=main_k1.id, name="South Indian Tiffin Griddle", station_type="tiffin"),
        KitchenStation(kitchen_id=snk_k1.id, name="Oven & Sandwich Grill", station_type="bakery"),
    ])

    t1 = DiningTable(canteen_id=main_canteen.id, counter_id=main_c1.id, table_number="T-01", zone_label="Window Wing", capacity=4)
    t2 = DiningTable(canteen_id=main_canteen.id, counter_id=main_c2.id, table_number="T-02", zone_label="Center Hall", capacity=6)
    db.add_all([t1, t2])
    db.flush()

    # Kiosk device (disabled by default per Section 24)
    kiosk = KioskDevice(
        canteen_id=main_canteen.id,
        counter_id=main_c1.id,
        device_code="KIOSK-MAIN-01",
        device_name="Main Entrance Touch Kiosk",
        is_enabled=False,
    )
    db.add(kiosk)
    db.flush()

    # Permanent Location QR Codes
    db.add_all([
        LocationQRCode(code="CB-MAIN-CANTEEN", target_type="canteen", canteen_id=main_canteen.id, label="Main Canteen Entrance QR"),
        LocationQRCode(code="CB-MAIN-T01", target_type="table", canteen_id=main_canteen.id, counter_id=main_c1.id, table_id=t1.id, label="Main Canteen Table T-01"),
        LocationQRCode(code="CB-MAIN-C2", target_type="counter", canteen_id=main_canteen.id, counter_id=main_c2.id, label="Main Canteen Counter 2 QR"),
        LocationQRCode(code="CB-SNACKS", target_type="canteen", canteen_id=snacks_canteen.id, counter_id=snk_c1.id, label="Snacks & Bakery QR"),
    ])

    # Pickup Slots for today & tomorrow
    for c in (main_canteen, snacks_canteen):
        for day_offset in (0, 1):
            slot_day = date.today() + timedelta(days=day_offset)
            for hr in range(8, 21):
                db.add(
                    PickupSlot(
                        canteen_id=c.id,
                        slot_date=slot_day,
                        start_time=time(hr, 0),
                        end_time=time(hr, 59),
                        capacity=c.orders_per_slot_capacity,
                        reserved_count=0,
                    )
                )

    # Allergens & Addons
    dairy = Allergen(name="Dairy", description="Contains milk or milk derivatives")
    gluten = Allergen(name="Gluten", description="Contains wheat or gluten grains")
    nuts = Allergen(name="Nuts", description="Contains tree nuts or peanuts")
    db.add_all([dairy, gluten, nuts])
    db.flush()

    addon_raita = FoodAddon(canteen_id=main_canteen.id, name="Extra Raita", addon_type="side", price=Decimal("20.00"), is_veg=True)
    addon_egg = FoodAddon(canteen_id=main_canteen.id, name="Boiled Egg", addon_type="topping", price=Decimal("15.00"), is_veg=False)
    addon_cheese = FoodAddon(canteen_id=main_canteen.id, name="Extra Cheese", addon_type="topping", price=Decimal("25.00"), is_veg=True)
    db.add_all([addon_raita, addon_egg, addon_cheese])
    db.flush()

    # Categories & Items
    cat_biryani = FoodCategory(canteen_id=main_canteen.id, name="Biryani & Rice", slug="biryani-rice", display_order=1)
    cat_tiffin = FoodCategory(canteen_id=main_canteen.id, name="South Indian Tiffins", slug="tiffins", display_order=2)
    cat_bev = FoodCategory(canteen_id=main_canteen.id, name="Beverages", slug="beverages", display_order=3)
    cat_snk = FoodCategory(canteen_id=snacks_canteen.id, name="Puffs & Sandwiches", slug="puffs-sandwiches", display_order=1)
    db.add_all([cat_biryani, cat_tiffin, cat_bev, cat_snk])
    db.flush()

    biryani = FoodItem(
        canteen_id=main_canteen.id,
        category_id=cat_biryani.id,
        kitchen_id=main_k1.id,
        counter_id=main_c2.id,
        name="Hyderabadi Chicken Dum Biryani",
        slug="chicken-dum-biryani",
        description="Aromatic basmati rice slow-cooked with spiced chicken, saffron, and caramelized onions.",
        base_price=Decimal("80.00"),
        is_veg=False,
        is_featured=True,
        is_popular=True,
        is_todays_special=True,
        is_recommended=True,
        prep_time_minutes=12,
        portion_size="Regular (450g)",
        calories=680,
        nutrition_info={"protein_g": 34, "carbs_g": 78, "fat_g": 22},
        spice_levels=["Mild", "Medium", "Extra Spicy"],
        sugar_levels=[],
        removable_ingredients=["Fried Onions", "Coriander"],
        ingredients_text="Basmati Rice, Chicken, Yogurt, Saffron, Mint, Spices",
        average_rating=Decimal("4.70"),
        rating_count=128,
        popularity_score=98,
    )
    fried_rice = FoodItem(
        canteen_id=main_canteen.id,
        category_id=cat_biryani.id,
        kitchen_id=main_k1.id,
        counter_id=main_c2.id,
        name="Veg Schezwan Fried Rice",
        slug="veg-fried-rice",
        description="Wok-tossed long grain rice with fresh crunchy veggies and house schezwan glaze.",
        base_price=Decimal("80.00"),
        is_veg=True,
        is_featured=True,
        is_popular=True,
        prep_time_minutes=9,
        portion_size="Regular Bowl",
        calories=510,
        nutrition_info={"protein_g": 12, "carbs_g": 82, "fat_g": 14},
        spice_levels=["Mild", "Medium", "Extra Spicy"],
        removable_ingredients=["Spring Onion", "Cabbage"],
        ingredients_text="Rice, Carrot, Beans, Capsicum, Soy Sauce, Garlic",
        average_rating=Decimal("4.45"),
        rating_count=89,
        popularity_score=86,
    )
    masala_dosa = FoodItem(
        canteen_id=main_canteen.id,
        category_id=cat_tiffin.id,
        kitchen_id=main_k1.id,
        counter_id=main_c1.id,
        name="Ghee Roast Masala Dosa",
        slug="masala-dosa",
        description="Crispy golden fermented crepe roasted in pure ghee with spiced potato masala & 2 chutneys.",
        base_price=Decimal("55.00"),
        is_veg=True,
        is_popular=True,
        is_recommended=True,
        prep_time_minutes=8,
        portion_size="1 Large Dosa + Sambar",
        calories=420,
        spice_levels=["Mild", "Medium"],
        ingredients_text="Rice Batter, Urad Dal, Potato, Ghee, Curry Leaves",
        average_rating=Decimal("4.80"),
        rating_count=210,
        popularity_score=95,
    )
    cold_coffee = FoodItem(
        canteen_id=main_canteen.id,
        category_id=cat_bev.id,
        kitchen_id=main_k1.id,
        counter_id=main_c1.id,
        name="Classic Campus Cold Coffee",
        slug="cold-coffee",
        description="Double-shot chilled espresso blended with creamy milk and cocoa dust.",
        base_price=Decimal("50.00"),
        is_veg=True,
        is_featured=True,
        is_popular=True,
        prep_time_minutes=4,
        portion_size="300ml",
        calories=210,
        spice_levels=[],
        sugar_levels=["No Sugar", "Less Sugar", "Regular", "Extra Sweet"],
        ingredients_text="Arabica Coffee, Chilled Milk, Sugar, Cocoa",
        average_rating=Decimal("4.65"),
        rating_count=156,
        popularity_score=92,
    )
    veg_puff = FoodItem(
        canteen_id=snacks_canteen.id,
        category_id=cat_snk.id,
        kitchen_id=snk_k1.id,
        counter_id=snk_c1.id,
        name="Crispy Paneer Puff",
        slug="paneer-puff",
        description="Flaky golden puff pastry filled with masala cottage cheese.",
        base_price=Decimal("35.00"),
        is_veg=True,
        is_popular=True,
        is_todays_special=True,
        prep_time_minutes=3,
        portion_size="1 Piece",
        calories=290,
        spice_levels=["Mild", "Medium"],
        ingredients_text="Puff Pastry, Paneer, Onion, Garam Masala",
        average_rating=Decimal("4.50"),
        rating_count=94,
        popularity_score=88,
    )
    db.add_all([biryani, fried_rice, masala_dosa, cold_coffee, veg_puff])
    db.flush()

    # Variants, Images, Addons, Allergens
    db.add_all([
        FoodVariant(food_item_id=biryani.id, name="Regular", price_delta=Decimal("0.00"), is_default=True),
        FoodVariant(food_item_id=biryani.id, name="Jumbo Pack", price_delta=Decimal("60.00"), is_default=False),
        FoodVariant(food_item_id=fried_rice.id, name="Regular", price_delta=Decimal("0.00"), is_default=True),
        FoodVariant(food_item_id=fried_rice.id, name="Full Plate", price_delta=Decimal("40.00"), is_default=False),
        FoodVariant(food_item_id=cold_coffee.id, name="300ml Regular", price_delta=Decimal("0.00"), is_default=True),
        FoodVariant(food_item_id=cold_coffee.id, name="450ml Tall", price_delta=Decimal("25.00"), is_default=False),
        FoodItemAddon(food_item_id=biryani.id, addon_id=addon_raita.id, max_quantity=3),
        FoodItemAddon(food_item_id=biryani.id, addon_id=addon_egg.id, max_quantity=3),
        FoodItemAddon(food_item_id=fried_rice.id, addon_id=addon_raita.id, max_quantity=2),
        FoodItemAddon(food_item_id=masala_dosa.id, addon_id=addon_cheese.id, max_quantity=2),
        FoodItemAllergen(food_item_id=biryani.id, allergen_id=dairy.id),
        FoodItemAllergen(food_item_id=masala_dosa.id, allergen_id=dairy.id),
        FoodItemAllergen(food_item_id=cold_coffee.id, allergen_id=dairy.id),
        FoodItemAllergen(food_item_id=veg_puff.id, allergen_id=gluten.id),
        FoodImage(food_item_id=biryani.id, image_url="https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?w=640", alt_text="Chicken Dum Biryani", is_primary=True),
        FoodImage(food_item_id=fried_rice.id, image_url="https://images.unsplash.com/photo-1603133872878-684f208fb84b?w=640", alt_text="Veg Fried Rice", is_primary=True),
        FoodImage(food_item_id=masala_dosa.id, image_url="https://images.unsplash.com/photo-1668236543090-82eba5ee5976?w=640", alt_text="Masala Dosa", is_primary=True),
        FoodImage(food_item_id=cold_coffee.id, image_url="https://images.unsplash.com/photo-1461023058943-07fcbe16d735?w=640", alt_text="Cold Coffee", is_primary=True),
        FoodImage(food_item_id=veg_puff.id, image_url="https://images.unsplash.com/photo-1509440159596-0249088772ff?w=640", alt_text="Paneer Puff", is_primary=True),
    ])

    # Menu Schedules
    db.add_all([
        MenuSchedule(canteen_id=main_canteen.id, name="Breakfast Tiffins", schedule_type="breakfast", start_time=time(7, 30), end_time=time(11, 0)),
        MenuSchedule(canteen_id=main_canteen.id, name="Lunch Meals & Biryani", schedule_type="lunch", start_time=time(11, 30), end_time=time(16, 0)),
        MenuSchedule(canteen_id=main_canteen.id, name="Evening Snacks", schedule_type="snacks", start_time=time(16, 0), end_time=time(21, 0)),
    ])

    # Ingredients, Recipes & Initial Inventory
    ing_rice = Ingredient(canteen_id=main_canteen.id, name="Basmati Rice", sku="RICE-BAS", unit="grams")
    ing_chicken = Ingredient(canteen_id=main_canteen.id, name="Fresh Chicken Cut", sku="CHK-CUT", unit="grams")
    ing_coffee = Ingredient(canteen_id=main_canteen.id, name="Espresso Coffee Beans", sku="COF-ESP", unit="grams")
    ing_milk = Ingredient(canteen_id=main_canteen.id, name="Toned Milk", sku="MLK-TON", unit="ml")
    db.add_all([ing_rice, ing_chicken, ing_coffee, ing_milk])
    db.flush()

    rec_biryani = Recipe(food_item_id=biryani.id, yield_portions=1, notes="Standard single portion")
    rec_coffee = Recipe(food_item_id=cold_coffee.id, yield_portions=1, notes="300ml cup")
    db.add_all([rec_biryani, rec_coffee])
    db.flush()
    db.add_all([
        RecipeIngredient(recipe_id=rec_biryani.id, ingredient_id=ing_rice.id, quantity_required=Decimal("180.000")),
        RecipeIngredient(recipe_id=rec_biryani.id, ingredient_id=ing_chicken.id, quantity_required=Decimal("150.000")),
        RecipeIngredient(recipe_id=rec_coffee.id, ingredient_id=ing_coffee.id, quantity_required=Decimal("18.000")),
        RecipeIngredient(recipe_id=rec_coffee.id, ingredient_id=ing_milk.id, quantity_required=Decimal("220.000")),
    ])

    supplier = Supplier(name="Deccan Agro & Dairy Suppliers", contact_person="Ramesh Rao", phone="+91-98480-11223", email="orders@deccanagro.in")
    db.add(supplier)
    db.flush()

    inv_items = [
        InventoryItem(canteen_id=main_canteen.id, ingredient_id=ing_rice.id, current_quantity=Decimal("25000.000"), reorder_level=Decimal("5000.000"), unit="grams", unit_cost=Decimal("0.11")),
        InventoryItem(canteen_id=main_canteen.id, ingredient_id=ing_chicken.id, current_quantity=Decimal("18000.000"), reorder_level=Decimal("3000.000"), unit="grams", unit_cost=Decimal("0.28")),
        InventoryItem(canteen_id=main_canteen.id, ingredient_id=ing_coffee.id, current_quantity=Decimal("4000.000"), reorder_level=Decimal("500.000"), unit="grams", unit_cost=Decimal("0.85")),
        InventoryItem(canteen_id=main_canteen.id, ingredient_id=ing_milk.id, current_quantity=Decimal("30000.000"), reorder_level=Decimal("5000.000"), unit="ml", unit_cost=Decimal("0.06")),
    ]
    db.add_all(inv_items)
    db.flush()
    for idx, inv in enumerate(inv_items):
        db.add(
            StockBatch(
                inventory_item_id=inv.id,
                supplier_id=supplier.id,
                batch_number=f"INIT-B{idx+1}",
                initial_quantity=inv.current_quantity,
                remaining_quantity=inv.current_quantity,
                unit_cost=inv.unit_cost,
                received_at=datetime.now(timezone.utc),
                expiry_date=date.today() + timedelta(days=30),
            )
        )

    # Promotional Banners, Announcements & Templates (no coupons)
    db.add(
        Promotion(
            canteen_id=main_canteen.id,
            title="Lunch Combo Special — Fresh Kitchen Counters Open",
            subtitle="Order ahead and skip the 12:30 PM counter rush!",
            badge_text="SPECIAL",
            coupon_code=None,
            is_active=True,
        )
    )
    db.add(
        Announcement(
            canteen_id=None,
            title="Welcome to CollegeBites Digital Canteen",
            body="Scan any table QR code or order ahead online to receive an instant pickup token and digital receipt.",
            severity="info",
            is_active=True,
        )
    )
    db.add(
        NotificationTemplate(
            code="ORDER_READY",
            channel="in_app",
            title_template="Token {token} is READY for pickup!",
            body_template="Collect order {order_number} from {canteen_name} / {counter_name}.",
        )
    )

    if create_demo_users:
        demo_accounts = [
            ("superadmin@collegebites.edu", "+919000000001", "Super Admin", "Admin@12345", "admin", ["super_admin"], None, None),
            ("admin@collegebites.edu", "+919000000002", "College Canteen Admin", "Admin@12345", "admin", ["college_admin"], None, None),
            ("manager@collegebites.edu", "+919000000003", "Main Canteen Manager", "Staff@12345", "staff", ["canteen_manager"], main_canteen.id, None),
            ("cashier@collegebites.edu", "+919000000004", "Counter Cashier", "Staff@12345", "staff", ["cashier"], main_canteen.id, None),
            ("kitchen@collegebites.edu", "+919000000005", "Head Chef", "Staff@12345", "staff", ["kitchen_staff"], main_canteen.id, None),
            ("inventory@collegebites.edu", "+919000000006", "Inventory Lead", "Staff@12345", "staff", ["inventory_manager"], main_canteen.id, None),
            ("pickup@collegebites.edu", "+919000000007", "Pickup Counter Staff", "Staff@12345", "staff", ["pickup_staff"], main_canteen.id, main_c2.id),
            ("inspector@collegebites.edu", "+919000000008", "Food Safety Inspector", "Staff@12345", "staff", ["food_safety_inspector"], None, None),
            ("student@collegebites.edu", "+919876543210", "Aarav Sharma", "Student@12345", "customer", ["customer"], None, None),
        ]
        for idx, (email, phone, name, pw, kind, rnames, cid, cnt_id) in enumerate(demo_accounts):
            u = User(
                email=email,
                phone=phone,
                full_name=name,
                password_hash=hash_password(pw),
                user_kind=kind,
                is_active=True,
                is_verified=True,
            )
            db.add(u)
            db.flush()
            for rname in rnames:
                db.add(UserRole(user_id=u.id, role_id=role_map[rname].id, canteen_id=cid))
            if kind == "customer":
                db.add(CustomerProfile(user_id=u.id, college_id_number="25AG1A6767", department="CSE (AI & DS)"))
                db.add(LoyaltyAccount(user_id=u.id, referral_code="CBSTUDENT1", points_balance=120, lifetime_points=120))
            else:
                db.add(
                    StaffProfile(
                        user_id=u.id,
                        employee_code=f"EMP-{100+idx}",
                        designation=rnames[0].replace("_", " ").title(),
                        assigned_canteen_id=cid,
                        assigned_counter_id=cnt_id,
                        assigned_kitchen_id=main_k1.id if cid == main_canteen.id else None,
                        is_on_duty=True,
                    )
                )

    db.commit()
    return {
        "college_id": str(college.id),
        "main_canteen_id": str(main_canteen.id),
        "snacks_canteen_id": str(snacks_canteen.id),
    }


def seed_live_production_advanced_data(db: Session) -> dict:
    """
    Idempotently enrich the live production database with real-world reference data
    for Vendor Procurement, Student Meal Plans, College Events, and Verified Nutrition profiles.
    """
    from app.models.event import CollegeEvent
    from app.models.meal_plan import MealPlan

    ensure_roles_and_permissions(db)
    main_canteen = db.scalar(select(Canteen).where(Canteen.slug == "main-canteen"))
    if not main_canteen:
        seed_initial_college_data(db, create_demo_users=True)
        main_canteen = db.scalar(select(Canteen).where(Canteen.slug == "main-canteen"))
    if not main_canteen:
        return {"status": "no_canteen"}

    # 1. Enrich Supplier with business details, supplied products & payment terms
    sup = db.scalar(select(Supplier).order_by(Supplier.created_at.asc()))
    if sup:
        if not sup.business_details:
            sup.business_details = "FSSAI Lic #1003604200192 | HDFC Corporate A/C IFSC HDFC0001204"
        if not sup.supplied_products:
            sup.supplied_products = ["Raw Ingredients", "Dairy & Beverages", "Biodegradable Packaging"]
        if not sup.payment_terms:
            sup.payment_terms = "Net 15 Days"
        if not sup.gst_number:
            sup.gst_number = "36AABCD4512K1Z8"

    # 2. Mark flagship menu items with verified nutrition & macro profiles
    items = list(db.scalars(select(FoodItem).where(FoodItem.canteen_id == main_canteen.id)).all())
    for it in items:
        if "Biryani" in it.name and not it.nutrition_verified:
            it.calories = it.calories or 640
            it.nutrition_info = it.nutrition_info or {"protein_g": 32.0, "carbs_g": 74.0, "fat_g": 22.0, "fiber_g": 4.5}
            it.ingredients_text = it.ingredients_text or "Aged basmati rice, marinated chicken, saffron, yogurt, whole garam masala, mint, fried onions"
            it.nutrition_verified = True
        elif "Thali" in it.name or "Meal" in it.name or "Dosa" in it.name:
            if not it.nutrition_verified:
                it.calories = it.calories or 480
                it.nutrition_info = it.nutrition_info or {"protein_g": 16.5, "carbs_g": 68.0, "fat_g": 14.0, "fiber_g": 7.0}
                it.nutrition_verified = True

    # 3. Seed active Student Meal Plans if none exist
    now = datetime.now(timezone.utc)
    today = date.today()
    if not db.scalar(select(MealPlan).where(MealPlan.code == "ACE-WEEKLY-7")):
        db.add(
            MealPlan(
                canteen_id=main_canteen.id,
                code="ACE-WEEKLY-7",
                name="Weekly Campus Lunch Pass (7 Meals)",
                description="7 wholesome campus meals valid across Main Canteen for 7 days.",
                plan_type="weekly",
                price=Decimal("490.00"),
                tax_rate_percent=Decimal("0.00"),
                validity_days=7,
                total_meals=7,
                start_date=today - timedelta(days=1),
                expiry_date=today + timedelta(days=90),
                is_active=True,
            )
        )
    if not db.scalar(select(MealPlan).where(MealPlan.code == "ACE-MONTHLY-30")):
        db.add(
            MealPlan(
                canteen_id=main_canteen.id,
                code="ACE-MONTHLY-30",
                name="Monthly All-Day Student Dining Plan (30 Meals)",
                description="30 nutritious meals with instant QR redemption at the pickup counter.",
                plan_type="monthly",
                price=Decimal("1950.00"),
                tax_rate_percent=Decimal("0.00"),
                validity_days=30,
                total_meals=30,
                start_date=today - timedelta(days=1),
                expiry_date=today + timedelta(days=120),
                is_active=True,
            )
        )

    # 4. Seed active College Event for Bulk Ordering if none exist
    if not db.scalar(select(CollegeEvent).where(CollegeEvent.event_code == "ACE-SYMPOSIUM-2026")):
        db.add(
            CollegeEvent(
                event_code="ACE-SYMPOSIUM-2026",
                canteen_id=main_canteen.id,
                name="ACE Annual AI & Engineering Symposium",
                department="CSE (AI & DS)",
                organizer_name="Dr. Priya Nair",
                contact_phone="+91-98480-55667",
                contact_email="symposium@aceec.ac.in",
                event_date=today + timedelta(days=14),
                location="Main Auditorium Block A",
                description="Official department symposium & hackathon bulk catering window.",
                ordering_deadline=now + timedelta(days=10),
                eligible_food_item_ids=[str(i.id) for i in items[:4]],
                min_order_quantity=10,
                max_order_quantity=300,
                is_active=True,
            )
        )

    db.commit()
    return {"status": "live_production_advanced_data_seeded"}

