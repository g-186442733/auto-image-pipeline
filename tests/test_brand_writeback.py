"""品牌画像 guidelines 写回闭环测试。"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.brand_profile import BrandProfile as BrandProfileCard

# 合并后 BrandProfile 统一指向 brand_profile_cards
BrandProfile = BrandProfileCard
from pipeline.models.project import Project
from pipeline.models.ab_test_result import ABTestResult
from pipeline.db_migrate import run_migrations
from pipeline.layers.feedback_loop import update_brand_profile_from_results


@pytest.fixture()
def mem_engine():
    """创建 in-memory SQLite 引擎并初始化全部表。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def mem_session(mem_engine):
    Session = sessionmaker(bind=mem_engine)
    session = Session()
    yield session
    session.close()


# ---------- 模型字段测试 ----------


def test_brand_profile_card_has_guidelines():
    """BrandProfileCard（brand_profile_cards 表）应有 guidelines 属性。"""
    assert hasattr(BrandProfileCard, "guidelines")


def test_brand_profile_has_guidelines():
    """BrandProfile（brand_profiles 表）应有 guidelines 属性。"""
    assert hasattr(BrandProfile, "guidelines")


# ---------- 字段读写测试 ----------


def test_guidelines_roundtrip_brand_profile_cards(mem_session):
    """brand_profile_cards 表 guidelines 字段可写入并读回。"""
    proj = Project(name="test-proj", category="test")
    mem_session.add(proj)
    mem_session.flush()

    card = BrandProfileCard(project_id=proj.id, guidelines="测试指南内容")
    mem_session.add(card)
    mem_session.commit()

    loaded = mem_session.get(BrandProfileCard, card.id)
    assert loaded.guidelines == "测试指南内容"


def test_guidelines_roundtrip_brand_profiles(mem_session):
    """brand_profile_cards 表 guidelines 字段可写入并读回（合并后）。"""
    proj = Project(name="test-proj-2", category="test")
    mem_session.add(proj)
    mem_session.flush()

    bp = BrandProfile(project_id=proj.id, guidelines="品牌指南")
    mem_session.add(bp)
    mem_session.commit()

    loaded = mem_session.get(BrandProfile, bp.id)
    assert loaded.guidelines == "品牌指南"


# ---------- feedback_loop 写回测试 ----------


def test_update_brand_profile_from_results_writes_guidelines(mem_session):
    """update_brand_profile_from_results() 应将 A/B 结论写入 guidelines。"""
    proj = Project(name="writeback-proj", category="test")
    mem_session.add(proj)
    mem_session.flush()

    bp = BrandProfile(project_id=proj.id)
    mem_session.add(bp)
    mem_session.flush()

    # 插入两条 ABTestResult
    mem_session.add(
        ABTestResult(project_id=proj.id, slot_index=0, variant="A", score=0.8)
    )
    mem_session.add(
        ABTestResult(project_id=proj.id, slot_index=1, variant="B", score=0.6)
    )
    mem_session.commit()

    result = update_brand_profile_from_results(proj.id, session=mem_session)
    assert result is not None
    assert result.guidelines is not None

    data = json.loads(result.guidelines)
    assert "best_variant" in data
    assert data["best_variant"] == "A"


# ---------- 迁移幂等性测试 ----------


def test_run_migrations_idempotent(mem_engine):
    """run_migrations() 执行两次不应报错。"""
    run_migrations(mem_engine)
    run_migrations(mem_engine)  # 第二次应安全跳过
