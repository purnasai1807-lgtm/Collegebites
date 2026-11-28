from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import NS_AUTH, cache_manager
from app.core.database import get_db
from app.core.security import decode_token
from app.models.auth import Role, RolePermission, Permission, SessionRecord, StaffProfile, User, UserPermission, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

# Role constants matching Section 3
ROLE_SUPER_ADMIN = "super_admin"
ROLE_COLLEGE_ADMIN = "college_admin"
ROLE_CANTEEN_MANAGER = "canteen_manager"
ROLE_CASHIER = "cashier"
ROLE_KITCHEN_STAFF = "kitchen_staff"
ROLE_INVENTORY_MANAGER = "inventory_manager"
ROLE_PICKUP_STAFF = "pickup_staff"
ROLE_FOOD_SAFETY_INSPECTOR = "food_safety_inspector"
ROLE_CUSTOMER = "customer"

ALL_ROLES = [
    ROLE_SUPER_ADMIN,
    ROLE_COLLEGE_ADMIN,
    ROLE_CANTEEN_MANAGER,
    ROLE_CASHIER,
    ROLE_KITCHEN_STAFF,
    ROLE_INVENTORY_MANAGER,
    ROLE_PICKUP_STAFF,
    ROLE_FOOD_SAFETY_INSPECTOR,
    ROLE_CUSTOMER,
]

ROLE_PERMISSIONS_MAP: dict[str, list[str]] = {
    ROLE_SUPER_ADMIN: ["*"],
    ROLE_COLLEGE_ADMIN: [
        "college:manage",
        "canteen:manage",
        "menu:manage",
        "staff:manage",
        "staff:view",
        "staff:shift_manage",
        "staff:leave_review",
        "staff:task_manage",
        "staff:activity_view",
        "staff:attendance_self",
        "role:manage",
        "customer:manage",
        "order:view_all",
        "order:manage",
        "payment:view",
        "payment:reconcile",
        "inventory:manage",
        "qr:manage",
        "queue:manage",
        "notification:manage",
        "announcement:manage",
        "promotion:manage",
        "report:view",
        "support:manage",
        "kiosk:manage",
        "audit:view",
        "qr:website_manage",
        "security:view",
        "security:manage",
        "backup:manage",
        "supplier:manage",
        "purchase_order:manage",
        "purchase_order:approve",
        "vendor_payment:manage",
        "meal_plan:manage",
        "meal_plan:redeem",
        "event:manage",
        "event:approve",
        "invoice:view_all",
        "control_center:view",
        "food_safety:manage",
        "food_safety:view",
        "traceability:manage",
        "traceability:view",
        "production:manage",
        "production:view",
        "reorder:manage",
        "reorder:approve",
        "forecast:view",
        "forecast:train",
        "ai_assistant:use",
    ],
    ROLE_CANTEEN_MANAGER: [
        "canteen:manage_assigned",
        "menu:manage",
        "order:view_canteen",
        "order:manage",
        "kitchen:manage",
        "staff:manage_canteen",
        "staff:view",
        "staff:shift_manage",
        "staff:leave_review",
        "staff:task_manage",
        "staff:activity_view",
        "staff:attendance_self",
        "inventory:manage",
        "supplier:manage",
        "purchase_order:manage",
        "purchase_order:approve",
        "vendor_payment:manage",
        "meal_plan:manage",
        "meal_plan:redeem",
        "event:manage",
        "event:approve",
        "invoice:view_canteen",
        "control_center:view",
        "queue:manage",
        "report:view_canteen",
        "support:view",
        "qr:manage",
        "security:view",
        "notification:manage",
        "food_safety:manage",
        "food_safety:view",
        "traceability:manage",
        "traceability:view",
        "production:manage",
        "production:view",
        "reorder:manage",
        "reorder:approve",
        "forecast:view",
        "forecast:train",
        "ai_assistant:use",
    ],
    ROLE_CASHIER: [
        "pos:use",
        "order:create_walkin",
        "order:view_canteen",
        "payment:accept_counter",
        "receipt:print",
        "receipt:reprint",
        "pickup:verify",
        "pickup:handover",
        "meal_plan:redeem",
        "shift:manage_own",
        "staff:attendance_self",
    ],
    ROLE_KITCHEN_STAFF: [
        "kitchen:view",
        "kitchen:update_order",
        "kitchen:report_delay",
        "kitchen:report_unavailable",
        "wastage:record",
        "staff:attendance_self",
        "production:manage",
        "production:view",
        "food_safety:view",
        "food_safety:manage",
        "traceability:view",
        "ai_assistant:use",
    ],
    ROLE_INVENTORY_MANAGER: [
        "inventory:manage",
        "supplier:manage",
        "purchase_order:manage",
        "vendor_payment:manage",
        "wastage:record",
        "menu:manage_inventory",
        "staff:attendance_self",
        "traceability:manage",
        "traceability:view",
        "reorder:manage",
        "forecast:view",
        "food_safety:view",
        "ai_assistant:use",
    ],
    ROLE_PICKUP_STAFF: [
        "pickup:verify",
        "pickup:handover",
        "meal_plan:redeem",
        "order:view_canteen",
        "staff:attendance_self",
    ],
    ROLE_FOOD_SAFETY_INSPECTOR: [
        "food_safety:manage",
        "food_safety:view",
        "traceability:manage",
        "traceability:view",
        "production:view",
        "staff:attendance_self",
        "ai_assistant:use",
    ],
    ROLE_CUSTOMER: [
        "order:create",
        "order:view_own",
        "receipt:view_own",
        "invoice:view_own",
        "meal_plan:subscribe",
        "event:order_bulk",
        "review:create",
        "support:create_own",
        "profile:manage_own",
    ],
}


@dataclass
class AuthenticatedPrincipal:
    user: User
    session_id: UUID
    roles: set[str]
    permissions: set[str]
    assigned_canteen_id: Optional[UUID]
    assigned_counter_id: Optional[UUID] = None

    def has_role(self, *role_names: str) -> bool:
        return bool(self.roles.intersection(role_names))

    def has_permission(self, permission: str) -> bool:
        if "*" in self.permissions or ROLE_SUPER_ADMIN in self.roles:
            return True
        return permission in self.permissions


def load_users_roles_and_permissions_batch(
    db: Session, user_ids: list[UUID]
) -> dict[UUID, tuple[set[str], set[str], Optional[UUID]]]:
    """Batch-load roles, effective permissions, and assigned canteen for many users in 4 queries total."""
    if not user_ids:
        return {}
    unique_ids = list(dict.fromkeys(user_ids))

    role_rows = db.execute(
        select(UserRole.user_id, Role.name, Role.id, UserRole.canteen_id)
        .join(Role, UserRole.role_id == Role.id)
        .where(UserRole.user_id.in_(unique_ids))
    ).all()

    roles_by_user: dict[UUID, set[str]] = {uid: set() for uid in unique_ids}
    role_ids_by_user: dict[UUID, set[UUID]] = {uid: set() for uid in unique_ids}
    canteen_by_user: dict[UUID, Optional[UUID]] = {uid: None for uid in unique_ids}
    all_role_ids: set[UUID] = set()
    for uid, rname, rid, cid in role_rows:
        roles_by_user[uid].add(rname)
        role_ids_by_user[uid].add(rid)
        all_role_ids.add(rid)
        if canteen_by_user[uid] is None and cid is not None:
            canteen_by_user[uid] = cid

    missing_canteen_uids = [uid for uid, cid in canteen_by_user.items() if cid is None]
    if missing_canteen_uids:
        for sp_uid, sp_cid in db.execute(
            select(StaffProfile.user_id, StaffProfile.assigned_canteen_id).where(
                StaffProfile.user_id.in_(missing_canteen_uids),
                StaffProfile.assigned_canteen_id.is_not(None),
            )
        ).all():
            canteen_by_user[sp_uid] = sp_cid

    perms_by_role: dict[UUID, set[str]] = {}
    if all_role_ids:
        for rid, code in db.execute(
            select(RolePermission.role_id, Permission.code)
            .join(Permission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id.in_(list(all_role_ids)))
        ).all():
            perms_by_role.setdefault(rid, set()).add(code)

    user_perm_overrides: dict[UUID, list[tuple[str, bool]]] = {}
    for uid, code, granted in db.execute(
        select(UserPermission.user_id, Permission.code, UserPermission.granted)
        .join(Permission, Permission.id == UserPermission.permission_id)
        .where(UserPermission.user_id.in_(unique_ids))
    ).all():
        user_perm_overrides.setdefault(uid, []).append((code, bool(granted)))

    out: dict[UUID, tuple[set[str], set[str], Optional[UUID]]] = {}
    for uid in unique_ids:
        roles = roles_by_user[uid]
        if ROLE_SUPER_ADMIN in roles:
            out[uid] = (roles, {"*"}, canteen_by_user[uid])
            continue
        perms: set[str] = set()
        for rid in role_ids_by_user[uid]:
            perms.update(perms_by_role.get(rid, ()))
        for rname in roles:
            perms.update(ROLE_PERMISSIONS_MAP.get(rname, []))
        for code, granted in user_perm_overrides.get(uid, ()):
            if granted:
                perms.add(code)
            else:
                perms.discard(code)
        out[uid] = (roles, perms, canteen_by_user[uid])
    return out


def load_user_roles_and_permissions(db: Session, user_id: UUID) -> tuple[set[str], set[str], Optional[UUID]]:
    cache_ns = f"{NS_AUTH}:u:{user_id}"
    hit, cached = cache_manager.get_json(cache_ns, "rbac", l1_ttl=2.0)
    if hit and isinstance(cached, dict):
        cid_raw = cached.get("assigned_canteen_id")
        return (
            set(cached.get("roles") or ()),
            set(cached.get("permissions") or ()),
            UUID(cid_raw) if cid_raw else None,
        )

    role_rows = db.execute(
        select(Role.name, Role.id, UserRole.canteen_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    ).all()
    roles = {row[0] for row in role_rows}
    assigned_canteen_id = next((row[2] for row in role_rows if row[2] is not None), None)

    if assigned_canteen_id is None:
        staff_prof = db.scalar(select(StaffProfile).where(StaffProfile.user_id == user_id))
        if staff_prof:
            assigned_canteen_id = staff_prof.assigned_canteen_id

    if ROLE_SUPER_ADMIN in roles:
        cache_manager.set_json(
            cache_ns,
            "rbac",
            {
                "roles": sorted(roles),
                "permissions": ["*"],
                "assigned_canteen_id": str(assigned_canteen_id) if assigned_canteen_id else None,
            },
            ttl_seconds=60,
            l1_ttl=2.0,
        )
        return roles, {"*"}, assigned_canteen_id

    role_ids = [row[1] for row in role_rows]
    perms: set[str] = set()
    if role_ids:
        perm_rows = db.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id.in_(role_ids))
        ).all()
        perms.update(perm_rows)

    for r in roles:
        perms.update(ROLE_PERMISSIONS_MAP.get(r, []))

    user_perm_rows = db.execute(
        select(Permission.code, UserPermission.granted)
        .join(Permission, Permission.id == UserPermission.permission_id)
        .where(UserPermission.user_id == user_id)
    ).all()
    for code, granted in user_perm_rows:
        if granted:
            perms.add(code)
        else:
            perms.discard(code)

    cache_manager.set_json(
        cache_ns,
        "rbac",
        {
            "roles": sorted(roles),
            "permissions": sorted(perms),
            "assigned_canteen_id": str(assigned_canteen_id) if assigned_canteen_id else None,
        },
        ttl_seconds=60,
        l1_ttl=2.0,
    )
    return roles, perms, assigned_canteen_id


def get_optional_principal(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[AuthenticatedPrincipal]:
    if not credentials or not credentials.credentials:
        return None
    token = credentials.credentials
    try:
        state = request.scope.setdefault("state", {})
        if state.get("jwt_raw") == token and isinstance(state.get("jwt_payload"), dict):
            payload = state["jwt_payload"]
        else:
            payload = decode_token(token)
            state["jwt_raw"] = token
            state["jwt_payload"] = payload
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token") from exc

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    try:
        user_id = UUID(payload["sub"])
        session_id = UUID(payload["sid"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token claims") from exc

    now = datetime.now(timezone.utc)
    sess_ns = f"{NS_AUTH}:s:{session_id}"
    sess_hit, sess_cached = cache_manager.get_json(sess_ns, "valid", l1_ttl=2.0)
    if sess_hit and isinstance(sess_cached, dict):
        if sess_cached.get("revoked") or sess_cached.get("user_id") != str(user_id):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")
        exp_dt = datetime.fromisoformat(sess_cached["expires_at"])
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if exp_dt <= now:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")
    else:
        session_rec = db.get(SessionRecord, session_id)
        if not session_rec or session_rec.revoked_at is not None or session_rec.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")
        expires_at = session_rec.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or revoked")
        cache_manager.set_json(
            sess_ns,
            "valid",
            {"user_id": str(user_id), "revoked": False, "expires_at": expires_at.isoformat()},
            ttl_seconds=30,
            l1_ttl=2.0,
        )

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account inactive or missing")

    roles, permissions, assigned_canteen_id = load_user_roles_and_permissions(db, user.id)
    assigned_counter_id: Optional[UUID] = None
    if not roles.intersection({ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER}) and roles.intersection(
        {ROLE_CASHIER, ROLE_KITCHEN_STAFF, ROLE_PICKUP_STAFF}
    ):
        assigned_counter_id = db.scalar(select(StaffProfile.assigned_counter_id).where(StaffProfile.user_id == user.id))
    return AuthenticatedPrincipal(
        user=user,
        session_id=session_id,
        roles=roles,
        permissions=permissions,
        assigned_canteen_id=assigned_canteen_id,
        assigned_counter_id=assigned_counter_id,
    )


def get_current_principal(
    principal: Optional[AuthenticatedPrincipal] = Depends(get_optional_principal),
) -> AuthenticatedPrincipal:
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return principal


def require_roles(*allowed_roles: str):
    def dependency(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
        if ROLE_SUPER_ADMIN in principal.roles or principal.has_role(*allowed_roles):
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires one of roles: {', '.join(allowed_roles)}",
        )

    return dependency


def require_role_or_permission(allowed_roles: Iterable[str], *required_permissions: str):
    allowed = tuple(allowed_roles)

    def dependency(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
        if ROLE_SUPER_ADMIN in principal.roles or "*" in principal.permissions:
            return principal
        if principal.has_role(*allowed) or any(principal.has_permission(p) for p in required_permissions):
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires permission ({', '.join(required_permissions)}) or role ({', '.join(allowed)})",
        )

    return dependency


def require_permissions(*required_permissions: str):
    def dependency(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
        if "*" in principal.permissions or ROLE_SUPER_ADMIN in principal.roles:
            return principal
        if any(principal.has_permission(p) for p in required_permissions):
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {', '.join(required_permissions)}",
        )

    return dependency


def enforce_canteen_scope(principal: AuthenticatedPrincipal, canteen_id: Optional[UUID]) -> None:
    if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        return
    if principal.has_role(ROLE_FOOD_SAFETY_INSPECTOR) and principal.assigned_canteen_id is None:
        return
    if not principal.assigned_canteen_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff user has no assigned canteen",
        )
    if canteen_id and principal.assigned_canteen_id != canteen_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff user is not authorized for this canteen",
        )


def scoped_canteen_for_principal(principal: AuthenticatedPrincipal, requested_canteen_id: Optional[UUID]) -> Optional[UUID]:
    """Resolve effective canteen filter, locking non-college-admin staff to their assigned canteen."""
    if principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN):
        return requested_canteen_id
    if principal.has_role(ROLE_FOOD_SAFETY_INSPECTOR) and principal.assigned_canteen_id is None:
        return requested_canteen_id
    enforce_canteen_scope(principal, requested_canteen_id)
    return principal.assigned_canteen_id


def scoped_counter_for_principal(principal: Optional[AuthenticatedPrincipal]) -> Optional[UUID]:
    """Return assigned counter lock for counter-bound operational staff (None if admin/manager/canteen-wide)."""
    if not principal or principal.has_role(ROLE_SUPER_ADMIN, ROLE_COLLEGE_ADMIN, ROLE_CANTEEN_MANAGER):
        return None
    return principal.assigned_counter_id


def client_ip_from_request(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
