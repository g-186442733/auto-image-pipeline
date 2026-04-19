"""飞轮测试 — TDD RED→GREEN→REFACTOR"""

import pytest
from unittest.mock import MagicMock
from dataclasses import dataclass, field

from pipeline.flywheel import run_flywheel, check_flywheel_status
from pipeline.config import Config
from pipeline.models.delivery_version import DeliveryVersion
from pipeline.models.base import get_engine, Base, get_session


@pytest.fixture(autouse=True)
def _db():
    eng = get_engine()
    Base.metadata.create_all(eng)
    yield
    Base.metadata.drop_all(eng)


def _make_config(enabled=False, auto_deliver=False, threshold=85.0) -> Config:
    cfg = Config()
    cfg.flywheel_enabled = enabled
    cfg.flywheel_auto_deliver = auto_deliver
    cfg.flywheel_confidence_threshold = threshold
    return cfg


class TestRunFlywheel:
    def test_disabled_returns_skipped(self):
        session = get_session()
        try:
            result = run_flywheel(
                "proj_1", session, config=_make_config(enabled=False), qa_score=90
            )
            assert result == {"skipped": True, "reason": "disabled"}
        finally:
            session.close()

    def test_high_score_auto_delivers(self):
        session = get_session()
        try:
            cfg = _make_config(enabled=True, auto_deliver=True, threshold=85)
            result = run_flywheel("proj_1", session, config=cfg, qa_score=90)
            assert result["auto_delivered"] is True
            assert result["score"] == 90
            assert result["version"] == 1

            dv = session.query(DeliveryVersion).filter_by(project_id="proj_1").first()
            assert dv is not None
            assert dv.auto_delivered is True
            assert dv.trigger == "flywheel"
        finally:
            session.close()

    def test_below_threshold_no_delivery(self):
        session = get_session()
        try:
            cfg = _make_config(enabled=True, auto_deliver=True, threshold=85)
            result = run_flywheel("proj_1", session, config=cfg, qa_score=60)
            assert result["auto_delivered"] is False
            assert result["reason"] == "below_threshold"
            assert result["score"] == 60

            dv = session.query(DeliveryVersion).filter_by(project_id="proj_1").first()
            assert dv is None
        finally:
            session.close()

    def test_auto_deliver_disabled_no_delivery(self):
        session = get_session()
        try:
            cfg = _make_config(enabled=True, auto_deliver=False, threshold=85)
            result = run_flywheel("proj_1", session, config=cfg, qa_score=90)
            assert result["auto_delivered"] is False
            assert result["reason"] == "auto_deliver_disabled"
            assert result["score"] == 90

            dv = session.query(DeliveryVersion).filter_by(project_id="proj_1").first()
            assert dv is None
        finally:
            session.close()

    def test_qa_score_fn_callable(self):
        session = get_session()
        try:
            cfg = _make_config(enabled=True, auto_deliver=True, threshold=85)
            result = run_flywheel("proj_1", session, config=cfg, qa_score_fn=lambda: 95)
            assert result["auto_delivered"] is True
            assert result["score"] == 95
        finally:
            session.close()

    def test_version_increments(self):
        session = get_session()
        try:
            cfg = _make_config(enabled=True, auto_deliver=True, threshold=85)
            run_flywheel("proj_1", session, config=cfg, qa_score=90)
            result2 = run_flywheel("proj_1", session, config=cfg, qa_score=92)
            assert result2["version"] == 2
        finally:
            session.close()


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
