import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.config import Config
from pipeline.flywheel import check_flywheel_status, run_flywheel
from pipeline.models.base import Base
from pipeline.models.flywheel_example import FlywheelExample
from pipeline.models.flywheel_observation import FlywheelObservation
from pipeline.models.human_image_score import HumanImageScore
from pipeline.models.product_profile import ProductProfile
from pipeline.models.project import Project
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.qa_record import QARecord
from pipeline.models.slot_plan import SlotPlan

PROJECT_ID = 1


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(Project(id=PROJECT_ID, name="Test", asin="B000TEST", category="test"))
    session.add(ProductProfile(project_id=PROJECT_ID, product_category="test", tenant_id=1))
    session.commit()
    yield session
    session.close()


def _make_config(enabled=False, auto_deliver=False, threshold=85.0) -> Config:
    cfg = Config()
    cfg.flywheel_enabled = enabled
    cfg.flywheel_auto_deliver = auto_deliver
    cfg.flywheel_confidence_threshold = threshold
    return cfg


def _add_asset_with_qa(session, slot_index=1, qa_score=90, human_score=None):
    plan = SlotPlan(project_id=PROJECT_ID, slot_index=slot_index, intent_tag="INT_HERO")
    asset = PromptAsset(
        project_id=PROJECT_ID,
        slot_index=slot_index,
        prompt_text=f"prompt {slot_index}",
        negative_prompt="bad",
        model_name="test-model",
        visual_tags=json.dumps({"photo_style": "studio"}),
    )
    session.add_all([plan, asset])
    session.flush()
    qa = QARecord(
        prompt_asset_id=asset.id,
        check_type="llm_qa",
        passed=1,
        score=qa_score,
        details=json.dumps({"delivery_status": "final"}),
    )
    session.add(qa)
    if human_score is not None:
        session.add(
            HumanImageScore(
                prompt_asset_id=asset.id,
                project_id=PROJECT_ID,
                slot_index=slot_index,
                overall_score=human_score,
            )
        )
    session.commit()
    return asset


class TestRunFlywheel:
    def test_disabled_returns_skipped(self, db_session):
        result = run_flywheel(PROJECT_ID, db_session, config=_make_config(enabled=False))
        assert result == {"skipped": True, "reason": "disabled"}

    def test_archives_high_qa_asset_with_listing_slot_type(self, db_session):
        asset = _add_asset_with_qa(db_session, slot_index=1, qa_score=90)
        result = run_flywheel(PROJECT_ID, db_session, config=_make_config(enabled=True))

        assert result == {"archived": 1, "skipped": 0}
        example = db_session.query(FlywheelExample).filter_by(prompt_asset_id=asset.id).one()
        assert example.slot_type == "MAIN"
        assert example.qa_score == pytest.approx(4.5)
        assert example.combined_score == pytest.approx(4.5)

        flywheel_asset = db_session.query(PromptAsset).filter_by(source="flywheel").one()
        assert flywheel_asset.slot_type == "MAIN"
        assert json.loads(flywheel_asset.visual_tags)["photo_style"] == "studio"

        observation = db_session.query(FlywheelObservation).filter_by(prompt_asset_id=asset.id).one()
        assert observation.source_type == "listing_qa"
        assert observation.slot_type == "MAIN"
        assert observation.combined_score == pytest.approx(4.5)

    def test_below_threshold_is_skipped(self, db_session):
        _add_asset_with_qa(db_session, slot_index=1, qa_score=60)
        result = run_flywheel(PROJECT_ID, db_session, config=_make_config(enabled=True))

        assert result == {"archived": 0, "skipped": 1}
        assert db_session.query(FlywheelExample).count() == 0
        assert db_session.query(FlywheelObservation).count() == 0

    def test_human_score_combines_with_qa_score(self, db_session):
        asset = _add_asset_with_qa(db_session, slot_index=2, qa_score=90, human_score=4.0)
        result = run_flywheel(PROJECT_ID, db_session, config=_make_config(enabled=True))

        assert result == {"archived": 1, "skipped": 0}
        example = db_session.query(FlywheelExample).filter_by(prompt_asset_id=asset.id).one()
        assert example.slot_type == "ALT1"
        assert example.human_score == pytest.approx(4.0)
        assert example.combined_score == pytest.approx(4.25)

    def test_idempotent_for_existing_example(self, db_session):
        _add_asset_with_qa(db_session, slot_index=1, qa_score=90)
        cfg = _make_config(enabled=True)
        run_flywheel(PROJECT_ID, db_session, config=cfg)
        result2 = run_flywheel(PROJECT_ID, db_session, config=cfg)

        assert result2 == {"archived": 1, "skipped": 0}
        assert db_session.query(FlywheelExample).count() == 1
        assert db_session.query(PromptAsset).filter_by(source="flywheel").count() == 1


class TestCheckFlywheelStatus:
    def test_returns_correct_dict(self):
        cfg = _make_config(enabled=True, auto_deliver=False, threshold=90)
        status = check_flywheel_status(cfg)
        assert status == {
            "enabled": True,
            "auto_deliver": False,
            "confidence_threshold": 90,
        }

    def test_defaults_all_disabled(self):
        cfg = _make_config()
        status = check_flywheel_status(cfg)
        assert status["enabled"] is False
        assert status["auto_deliver"] is False
