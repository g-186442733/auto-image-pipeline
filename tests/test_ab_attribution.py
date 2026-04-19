"""TDD tests for A/B attribution engine."""

import csv
import json
import os
import tempfile

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import pipeline.models.base as base_mod
import pipeline.models.prompt_asset
import pipeline.models.project
import pipeline.models.tenant
from pipeline.db_migrate import run_migrations
from pipeline.layers.ab_attribution import (
    CTR_WEIGHT,
    CVR_WEIGHT,
    RECOMMEND_THRESHOLD,
    apply_attribution,
    calculate_performance_score,
    import_performance_data,
)


@pytest.fixture
def db_session():
    """创建内存数据库，运行迁移，返回 session。"""
    base_mod._engine = None
    base_mod._SessionLocal = None
    base_mod.create_all("sqlite:///:memory:")
    engine = base_mod._engine
    run_migrations(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # SQLite 默认不强制外键，直接 yield，prompt_assets 在各测试中按需插入
    session.commit()
    yield session
    session.close()
    base_mod._engine = None
    base_mod._SessionLocal = None


@pytest.fixture
def csv_file_normal():
    """正常 CSV：ctr=0.8, cvr=0.6 → score=0.72"""
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["prompt_asset_id", "ctr", "cvr"])
        writer.writeheader()
        writer.writerow({"prompt_asset_id": "1", "ctr": "0.8", "cvr": "0.6"})
    yield path
    os.unlink(path)


@pytest.fixture
def csv_file_recommended():
    """高分 CSV：ctr=0.9, cvr=0.8 → score=0.86"""
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["prompt_asset_id", "ctr", "cvr"])
        writer.writeheader()
        writer.writerow({"prompt_asset_id": "1", "ctr": "0.9", "cvr": "0.8"})
    yield path
    os.unlink(path)


@pytest.fixture
def json_file():
    """JSON 格式数据"""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump([{"prompt_asset_id": 1, "ctr": 0.9, "cvr": 0.8}], f)
    yield path
    os.unlink(path)


@pytest.fixture
def csv_file_missing_cvr():
    """缺少 cvr 字段的 CSV"""
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["prompt_asset_id", "ctr"])
        writer.writeheader()
        writer.writerow({"prompt_asset_id": "1", "ctr": "0.8"})
    yield path
    os.unlink(path)


@pytest.fixture
def csv_file_boundary():
    """边界值：score 恰好等于 0.75"""
    # 0.6*ctr + 0.4*cvr = 0.75 → ctr=0.75, cvr=0.75 时 score=0.75
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["prompt_asset_id", "ctr", "cvr"])
        writer.writeheader()
        writer.writerow({"prompt_asset_id": "1", "ctr": "0.75", "cvr": "0.75"})
    yield path
    os.unlink(path)


# --- 常量测试 ---


def test_constants():
    assert CTR_WEIGHT == 0.6
    assert CVR_WEIGHT == 0.4
    assert RECOMMEND_THRESHOLD == 0.75


# --- calculate_performance_score 测试 ---


def test_score_normal():
    """ctr=0.8, cvr=0.6 → 0.6*0.8 + 0.4*0.6 = 0.72"""
    assert calculate_performance_score(0.8, 0.6) == pytest.approx(0.72)


def test_score_high():
    """ctr=0.9, cvr=0.8 → 0.6*0.9 + 0.4*0.8 = 0.86"""
    assert calculate_performance_score(0.9, 0.8) == pytest.approx(0.86)


def test_score_boundary():
    """ctr=0.75, cvr=0.75 → 0.75"""
    assert calculate_performance_score(0.75, 0.75) == pytest.approx(0.75)


# --- import_performance_data 测试 ---


def test_import_csv(csv_file_normal):
    data = import_performance_data(csv_file_normal, format="csv")
    assert len(data) == 1
    assert data[0]["ctr"] == pytest.approx(0.8)
    assert data[0]["cvr"] == pytest.approx(0.6)
    assert data[0]["prompt_asset_id"] == 1


def test_import_csv_recommended(csv_file_recommended):
    data = import_performance_data(csv_file_recommended, format="csv")
    assert len(data) == 1
    assert data[0]["ctr"] == pytest.approx(0.9)


def test_import_json(json_file):
    data = import_performance_data(json_file, format="json")
    assert len(data) == 1
    assert data[0]["ctr"] == pytest.approx(0.9)
    assert data[0]["cvr"] == pytest.approx(0.8)


def test_import_csv_missing_cvr(csv_file_missing_cvr):
    with pytest.raises(ValueError):
        import_performance_data(csv_file_missing_cvr, format="csv")


# --- apply_attribution 测试 ---


def test_apply_not_recommended(db_session, csv_file_normal):
    """ctr=0.8, cvr=0.6 → score=0.72 → is_recommended=False"""
    # 插入 prompt_asset
    db_session.execute(
        text(
            "INSERT INTO prompt_assets (id, project_id, slot_index, prompt_text) "
            "VALUES (1, 1, 0, 'test')"
        )
    )
    db_session.commit()
    data = import_performance_data(csv_file_normal)
    count = apply_attribution(db_session, data)
    assert count == 1
    row = db_session.execute(
        text("SELECT performance_score, is_recommended FROM prompt_assets WHERE id=1")
    ).fetchone()
    assert row[0] == pytest.approx(0.72)
    assert row[1] == 0  # False


def test_apply_recommended(db_session, csv_file_recommended):
    """ctr=0.9, cvr=0.8 → score=0.86 → is_recommended=True"""
    db_session.execute(
        text(
            "INSERT INTO prompt_assets (id, project_id, slot_index, prompt_text) "
            "VALUES (1, 1, 0, 'test')"
        )
    )
    db_session.commit()
    data = import_performance_data(csv_file_recommended)
    count = apply_attribution(db_session, data)
    assert count == 1
    row = db_session.execute(
        text("SELECT performance_score, is_recommended FROM prompt_assets WHERE id=1")
    ).fetchone()
    assert row[0] == pytest.approx(0.86)
    assert row[1] == 1  # True


def test_apply_boundary(db_session, csv_file_boundary):
    """score==0.75 → is_recommended=True"""
    db_session.execute(
        text(
            "INSERT INTO prompt_assets (id, project_id, slot_index, prompt_text) "
            "VALUES (1, 1, 0, 'test')"
        )
    )
    db_session.commit()
    data = import_performance_data(csv_file_boundary)
    count = apply_attribution(db_session, data)
    assert count == 1
    row = db_session.execute(
        text("SELECT performance_score, is_recommended FROM prompt_assets WHERE id=1")
    ).fetchone()
    assert row[0] == pytest.approx(0.75)
    assert row[1] == 1  # True


def test_apply_missing_asset(db_session):
    """不存在的 prompt_asset_id → 跳过，返回 0"""
    data = [{"prompt_asset_id": 999, "ctr": 0.9, "cvr": 0.8}]
    count = apply_attribution(db_session, data)
    assert count == 0
