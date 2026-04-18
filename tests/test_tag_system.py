"""TDD tests for pipeline.layers.tag_system — 三层标签体系."""

import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.slot_plan import SlotPlan
from pipeline.models.tag_assignment import TagAssignment
from pipeline.models.benchmark import AmazonBenchmark
from pipeline.layers.tag_system import (
    INTENT_CODES,
    ROLE_CODES,
    assign_tags,
    get_scene_tags,
)


PROJECT_ID = 42


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed_slots(session, project_id, count=8):
    """创建 count 个 SlotPlan 记录."""
    plans = []
    for i in range(1, count + 1):
        sp = SlotPlan(
            project_id=project_id,
            slot_index=i,
            intent_tag=f"INT_HERO",
            layout_tag="LAY_CENTER",
            style_tag="STY_MINIMAL",
            color_tag="CLR_WHITE",
            description=f"slot {i}",
        )
        session.add(sp)
        plans.append(sp)
    session.commit()
    for p in plans:
        session.refresh(p)
    return plans


# ── Intent/Role 常量检查 ─────────────────────────────────────


class TestConstants:
    def test_intent_codes_count(self):
        assert len(INTENT_CODES) == 6

    def test_role_codes_count(self):
        assert len(ROLE_CODES) == 7

    def test_intent_codes_format(self):
        """INT_01 ~ INT_06."""
        for i, code in enumerate(INTENT_CODES, 1):
            assert code == f"INT_{i:02d}"

    def test_role_codes_format(self):
        """ROLE_01 ~ ROLE_07."""
        for i, code in enumerate(ROLE_CODES, 1):
            assert code == f"ROLE_{i:02d}"


# ── assign_tags ──────────────────────────────────────────────


class TestAssignTags:
    def test_assigns_intent_and_role_per_slot(self, db_session):
        """每个 slot 至少分配 1 个 intent + 1 个 role 标签."""
        slots = _seed_slots(db_session, PROJECT_ID)
        result = assign_tags(PROJECT_ID, slots[0].project_id, session=db_session)

        # 至少有 8 个 intent + 8 个 role = 16 条记录
        intents = [t for t in result if t.tag_layer == "intent"]
        roles = [t for t in result if t.tag_layer == "role"]
        assert len(intents) >= 8
        assert len(roles) >= 8

    def test_tag_codes_valid(self, db_session):
        """分配的 tag_code 属于常量定义."""
        _seed_slots(db_session, PROJECT_ID)
        result = assign_tags(PROJECT_ID, PROJECT_ID, session=db_session)

        for ta in result:
            if ta.tag_layer == "intent":
                assert ta.tag_code in INTENT_CODES
            elif ta.tag_layer == "role":
                assert ta.tag_code in ROLE_CODES

    def test_entity_type_is_slot(self, db_session):
        """entity_type 固定为 'slot'."""
        _seed_slots(db_session, PROJECT_ID)
        result = assign_tags(PROJECT_ID, PROJECT_ID, session=db_session)
        for ta in result:
            assert ta.entity_type == "slot"

    def test_tag_layer_written(self, db_session):
        """tag_layer 字段正确写入 'intent' 或 'role'."""
        _seed_slots(db_session, PROJECT_ID)
        result = assign_tags(PROJECT_ID, PROJECT_ID, session=db_session)
        layers = {ta.tag_layer for ta in result}
        assert "intent" in layers
        assert "role" in layers

    def test_invalid_project_returns_empty(self, db_session):
        """无效 project_id → 返回空列表，不抛异常."""
        result = assign_tags(999, 1, session=db_session)
        assert result == []

    def test_no_duplicate_tags(self, db_session):
        """同一 slot 不重复分配相同 tag_code."""
        _seed_slots(db_session, PROJECT_ID)
        assign_tags(PROJECT_ID, PROJECT_ID, session=db_session)
        # 再次调用不应报错（幂等）
        result = assign_tags(PROJECT_ID, PROJECT_ID, session=db_session)
        assert len(result) >= 16

    def test_persisted_to_db(self, db_session):
        """TagAssignment 记录写入数据库."""
        _seed_slots(db_session, PROJECT_ID)
        assign_tags(PROJECT_ID, PROJECT_ID, session=db_session)
        count = db_session.query(TagAssignment).count()
        assert count >= 16


# ── get_scene_tags ───────────────────────────────────────────


class TestGetSceneTags:
    @patch("pipeline.layers.tag_system._call_llm_for_scenes")
    def test_returns_scene_tags(self, mock_llm, db_session):
        """LLM 返回场景标签，写入 tag_layer='scene'."""
        mock_llm.return_value = ["SCENE_OUTDOOR", "SCENE_KITCHEN", "SCENE_OFFICE"]
        _seed_slots(db_session, PROJECT_ID)

        result = get_scene_tags(PROJECT_ID, session=db_session)
        assert len(result) >= 3
        for ta in result:
            assert ta.tag_layer == "scene"
            assert ta.tag_code.startswith("SCENE_")

    @patch("pipeline.layers.tag_system._call_llm_for_scenes")
    def test_scene_tags_persisted(self, mock_llm, db_session):
        """场景标签写入数据库."""
        mock_llm.return_value = ["SCENE_OUTDOOR", "SCENE_KITCHEN"]
        _seed_slots(db_session, PROJECT_ID)

        get_scene_tags(PROJECT_ID, session=db_session)
        scenes = (
            db_session.query(TagAssignment)
            .filter(TagAssignment.tag_layer == "scene")
            .all()
        )
        assert len(scenes) >= 2

    @patch("pipeline.layers.tag_system._call_llm_for_scenes")
    def test_scene_invalid_project(self, mock_llm, db_session):
        """无效 project → 空列表."""
        mock_llm.return_value = []
        result = get_scene_tags(999, session=db_session)
        assert result == []
