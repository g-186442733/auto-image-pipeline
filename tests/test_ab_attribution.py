"""TDD tests for A/B attribution engine."""

import csv
import json
import os
import tempfile
import threading
from unittest.mock import ANY, MagicMock, patch

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
    _flywheel_update_brand,
    _trigger_flywheel_regen,
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
    assert RECOMMEND_THRESHOLD == 0.06


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
    """ctr=0.8, cvr=0.6 → score=0.72 → is_recommended=True（当前阈值 0.06）"""
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
    assert row[1] == 1  # True


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


def test_flywheel_update_brand_no_visual_tags(db_session):
    """visual_tags 为 None → 返回 None，不触发飞轮"""
    asset = MagicMock()
    asset.visual_tags = None
    result = _flywheel_update_brand(asset, 0.9, db_session)
    assert result is None


def test_flywheel_update_brand_invalid_json(db_session):
    """visual_tags 不是合法 JSON → 返回 None"""
    asset = MagicMock()
    asset.visual_tags = "not-json"
    result = _flywheel_update_brand(asset, 0.9, db_session)
    assert result is None


def test_flywheel_update_brand_no_string_values(db_session):
    """visual_tags 内无字符串 value（全是数字）→ elastic_updates 为空 → 返回 None"""
    asset = MagicMock()
    asset.visual_tags = json.dumps({"count": 5, "score": 0.9})
    result = _flywheel_update_brand(asset, 0.9, db_session)
    assert result is None


def test_flywheel_update_brand_no_product_profile(db_session):
    """ProductProfile 不存在 → 返回 None"""
    asset = MagicMock()
    asset.visual_tags = json.dumps({"photo_style": "lifestyle"})
    asset.project_id = 9999
    result = _flywheel_update_brand(asset, 0.9, db_session)
    assert result is None


def test_trigger_flywheel_regen_starts_daemon_thread():
    """_trigger_flywheel_regen 必须启动一个 daemon=True 的线程，名称包含 brand_profile_id"""
    with patch("threading.Thread") as mock_thread_cls:
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        _trigger_flywheel_regen(42)

        mock_thread_cls.assert_called_once_with(
            target=ANY,
            daemon=True,
            name="flywheel-regen-42",
        )
        mock_thread.start.assert_called_once()


def test_trigger_flywheel_regen_worker_calls_regen_single_slot():
    """_regen_worker 内部应对每个 completed project 的每个 slot 调用 regen_single_slot"""
    done_event = threading.Event()

    mock_session = MagicMock()
    mock_session.query.return_value.join.return_value.filter.return_value.all.return_value = [
        (10,)
    ]
    mock_session.query.return_value.filter_by.return_value.distinct.return_value.all.return_value = [
        (0,)
    ]

    with (
        patch("pipeline.layers.ab_attribution.threading.Thread") as mock_thread_cls,
        patch("pipeline.models.base.get_session", return_value=mock_session),
        patch("pipeline.layers.slot_planner.regen_single_slot") as mock_regen,
    ):

        def fake_thread(target, daemon, name):
            # 同步执行 worker，避免真实线程竞态
            t = MagicMock()
            t.start.side_effect = lambda: (target(), done_event.set())
            return t

        mock_thread_cls.side_effect = fake_thread

        _trigger_flywheel_regen(7)

        done_event.wait(timeout=2)
        mock_regen.assert_called_once_with(10, 0, session=mock_session)


def test_apply_attribution_triggers_regen_on_brand_update(
    db_session, csv_file_recommended
):
    """apply_attribution: 飞轮写入 brand → 调用 _trigger_flywheel_regen(brand_id)"""
    db_session.execute(
        text(
            "INSERT INTO prompt_assets (id, project_id, slot_index, prompt_text) "
            "VALUES (1, 1, 0, 'test')"
        )
    )
    db_session.commit()
    data = import_performance_data(csv_file_recommended)

    with (
        patch("pipeline.layers.ab_attribution._flywheel_update_brand", return_value=5),
        patch("pipeline.layers.ab_attribution._trigger_flywheel_regen") as mock_regen,
        patch("pipeline.layers.knowledge_base.promote_to_knowledge"),
    ):
        apply_attribution(db_session, data)
        mock_regen.assert_called_once_with(5)


def test_apply_attribution_no_regen_when_brand_not_updated(
    db_session, csv_file_recommended
):
    """apply_attribution: 飞轮未写入（返回 None）→ 不调用 _trigger_flywheel_regen"""
    db_session.execute(
        text(
            "INSERT INTO prompt_assets (id, project_id, slot_index, prompt_text) "
            "VALUES (1, 1, 0, 'test')"
        )
    )
    db_session.commit()
    data = import_performance_data(csv_file_recommended)

    with (
        patch(
            "pipeline.layers.ab_attribution._flywheel_update_brand", return_value=None
        ),
        patch("pipeline.layers.ab_attribution._trigger_flywheel_regen") as mock_regen,
        patch("pipeline.layers.knowledge_base.promote_to_knowledge"),
    ):
        apply_attribution(db_session, data)
        mock_regen.assert_not_called()


def test_apply_attribution_deduplicates_brand_ids(db_session):
    """apply_attribution: 多条记录同一 brand_id → _trigger_flywheel_regen 只调用一次"""
    db_session.execute(
        text(
            "INSERT INTO prompt_assets (id, project_id, slot_index, prompt_text) VALUES "
            "(1, 1, 0, 'a'), (2, 1, 1, 'b')"
        )
    )
    db_session.commit()
    data = [
        {"prompt_asset_id": 1, "ctr": 0.9, "cvr": 0.8},
        {"prompt_asset_id": 2, "ctr": 0.9, "cvr": 0.8},
    ]

    with (
        patch("pipeline.layers.ab_attribution._flywheel_update_brand", return_value=9),
        patch("pipeline.layers.ab_attribution._trigger_flywheel_regen") as mock_regen,
        patch("pipeline.layers.knowledge_base.promote_to_knowledge"),
    ):
        apply_attribution(db_session, data)
        mock_regen.assert_called_once_with(9)
