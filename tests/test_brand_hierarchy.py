"""
Tests for the 3-level brand hierarchy: Customer → Brand → Product.

Covers:
1. CustomerProfile CRUD via API
2. BrandProfile linked to Customer
3. ProductProfile linked to Project
4. Tenant isolation across all three models
"""

import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.tenant import Tenant
from pipeline.models.user import User
from pipeline.models.project import Project
from pipeline.models.customer_profile import CustomerProfile
from pipeline.models.product_profile import ProductProfile
from pipeline.models.brand_profile import BrandProfile
from pipeline.web.app import create_app

AIP_TEST_DB_URL = os.environ.get(
    "AIP_TEST_DB_URL", "postgresql://localhost/aip_test_db"
)


@pytest.fixture(scope="module")
def setup():
    """Create app, DB tables, seed tenants/users/projects."""
    os.environ["AIP_DB_URL"] = AIP_TEST_DB_URL
    import pipeline.models.base as base_mod

    base_mod._engine = None
    base_mod._SessionLocal = None
    base_mod._DEFAULT_DB_URL = AIP_TEST_DB_URL

    engine = create_engine(AIP_TEST_DB_URL)
    Base.metadata.create_all(engine)

    application = create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"

    Session = sessionmaker(bind=engine)
    db = Session()

    t1 = Tenant(name="HierTenantA", slug="hier-a")
    t2 = Tenant(name="HierTenantB", slug="hier-b")
    db.add_all([t1, t2])
    db.commit()

    u1 = User(email="hier_a@test.com", tenant_id=t1.id)
    u1.set_password("pass")
    u2 = User(email="hier_b@test.com", tenant_id=t2.id)
    u2.set_password("pass")
    db.add_all([u1, u2])
    db.commit()

    p1 = Project(name="HierProjA", tenant_id=t1.id)
    p2 = Project(name="HierProjB", tenant_id=t2.id)
    db.add_all([p1, p2])
    db.commit()

    ctx = {
        "t1": t1.id,
        "t2": t2.id,
        "u1": u1.id,
        "u2": u2.id,
        "p1": p1.id,
        "p2": p2.id,
    }

    yield application, db, ctx

    db.close()
    # Clean up hierarchy tables only (leave tenants/users/projects for other tests)
    for tbl in ("product_profiles", "brand_profile_cards", "customer_profiles"):
        try:
            engine.execute(f"DELETE FROM {tbl} WHERE tenant_id IN ({t1.id},{t2.id})")
        except Exception:
            pass
    Base.metadata.drop_all(engine)
    engine.dispose()
    base_mod._engine = None
    base_mod._SessionLocal = None


def _auth(client, user_id, tenant_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["tenant_id"] = tenant_id


# ── Test 1: Create CustomerProfile via API ──────────────────────────────────


def test_create_customer(setup):
    app, db, ctx = setup
    with app.test_client() as c:
        _auth(c, ctx["u1"], ctx["t1"])
        resp = c.post(
            "/api/customers",
            json={
                "name": "Acme Corp",
                "industry": "Electronics",
                "contact_email": "acme@example.com",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Acme Corp"
        assert "id" in data

        # GET should list it
        resp2 = c.get("/api/customers")
        assert resp2.status_code == 200
        names = [r["name"] for r in resp2.get_json()]
        assert "Acme Corp" in names


# ── Test 2: Create BrandProfile under Customer ──────────────────────────────


def test_create_brand_under_customer(setup):
    app, db, ctx = setup
    with app.test_client() as c:
        _auth(c, ctx["u1"], ctx["t1"])
        # First create a customer
        resp = c.post("/api/customers", json={"name": "BrandTestCo"})
        cust_id = resp.get_json()["id"]

        # Create brand under customer
        resp2 = c.post(
            f"/api/customers/{cust_id}/brands",
            json={
                "project_id": ctx["p1"],
                "brand_tone": "Professional",
                "color_system": "#000,#FFF",
            },
        )
        assert resp2.status_code == 201
        data = resp2.get_json()
        assert data["customer_profile_id"] == cust_id

        # GET brands under customer
        resp3 = c.get(f"/api/customers/{cust_id}/brands")
        assert resp3.status_code == 200
        assert len(resp3.get_json()) >= 1


# ── Test 3: Create ProductProfile under Project ─────────────────────────────


def test_create_product_profile(setup):
    app, db, ctx = setup
    with app.test_client() as c:
        _auth(c, ctx["u1"], ctx["t1"])
        resp = c.post(
            f"/api/projects/{ctx['p1']}/product-profile",
            json={
                "product_name": "Widget X",
                "product_category": "Gadgets",
                "price_point": "$29.99",
                "key_features": "Compact, durable",
                "visual_notes": "Use bright colors",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["project_id"] == ctx["p1"]

        # GET should return it
        resp2 = c.get(f"/api/projects/{ctx['p1']}/product-profile")
        assert resp2.status_code == 200
        assert resp2.get_json()["product_name"] == "Widget X"


# ── Test 4: Tenant isolation — tenant B cannot see tenant A's data ──────────


@pytest.mark.skip(reason="Tenant isolation removed in single-admin mode")
def test_tenant_isolation(setup):
    app, db, ctx = setup
    with app.test_client() as c:
        # Create customer as tenant A
        _auth(c, ctx["u1"], ctx["t1"])
        resp = c.post("/api/customers", json={"name": "SecretCo"})
        assert resp.status_code == 201
        secret_id = resp.get_json()["id"]

        # Switch to tenant B — should NOT see tenant A's customer
        _auth(c, ctx["u2"], ctx["t2"])
        resp2 = c.get("/api/customers")
        assert resp2.status_code == 200
        ids = [r["id"] for r in resp2.get_json()]
        assert secret_id not in ids

        # Tenant B cannot access tenant A's customer's brands
        resp3 = c.get(f"/api/customers/{secret_id}/brands")
        assert resp3.status_code == 404

        # Tenant B cannot access tenant A's project product-profile
        resp4 = c.get(f"/api/projects/{ctx['p1']}/product-profile")
        assert resp4.status_code == 404


# ── Test 5: Validation — customer name required ─────────────────────────────


def test_customer_name_required(setup):
    app, db, ctx = setup
    with app.test_client() as c:
        _auth(c, ctx["u1"], ctx["t1"])
        resp = c.post("/api/customers", json={"industry": "Tech"})
        assert resp.status_code == 400
        assert "name" in resp.get_json().get("error", "").lower()
