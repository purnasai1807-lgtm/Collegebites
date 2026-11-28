"""Regression tests for Vercel Fluid CPU, Edge CDN caching, privacy headers, pagination,
pure-Python ML pickup prediction, and additive DB index migration.
"""
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.services.campus_intelligence_service import _fit_ridge_pure, _predict_ridge_pure
from tests.conftest import login_as


def test_public_endpoints_emit_edge_cdn_headers_and_support_304(client: TestClient):
    """Non-personalized public endpoints must expose public s-maxage, ETag, and return 304 on match."""
    r_canteens = client.get("/api/v1/canteens")
    assert r_canteens.status_code == 200
    assert "public" in r_canteens.headers.get("cache-control", "")
    assert "s-maxage=" in r_canteens.headers.get("cache-control", "")
    etag = r_canteens.headers.get("etag")
    assert etag and etag.startswith('W/"')

    # Conditional 304 Not Modified skips JSON payload transfer
    r_304 = client.get("/api/v1/canteens", headers={"If-None-Match": etag})
    assert r_304.status_code == 304
    assert r_304.content == b""

    canteen_id = r_canteens.json()[0]["id"]
    public_urls = [
        "/api/v1/canteens/college",
        f"/api/v1/menus/canteens/{canteen_id}/items",
        "/api/v1/menus/allergens",
        "/api/v1/campus-intelligence/crowd/live?days=7",
        f"/api/v1/campus-intelligence/pickup-predictions/{canteen_id}",
        f"/api/v1/campus-intelligence/menu-availability/{canteen_id}",
        "/api/v1/campus-intelligence/seating",
        "/api/v1/notifications/announcements",
        "/api/v1/payments/razorpay/config",
    ]
    for url in public_urls:
        resp = client.get(url)
        assert resp.status_code == 200, f"{url} returned {resp.status_code}: {resp.text}"
        cc = resp.headers.get("cache-control", "")
        assert "public" in cc and "s-maxage=" in cc, f"{url} missing public s-maxage: {cc}"
        assert resp.headers.get("etag"), f"{url} missing ETag"


def test_personalized_and_sensitive_endpoints_strictly_private_no_store(client: TestClient):
    """Personalized order, cart, auth, notification, and admin/staff endpoints must NEVER be publicly cached."""
    stu = login_as(client, "student@collegebites.edu", "Student@12345")
    adm = login_as(client, "admin@collegebites.edu", "Admin@12345")
    canteen_id = client.get("/api/v1/canteens").json()[0]["id"]

    private_cases = [
        ("GET", "/api/v1/auth/me", stu["headers"]),
        ("GET", "/api/v1/orders/my", stu["headers"]),
        ("GET", "/api/v1/orders/my-orders", stu["headers"]),
        ("GET", "/api/v1/tokens/receipts/my", stu["headers"]),
        ("GET", f"/api/v1/carts?canteen_id={canteen_id}", stu["headers"]),
        ("GET", "/api/v1/customers/profile", stu["headers"]),
        ("GET", "/api/v1/notifications/my", stu["headers"]),
        ("GET", "/api/v1/notifications/unread-count", stu["headers"]),
        ("GET", f"/api/v1/pickup/board/{canteen_id}", adm["headers"]),
        ("GET", "/api/v1/pickup/token-board", adm["headers"]),
        ("GET", "/api/v1/command-center/unified-status", adm["headers"]),
        ("GET", "/api/v1/command-center/cafeteria-map?hours=24", adm["headers"]),
        ("GET", "/api/v1/admin/orders?limit=10", adm["headers"]),
    ]
    for method, url, hdrs in private_cases:
        resp = client.request(method, url, headers=hdrs)
        assert resp.status_code == 200, f"{url} returned {resp.status_code}: {resp.text}"
        cc = resp.headers.get("cache-control", "").lower()
        assert "private" in cc and "no-store" in cc, f"{url} MUST be private, no-store; got '{cc}'"
        assert "s-maxage" not in cc and "public" not in cc, f"{url} leaked public cache directive: '{cc}'"


def test_menu_and_command_center_pagination_support(client: TestClient):
    """Paginated list endpoints respect limit/offset cleanly without breaking unpaginated defaults."""
    adm = login_as(client, "admin@collegebites.edu", "Admin@12345")
    canteen_id = client.get("/api/v1/canteens").json()[0]["id"]

    all_items = client.get(f"/api/v1/menus/canteens/{canteen_id}/items").json()
    assert len(all_items) >= 3
    page1 = client.get(f"/api/v1/menus/canteens/{canteen_id}/items?limit=2&offset=0").json()
    page2 = client.get(f"/api/v1/menus/canteens/{canteen_id}/items?limit=2&offset=2").json()
    assert len(page1) == 2
    assert len(page2) >= 1
    assert {i["id"] for i in page1}.isdisjoint({i["id"] for i in page2})

    # Offset/limit accepted on campus-intel & command-center listing routes
    assert client.get("/api/v1/campus-intelligence/tray-verification/history?limit=5&offset=0", headers=adm["headers"]).status_code == 200
    assert client.get("/api/v1/campus-intelligence/timetables?limit=5&offset=0", headers=adm["headers"]).status_code == 200
    assert client.get("/api/v1/command-center/incidents?limit=5&offset=0", headers=adm["headers"]).status_code == 200
    assert client.get("/api/v1/command-center/executions?limit=5&offset=0", headers=adm["headers"]).status_code == 200
    assert client.get("/api/v1/command-center/simulations?limit=5&offset=0", headers=adm["headers"]).status_code == 200


def test_pure_python_ridge_regression_prediction_without_numpy_or_sklearn():
    """Verify pure-Python 4x4 Ridge solver produces accurate predictions with zero numpy/sklearn import overhead."""
    # Synthetic linear data: y = 3 + 1.5*units + 0.8*est + 0.0*hour + 0.5*backlog
    xs = []
    ys = []
    for u in (1, 2, 3, 4):
        for e in (5, 10, 15):
            for h in (9, 13):
                for b in (0, 4, 8):
                    xs.append([float(u), float(e), float(h), float(b)])
                    ys.append(3.0 + 1.5 * u + 0.8 * e + 0.5 * b)
    model = _fit_ridge_pure(xs, ys, alpha=1.0)
    assert model is not None
    weights, intercept = model
    pred = _predict_ridge_pure(weights, intercept, [2.0, 10.0, 12.0, 4.0])
    # True target = 3 + 3 + 8 + 2 = 16.0
    assert abs(pred - 16.0) < 0.5, f"Expected ~16.0, got {pred}"


def test_alembic_cpu_perf_index_migration_upgrade_and_downgrade(tmp_path: Path):
    """Verify additive migration b2c3d4e5f6a7 upgrades and downgrades cleanly."""
    from sqlalchemy import create_engine
    from app.models import Base

    db_path = tmp_path / "alembic_cpu_test.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    eng = create_engine(db_url)
    Base.metadata.create_all(bind=eng)
    eng.dispose()

    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url

    stamp = subprocess.run(
        [sys.executable, "-m", "alembic", "stamp", "a1b2c3d4e5f6"],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    assert stamp.returncode == 0, f"alembic stamp failed:\n{stamp.stdout}\n{stamp.stderr}"

    up = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    assert up.returncode == 0, f"alembic upgrade head failed:\n{up.stdout}\n{up.stderr}"

    down = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "a1b2c3d4e5f6"],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    assert down.returncode == 0, f"alembic downgrade failed:\n{down.stdout}\n{down.stderr}"

    up2 = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
    )
    assert up2.returncode == 0, f"re-upgrade failed:\n{up2.stdout}\n{up2.stderr}"
