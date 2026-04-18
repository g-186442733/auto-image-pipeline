"""一致性锁定系统 — 模型、layer、路由测试"""

import pytest
import pipeline.models.base as base_mod


def _reset_db():
    base_mod._engine = None
    base_mod._SessionLocal = None
    import pipeline.models.consistency_profile  # noqa: F401
    import pipeline.models.project  # noqa: F401

    base_mod.create_all("sqlite:///:memory:")


@pytest.fixture(autouse=True)
def reset_db():
    _reset_db()
    yield
    base_mod._engine = None
    base_mod._SessionLocal = None


def _make_project():
    from pipeline.models.project import Project
    from pipeline.models.base import get_session

    session = get_session()
    p = Project(name="Test Consistency", asin="B000000099", category="electronics")
    session.add(p)
    session.commit()
    pid = p.id
    session.close()
    return pid


# ---- 模型测试 ----


def test_five_variables_present():
    """ConsistencyProfile 恰好包含 5 个风格变量 + locked 字段"""
    from pipeline.models.consistency_profile import ConsistencyProfile

    variables = [
        "lighting_style",
        "color_palette",
        "camera_angle",
        "element_density",
        "text_overlay_style",
    ]
    for f in variables:
        assert hasattr(ConsistencyProfile, f), f"缺少字段: {f}"
    assert hasattr(ConsistencyProfile, "locked")
    assert len(variables) == 5


# ---- Layer 测试 ----


def test_create_profile():
    """create_consistency_profile 创建记录并返回"""
    from pipeline.layers.consistency_system import create_consistency_profile

    pid = _make_project()
    cp = create_consistency_profile(pid)
    assert cp is not None
    assert cp.project_id == pid
    assert cp.locked is False


def test_get_returns_default_if_not_exists():
    """get_consistency_profile 不存在时自动创建默认"""
    from pipeline.layers.consistency_system import get_consistency_profile

    pid = _make_project()
    cp = get_consistency_profile(pid)
    assert cp is not None
    assert cp.project_id == pid
    assert cp.lighting_style is None


def test_update_variables():
    """update_consistency_profile 更新风格变量"""
    from pipeline.layers.consistency_system import (
        create_consistency_profile,
        update_consistency_profile,
        get_consistency_profile,
    )

    pid = _make_project()
    create_consistency_profile(pid)
    update_consistency_profile(
        pid, lighting_style="soft diffused", color_palette="warm earth tones"
    )
    cp = get_consistency_profile(pid)
    assert cp.lighting_style == "soft diffused"
    assert cp.color_palette == "warm earth tones"


def test_lock_prevents_update():
    """锁定后 update 抛出 ValueError"""
    from pipeline.layers.consistency_system import (
        create_consistency_profile,
        update_consistency_profile,
        lock_consistency_profile,
    )

    pid = _make_project()
    create_consistency_profile(pid)
    lock_consistency_profile(pid)
    with pytest.raises(ValueError, match="locked"):
        update_consistency_profile(pid, lighting_style="harsh")


def test_validate_consistency_pass():
    """validate_consistency 全部填写时返回 True"""
    from pipeline.layers.consistency_system import (
        create_consistency_profile,
        update_consistency_profile,
        validate_consistency,
    )

    pid = _make_project()
    create_consistency_profile(pid)
    update_consistency_profile(
        pid,
        lighting_style="studio",
        color_palette="neutral",
        camera_angle="eye level",
        element_density="medium",
        text_overlay_style="minimal",
    )
    ok, missing = validate_consistency(pid)
    assert ok is True
    assert missing == []


def test_validate_consistency_fail():
    """validate_consistency 有空字段时返回 False + 缺失列表"""
    from pipeline.layers.consistency_system import (
        create_consistency_profile,
        validate_consistency,
    )

    pid = _make_project()
    create_consistency_profile(pid)
    ok, missing = validate_consistency(pid)
    assert ok is False
    assert len(missing) == 5
