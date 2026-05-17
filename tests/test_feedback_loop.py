import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.project import Project
from pipeline.models.brand_profile import BrandProfile
from pipeline.models.product_profile import ProductProfile
from pipeline.models.ab_test_result import ABTestResult
from pipeline.layers.feedback_loop import (
    record_ab_result,
    update_brand_profile_from_results,
    export_conclusions,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed_project(session, project_id=1):
    session.add(Project(id=project_id, name="Test", asin="B000TEST", category="test"))
    session.commit()


def _seed_brand(session, project_id=1):
    brand = BrandProfile(name="TestBrand")
    session.add(brand)
    session.flush()
    pp = ProductProfile(project_id=project_id, brand_profile_id=brand.id, tenant_id=1)
    session.add(pp)
    session.commit()
    return brand


def test_record_ab_result_persists(db_session):
    _seed_project(db_session)
    row = record_ab_result(
        project_id=1, slot_index=1, variant="A", score=0.85, session=db_session
    )
    assert row.id is not None
    fetched = db_session.get(ABTestResult, row.id)
    assert fetched is not None
    assert fetched.variant == "A"
    assert fetched.score == 0.85


def test_record_ab_result_owns_session(db_session):
    _seed_project(db_session)
    row = record_ab_result(
        project_id=1, slot_index=2, variant="B", score=0.9, session=db_session
    )
    assert row.id is not None
    assert row.variant == "B"


def test_update_brand_profile_from_results(db_session):
    _seed_project(db_session)
    _seed_brand(db_session)
    record_ab_result(
        project_id=1, slot_index=1, variant="A", score=0.8, session=db_session
    )
    record_ab_result(
        project_id=1, slot_index=2, variant="A", score=0.6, session=db_session
    )
    record_ab_result(
        project_id=1, slot_index=1, variant="B", score=0.9, session=db_session
    )
    record_ab_result(
        project_id=1, slot_index=2, variant="B", score=0.95, session=db_session
    )

    brand = update_brand_profile_from_results(project_id=1, session=db_session)
    assert brand is not None
    data = json.loads(brand.ab_conclusions)
    assert data["best_variant"] == "B"
    assert data["variant_averages"]["B"] > data["variant_averages"]["A"]


def test_update_brand_profile_empty_results(db_session):
    _seed_project(db_session)
    _seed_brand(db_session)
    brand = update_brand_profile_from_results(project_id=1, session=db_session)
    assert brand is not None
    assert (
        brand.ab_conclusions is None
        or brand.ab_conclusions == ""
        or "best_variant" not in (brand.ab_conclusions or "")
    )


def test_export_conclusions_correct_keys(db_session):
    _seed_project(db_session)
    record_ab_result(
        project_id=1, slot_index=1, variant="A", score=0.7, session=db_session
    )
    record_ab_result(
        project_id=1, slot_index=2, variant="B", score=0.9, session=db_session
    )

    result = export_conclusions(project_id=1, session=db_session)
    assert set(result.keys()) == {
        "project_id",
        "total_tests",
        "best_variant",
        "avg_score",
        "results",
    }
    assert result["total_tests"] == 2
    assert result["best_variant"] == "B"
    assert result["project_id"] == 1


def test_export_conclusions_no_results(db_session):
    _seed_project(db_session)
    result = export_conclusions(project_id=1, session=db_session)
    assert result["total_tests"] == 0
    assert result["best_variant"] is None
    assert result["avg_score"] == 0.0
    assert result["results"] == []
