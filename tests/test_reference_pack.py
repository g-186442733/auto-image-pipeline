"""Tests for Reference Pack 6 components (Task 6)."""

import json
import pytest

from pipeline.models.base import Base, get_engine, get_session
from pipeline.models.project import Project
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.review_cluster import ReviewCluster
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.models.reference_pack import ReferencePack
from pipeline.layers.reference_pack import build_reference_pack, get_reference_pack


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    session = Session()

    # Patch get_session to return sessions from this engine
    import pipeline.models.base as base_mod

    orig_factory = base_mod._SessionLocal
    base_mod._SessionLocal = Session

    yield session

    session.close()
    base_mod._SessionLocal = orig_factory
    Base.metadata.drop_all(engine)


@pytest.fixture()
def project_with_data(db_session):
    """Create a project with related data for reference pack building."""
    project = Project(name="Test Product", asin="B001TEST", category="Electronics")
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    # Add competitor listing
    comp = CompetitorListing(
        asin="B002COMP",
        title="Competitor Widget",
        bullet_points="Fast charging\nLong battery",
        description="A great competitor product",
        project_id=project.id,
    )
    db_session.add(comp)

    # Add review clusters
    rc1 = ReviewCluster(
        asin="B001TEST",
        cluster_label="Quality",
        sentiment="positive",
        count=42,
        representative_reviews="Great quality, very durable",
        project_id=project.id,
    )
    rc2 = ReviewCluster(
        asin="B001TEST",
        cluster_label="Price",
        sentiment="negative",
        count=10,
        representative_reviews="Too expensive for what it is",
        project_id=project.id,
    )
    db_session.add_all([rc1, rc2])

    # Add brand profile
    bp = BrandProfile(
        project_id=project.id,
        brand_tone="Premium, Professional",
        color_system="#1A1A2E, #16213E, #0F3460",
        photo_style="Studio, minimalist",
        material_texture="Matte aluminum",
    )
    db_session.add(bp)

    # Add benchmarks
    bm = AmazonBenchmark(
        project_id=project.id,
        competitor_asin="B002COMP",
        slot_index=1,
        analysis="Clean white background, product centered",
        score=8.5,
    )
    db_session.add(bm)

    db_session.commit()
    return project


# ---- Model tests ----


class TestReferencePackModel:
    def test_create_reference_pack(self, db_session):
        project = Project(name="RP Test", asin="B000RP")
        db_session.add(project)
        db_session.commit()
        db_session.refresh(project)

        rp = ReferencePack(
            project_id=project.id,
            product_truth=json.dumps({"name": "Test", "asin": "B000RP"}),
            brand_rules=json.dumps({"tone": "premium"}),
            winning_examples=json.dumps([{"label": "Quality", "count": 42}]),
            competitor_baseline=json.dumps([{"asin": "B002", "score": 8.5}]),
            negative_cases=json.dumps([{"sentiment": "negative", "issue": "price"}]),
            angle_matrix=json.dumps({"angles": ["quality", "value"]}),
        )
        db_session.add(rp)
        db_session.commit()
        db_session.refresh(rp)

        assert rp.id is not None
        assert rp.project_id == project.id
        assert json.loads(rp.product_truth)["name"] == "Test"

    def test_unique_project_id(self, db_session):
        """Only one ReferencePack per project."""
        project = Project(name="Unique Test", asin="B000UQ")
        db_session.add(project)
        db_session.commit()
        db_session.refresh(project)

        rp1 = ReferencePack(project_id=project.id, product_truth="{}")
        db_session.add(rp1)
        db_session.commit()

        rp2 = ReferencePack(project_id=project.id, product_truth="{}")
        db_session.add(rp2)
        with pytest.raises(Exception):  # IntegrityError
            db_session.commit()
        db_session.rollback()

    def test_six_json_columns_exist(self, db_session):
        """All 6 component columns exist on the model."""
        cols = {c.name for c in ReferencePack.__table__.columns}
        expected = {
            "product_truth",
            "brand_rules",
            "winning_examples",
            "competitor_baseline",
            "negative_cases",
            "angle_matrix",
        }
        assert expected.issubset(cols)


# ---- build_reference_pack tests ----


class TestBuildReferencePack:
    def test_build_creates_record(self, project_with_data):
        rp = build_reference_pack(project_with_data.id)
        assert rp is not None
        assert rp.project_id == project_with_data.id

    def test_build_all_six_fields_non_empty(self, project_with_data):
        rp = build_reference_pack(project_with_data.id)
        for field in [
            "product_truth",
            "brand_rules",
            "winning_examples",
            "competitor_baseline",
            "negative_cases",
            "angle_matrix",
        ]:
            val = getattr(rp, field)
            assert val is not None, f"{field} is None"
            parsed = json.loads(val)
            assert parsed, f"{field} is empty after JSON parse"

    def test_product_truth_from_project(self, project_with_data):
        rp = build_reference_pack(project_with_data.id)
        pt = json.loads(rp.product_truth)
        assert pt["name"] == "Test Product"
        assert pt["asin"] == "B001TEST"

    def test_brand_rules_from_brand_profile(self, project_with_data):
        rp = build_reference_pack(project_with_data.id)
        br = json.loads(rp.brand_rules)
        assert "Premium" in br.get("tone", "") or "Premium" in str(br)

    def test_winning_examples_from_reviews(self, project_with_data):
        rp = build_reference_pack(project_with_data.id)
        we = json.loads(rp.winning_examples)
        assert isinstance(we, list)
        assert len(we) >= 1

    def test_competitor_baseline_from_benchmarks(self, project_with_data):
        rp = build_reference_pack(project_with_data.id)
        cb = json.loads(rp.competitor_baseline)
        assert isinstance(cb, list)
        assert any("B002COMP" in str(item) for item in cb)

    def test_negative_cases_from_negative_reviews(self, project_with_data):
        rp = build_reference_pack(project_with_data.id)
        nc = json.loads(rp.negative_cases)
        assert isinstance(nc, list)

    def test_angle_matrix_generated(self, project_with_data):
        rp = build_reference_pack(project_with_data.id)
        am = json.loads(rp.angle_matrix)
        assert isinstance(am, (dict, list))

    def test_build_idempotent(self, project_with_data):
        """Building twice should update, not duplicate."""
        rp1 = build_reference_pack(project_with_data.id)
        rp2 = build_reference_pack(project_with_data.id)
        assert rp1.id == rp2.id

    def test_build_nonexistent_project(self, db_session):
        with pytest.raises(ValueError, match="E_REFPACK_001"):
            build_reference_pack(9999)

    def test_build_no_related_data(self, db_session):
        """Project with no competitors/reviews/brand should still produce a pack with defaults."""
        project = Project(name="Bare Project", asin="B000BARE")
        db_session.add(project)
        db_session.commit()
        db_session.refresh(project)

        rp = build_reference_pack(project.id)
        assert rp is not None
        # All fields should have valid JSON (possibly empty containers)
        for field in [
            "product_truth",
            "brand_rules",
            "winning_examples",
            "competitor_baseline",
            "negative_cases",
            "angle_matrix",
        ]:
            val = getattr(rp, field)
            assert val is not None
            json.loads(val)  # should not raise


# ---- get_reference_pack tests ----


class TestGetReferencePack:
    def test_get_after_build(self, project_with_data):
        build_reference_pack(project_with_data.id)
        rp = get_reference_pack(project_with_data.id)
        assert rp is not None
        assert rp.project_id == project_with_data.id

    def test_get_nonexistent_returns_none(self, db_session):
        assert get_reference_pack(9999) is None


# ---- prompt_engine integration tests ----


class TestPromptEngineIntegration:
    def test_assemble_prompt_with_reference_pack(self, db_session):
        """assemble_prompt should accept and include reference_pack context."""
        from pipeline.models.prompt_asset import PromptAsset

        asset = PromptAsset(
            project_id=1,
            slot_index=1,
            prompt_text="Generate {{ subject }}",
            negative_prompt="blurry",
            version=1,
        )
        db_session.add(asset)
        db_session.commit()
        db_session.refresh(asset)

        from pipeline.layers.prompt_engine import assemble_prompt

        variables = {
            "composition": "centered",
            "subject": "product shot",
            "environment": "studio",
            "camera": "front",
            "tone": "premium",
            "constraints": "none",
        }

        rp_dict = {
            "product_truth": {"name": "Widget", "asin": "B001"},
            "brand_rules": {"tone": "Premium"},
        }

        result = assemble_prompt(asset.id, variables, reference_pack=rp_dict)
        assert "Widget" in result or "reference" in result.lower()

    def test_assemble_prompt_without_reference_pack(self, db_session):
        """assemble_prompt should work fine without reference_pack (backward compat)."""
        from pipeline.models.prompt_asset import PromptAsset

        asset = PromptAsset(
            project_id=1,
            slot_index=1,
            prompt_text="Simple {{ subject }}",
            version=1,
        )
        db_session.add(asset)
        db_session.commit()
        db_session.refresh(asset)

        from pipeline.layers.prompt_engine import assemble_prompt

        variables = {
            "composition": "c",
            "subject": "test",
            "environment": "e",
            "camera": "c",
            "tone": "t",
            "constraints": "n",
        }
        result = assemble_prompt(asset.id, variables)
        assert "Simple test" in result


# ---- web route test ----


class TestWebRoute:
    def test_reference_pack_route_exists(self, project_with_data):
        from pipeline.web.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        from tests.conftest import inject_auth
        inject_auth(client)

        build_reference_pack(project_with_data.id)
        resp = client.get(f"/project/{project_with_data.id}/reference-pack")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "product_truth" in data

    def test_reference_pack_route_404(self, db_session):
        from pipeline.web.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        from tests.conftest import inject_auth
        inject_auth(client)

        resp = client.get("/project/9999/reference-pack")
        assert resp.status_code == 404
