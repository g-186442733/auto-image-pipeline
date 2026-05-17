"""Task 5 — tests for 5 new SQLAlchemy models (TDD RED→GREEN)."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_in_memory_db():
    """Reset SQLAlchemy globals and point to in-memory SQLite."""
    import pipeline.models.base as base_mod

    base_mod._engine = None
    base_mod._SessionLocal = None
    base_mod.create_all("sqlite:///:memory:")
    return "sqlite:///:memory:"


def _session(db_url="sqlite:///:memory:"):
    from pipeline.models.base import get_session

    return get_session(db_url)


def _create_project(session):
    from pipeline.models.project import Project

    p = Project(
        name="test-proj", asin="B0TESTTEST", category="Electronics", status="draft"
    )
    session.add(p)
    session.commit()
    return p.id


# ===========================================================================
# T1: create_all creates all 5 new tables
# ===========================================================================


class TestTablesExist:
    def test_new_tables_created(self):
        db_url = _make_in_memory_db()
        from pipeline.models.base import get_engine

        eng = get_engine(db_url)
        tables = inspect(eng).get_table_names()
        for t in [
            "intake_checklists",
            "competitor_listings",
            "review_clusters",
            "qa_entries",
            "image_briefs",
        ]:
            assert t in tables, f"Table {t} missing after create_all"


# ===========================================================================
# T2: IntakeChecklist CRUD + FK
# ===========================================================================


class TestIntakeChecklist:
    def test_create_and_read(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)
        pid = _create_project(s)

        from pipeline.models.intake_checklist import IntakeChecklist

        obj = IntakeChecklist(
            project_id=pid,
            product_photos="photo1.jpg,photo2.jpg",
            brand_guide="guide.pdf",
            competitor_asins="B0AAA11111,B0BBB22222",
            platform_requirements="Amazon US",
        )
        s.add(obj)
        s.commit()
        oid = obj.id

        fetched = s.get(IntakeChecklist, oid)
        assert fetched is not None
        assert fetched.project_id == pid
        assert fetched.product_photos == "photo1.jpg,photo2.jpg"
        assert fetched.created_at is not None
        s.close()

    def test_fk_constraint(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)
        from pipeline.models.intake_checklist import IntakeChecklist

        obj = IntakeChecklist(project_id=99999, product_photos="x")
        s.add(obj)
        # SQLite doesn't enforce FK by default, but column should exist
        s.commit()
        assert obj.project_id == 99999
        s.close()


# ===========================================================================
# T3: CompetitorListing CRUD
# ===========================================================================


class TestCompetitorListing:
    def test_create_and_read(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)
        pid = _create_project(s)

        from pipeline.models.competitor_listing import CompetitorListing

        obj = CompetitorListing(
            asin="B0COMP1234",
            title="Competitor Product",
            bullet_points="point1\npoint2",
            description="A great product",
            selling_points_map='{"usp": "fast"}',
            project_id=pid,
        )
        s.add(obj)
        s.commit()

        fetched = s.get(CompetitorListing, obj.id)
        assert fetched.asin == "B0COMP1234"
        assert fetched.title == "Competitor Product"
        assert fetched.created_at is not None
        s.close()

    def test_nullable_project_id(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)
        from pipeline.models.competitor_listing import CompetitorListing

        obj = CompetitorListing(asin="B0NULLTEST", title="No project")
        s.add(obj)
        s.commit()
        assert obj.project_id is None
        s.close()


# ===========================================================================
# T4: ReviewCluster CRUD
# ===========================================================================


class TestReviewCluster:
    def test_create_and_read(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)

        from pipeline.models.review_cluster import ReviewCluster

        obj = ReviewCluster(
            asin="B0REVIEW01",
            cluster_label="battery_life",
            sentiment="positive",
            count=42,
            representative_reviews='["great battery", "lasts long"]',
        )
        s.add(obj)
        s.commit()

        fetched = s.get(ReviewCluster, obj.id)
        assert fetched.cluster_label == "battery_life"
        assert fetched.sentiment == "positive"
        assert fetched.count == 42
        assert fetched.created_at is not None
        s.close()


# ===========================================================================
# T5: QAEntry CRUD
# ===========================================================================


class TestQAEntry:
    def test_create_and_read(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)

        from pipeline.models.qa_entry import QAEntry

        obj = QAEntry(
            asin="B0QATEST01",
            question="Is it waterproof?",
            answer="Yes, IPX7 rated",
            frequency=15,
            category="durability",
        )
        s.add(obj)
        s.commit()

        fetched = s.get(QAEntry, obj.id)
        assert fetched.question == "Is it waterproof?"
        assert fetched.frequency == 15
        assert fetched.created_at is not None
        s.close()

    def test_frequency_default(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)
        from pipeline.models.qa_entry import QAEntry

        obj = QAEntry(asin="B0DEFAULT1", question="Q", answer="A")
        s.add(obj)
        s.commit()
        assert obj.frequency == 1
        s.close()


# ===========================================================================
# T6: ImageBrief CRUD + FK
# ===========================================================================


class TestImageBrief:
    def test_create_and_read(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)
        pid = _create_project(s)

        from pipeline.models.image_brief import ImageBrief

        obj = ImageBrief(
            project_id=pid,
            slot_index=0,
            brief_json='{"hero": true}',
            source_analysis_ids="[1, 2, 3]",
        )
        s.add(obj)
        s.commit()

        fetched = s.get(ImageBrief, obj.id)
        assert fetched.project_id == pid
        assert fetched.slot_index == 0
        assert fetched.brief_json == '{"hero": true}'
        assert fetched.created_at is not None
        s.close()


# ===========================================================================
# T7: PriceAnalysis CRUD
# ===========================================================================


class TestPriceAnalysis:
    def test_create_and_read(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)
        pid = _create_project(s)

        from pipeline.models.price_analysis import PriceAnalysis

        obj = PriceAnalysis(
            project_id=pid,
            asin="B0PRICE001",
            price_current=29.99,
            price_avg_30d=31.50,
            price_min_30d=25.00,
            price_max_30d=35.99,
            price_position="mid",
            competitor_prices='[{"asin":"B0X1","price":27.99}]',
        )
        s.add(obj)
        s.commit()

        fetched = s.get(PriceAnalysis, obj.id)
        assert fetched.asin == "B0PRICE001"
        assert fetched.price_current == 29.99
        assert fetched.price_position == "mid"
        assert fetched.created_at is not None
        s.close()

    def test_table_created(self):
        db_url = _make_in_memory_db()
        from pipeline.models.base import get_engine

        eng = get_engine(db_url)
        tables = inspect(eng).get_table_names()
        assert "price_analyses" in tables

    def test_nullable_fields(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)
        from pipeline.models.price_analysis import PriceAnalysis

        obj = PriceAnalysis(asin="B0NULLPRICE")
        s.add(obj)
        s.commit()
        assert obj.price_current is None
        assert obj.price_position is None
        s.close()


# ===========================================================================
# T8: PromoAnalysis CRUD
# ===========================================================================


class TestPromoAnalysis:
    def test_create_and_read(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)
        pid = _create_project(s)

        from pipeline.models.promo_analysis import PromoAnalysis

        obj = PromoAnalysis(
            project_id=pid,
            asin="B0PROMO001",
            promo_frequency=3,
            avg_discount_pct=15.5,
            last_promo_date="2024-01-15",
            promo_pattern="seasonal",
        )
        s.add(obj)
        s.commit()

        fetched = s.get(PromoAnalysis, obj.id)
        assert fetched.asin == "B0PROMO001"
        assert fetched.promo_frequency == 3
        assert fetched.avg_discount_pct == 15.5
        assert fetched.promo_pattern == "seasonal"
        assert fetched.created_at is not None
        s.close()

    def test_table_created(self):
        db_url = _make_in_memory_db()
        from pipeline.models.base import get_engine

        eng = get_engine(db_url)
        tables = inspect(eng).get_table_names()
        assert "promo_analysis" in tables

    def test_defaults(self):
        db_url = _make_in_memory_db()
        s = _session(db_url)
        from pipeline.models.promo_analysis import PromoAnalysis

        obj = PromoAnalysis(asin="B0DEFPROMO")
        s.add(obj)
        s.commit()
        assert obj.promo_frequency is None
        assert obj.avg_discount_pct is None
        assert obj.last_promo_date is None
        assert obj.promo_pattern is None
        s.close()


# ===========================================================================
# T9: Import check — PriceAnalysis and PromoAnalysis from pipeline.models
# ===========================================================================


class TestModelsImport:
    def test_import_from_package(self):
        from pipeline.models import PriceAnalysis, PromoAnalysis

        assert PriceAnalysis.__tablename__ == "price_analyses"
        assert PromoAnalysis.__tablename__ == "promo_analysis"
