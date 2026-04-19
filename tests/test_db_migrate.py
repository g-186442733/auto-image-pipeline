import pytest
from sqlalchemy import create_engine, inspect, text
import pipeline.models.base as base_mod
import pipeline.models.tenant
import pipeline.models.project
import pipeline.models.brand_profile
import pipeline.models.benchmark
import pipeline.models.prompt_asset
import pipeline.models.slot_plan
import pipeline.models.qa_record
import pipeline.models.ab_test
import pipeline.models.ab_test_result
import pipeline.models.tag_assignment
import pipeline.models.intake_checklist
import pipeline.models.competitor_listing
import pipeline.models.review_cluster
import pipeline.models.qa_entry
import pipeline.models.image_brief
import pipeline.models.price_analysis
import pipeline.models.promo_analysis
import pipeline.models.aplus_content
import pipeline.models.asin_ranking
import pipeline.models.client_feedback
import pipeline.models.consistency_profile
import pipeline.models.delivery_version
import pipeline.models.image_snapshot
import pipeline.models.knowledge_entry
import pipeline.models.reference_pack
from pipeline.db_migrate import run_migrations


@pytest.fixture
def fresh_engine():
    base_mod._engine = None
    base_mod._SessionLocal = None
    base_mod.create_all("sqlite:///:memory:")
    engine = base_mod._engine
    yield engine
    base_mod._engine = None
    base_mod._SessionLocal = None


def _col_names(engine, table):
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_fresh_migration_adds_all_columns(fresh_engine):
    run_migrations(fresh_engine)
    prompt_cols = _col_names(fresh_engine, "prompt_assets")
    delivery_cols = _col_names(fresh_engine, "delivery_versions")
    assert "performance_score" in prompt_cols
    assert "is_recommended" in prompt_cols
    assert "auto_delivered" in delivery_cols
    assert "client_signed_at" in delivery_cols


def test_migration_idempotent(fresh_engine):
    run_migrations(fresh_engine)
    run_migrations(fresh_engine)
    prompt_cols = _col_names(fresh_engine, "prompt_assets")
    assert "performance_score" in prompt_cols
    assert "is_recommended" in prompt_cols


def test_migration_skips_missing_table(fresh_engine):
    from pipeline.db_migrate import MIGRATIONS as orig
    import pipeline.db_migrate as dm

    old = dm.MIGRATIONS
    dm.MIGRATIONS = [("nonexistent_table", "some_col", "TEXT DEFAULT NULL")]
    run_migrations(fresh_engine)
    dm.MIGRATIONS = old
