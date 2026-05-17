"""L4 Schema 约束测试：APlusContent.module_type 枚举 + TagAssignment 唯一约束"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.aplus_content import APlusContent
from pipeline.models.tag_assignment import TagAssignment

# 确保所有模型都被注册
import pipeline.models  # noqa: F401


@pytest.fixture()
def engine():
    """内存 SQLite，启用外键约束"""
    eng = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(eng, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture()
def session(engine):
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


# ---------------------------------------------------------------------------
# 辅助：先创建一个 project 以满足外键
# ---------------------------------------------------------------------------


def _make_project(session):
    from pipeline.models.project import Project

    p = Project(name="test-proj", asin="B000TEST01")
    session.add(p)
    session.flush()
    return p


# ---------------------------------------------------------------------------
# APlusContent.layout 字段存在测试
# ---------------------------------------------------------------------------


class TestAPlusContentLayout:
    def test_layout_field_nullable(self, session):
        """layout 字段存在且可为 None"""
        p = _make_project(session)
        ac = APlusContent(
            project_id=p.id,
            module_type="HERO",
            layout=None,
        )
        session.add(ac)
        session.flush()
        assert ac.layout is None

    def test_layout_field_stores_value(self, session):
        """layout 字段可以存储 JSON 字符串"""
        p = _make_project(session)
        ac = APlusContent(
            project_id=p.id,
            module_type="BENEFIT",
            layout='{"columns": 2}',
        )
        session.add(ac)
        session.flush()
        assert ac.layout == '{"columns": 2}'


# ---------------------------------------------------------------------------
# APlusContent.module_type 枚举约束测试
# ---------------------------------------------------------------------------

VALID_MODULE_TYPES = [
    "HERO",
    "BENEFIT",
    "DETAIL",
    "LIFESTYLE",
    "COMPARISON",
    "BRAND_STORY",
    "CROSS_SELL",
]


class TestAPlusContentModuleTypeConstraint:
    @pytest.mark.parametrize("module_type", VALID_MODULE_TYPES)
    def test_valid_module_type(self, session, module_type):
        """所有合法枚举值应通过约束"""
        p = _make_project(session)
        ac = APlusContent(project_id=p.id, module_type=module_type)
        session.add(ac)
        session.flush()  # 不应抛出异常
        assert ac.module_type == module_type

    def test_invalid_module_type_raises(self, session):
        """非法 module_type 应触发 IntegrityError"""
        p = _make_project(session)
        ac = APlusContent(project_id=p.id, module_type="INVALID_TYPE")
        session.add(ac)
        with pytest.raises(IntegrityError):
            session.flush()


# ---------------------------------------------------------------------------
# TagAssignment.tag_layer 字段测试
# ---------------------------------------------------------------------------


class TestTagAssignmentTagLayer:
    def test_tag_layer_default_intent(self, session):
        """tag_layer 服务端默认值为 'intent'"""
        ta = TagAssignment(
            entity_type="project",
            entity_id=1,
            tag_code="minimalist",
        )
        session.add(ta)
        session.flush()
        # server_default 在 flush 后需 refresh 才能看到
        session.refresh(ta)
        assert ta.tag_layer == "intent"

    def test_tag_layer_custom_value(self, session):
        """tag_layer 可以设置自定义值"""
        ta = TagAssignment(
            entity_type="project",
            entity_id=2,
            tag_code="premium",
            tag_layer="style",
        )
        session.add(ta)
        session.flush()
        assert ta.tag_layer == "style"


# ---------------------------------------------------------------------------
# TagAssignment 唯一约束测试
# ---------------------------------------------------------------------------


class TestTagAssignmentUniqueConstraint:
    def test_duplicate_raises_integrity_error(self, session):
        """同一 (entity_type, entity_id, tag_code) 重复插入应触发 IntegrityError"""
        ta1 = TagAssignment(entity_type="project", entity_id=10, tag_code="eco")
        ta2 = TagAssignment(entity_type="project", entity_id=10, tag_code="eco")
        session.add(ta1)
        session.flush()
        session.add(ta2)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_different_entity_id_allowed(self, session):
        """不同 entity_id 可以有相同 tag_code"""
        ta1 = TagAssignment(entity_type="project", entity_id=20, tag_code="eco")
        ta2 = TagAssignment(entity_type="project", entity_id=21, tag_code="eco")
        session.add_all([ta1, ta2])
        session.flush()  # 不应抛出

    def test_different_tag_code_allowed(self, session):
        """同一 entity_id 可以有不同 tag_code"""
        ta1 = TagAssignment(entity_type="project", entity_id=30, tag_code="eco")
        ta2 = TagAssignment(entity_type="project", entity_id=30, tag_code="premium")
        session.add_all([ta1, ta2])
        session.flush()  # 不应抛出
