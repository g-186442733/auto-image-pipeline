"""品牌画像卡 — 模型、layer、路由测试"""

import pytest
import pipeline.models.base as base_mod


def _reset_db():
    base_mod._engine = None
    base_mod._SessionLocal = None
    # 确保 BrandProfile 被 import，create_all 才能建表
    import pipeline.models.brand_profile  # noqa: F401
    import pipeline.models.project  # noqa: F401

    base_mod.create_all("sqlite:///:memory:")


@pytest.fixture(autouse=True)
def reset_db():
    _reset_db()
    yield
    base_mod._engine = None
    base_mod._SessionLocal = None


def _make_project():
    """创建测试用 Project"""
    from pipeline.models.project import Project
    from pipeline.models.base import get_session

    session = get_session()
    p = Project(name="Test Brand", asin="B000000001", category="fashion")
    session.add(p)
    session.commit()
    pid = p.id
    session.close()
    return pid


# ---- 模型测试 ----


def test_brand_profile_model_has_10_dimensions():
    """BrandProfile 恰好包含 10 个维度字段"""
    from pipeline.models.brand_profile import BrandProfile

    dimension_fields = [
        "brand_tone",
        "color_system",
        "font_preference",
        "photo_style",
        "model_type",
        "scene_preference",
        "composition_preference",
        "material_texture",
        "competitor_positioning",
        "brand_story",
    ]
    for f in dimension_fields:
        assert hasattr(BrandProfile, f), f"缺少字段: {f}"
    assert len(dimension_fields) == 10


def test_brand_profile_crud():
    """CRUD 基本操作"""
    from pipeline.models.brand_profile import BrandProfile
    from pipeline.models.base import get_session

    session = get_session()
    bp = BrandProfile(brand_tone="极简高端", color_system="黑白灰")
    session.add(bp)
    session.commit()

    loaded = session.query(BrandProfile).filter_by(id=bp.id).first()
    assert loaded is not None
    assert loaded.brand_tone == "极简高端"
    assert loaded.color_system == "黑白灰"
    assert loaded.photo_style is None
    session.close()


# ---- Layer 测试 ----


def test_build_brand_profile_returns_empty_if_missing():
    """不存在 ProductProfile 时，返回空 BrandProfile（project_id 为 None）"""
    from pipeline.layers.brand_profiler import build_brand_profile

    pid = _make_project()
    bp = build_brand_profile(pid)
    assert bp is not None
    assert bp.brand_tone is None


def test_build_brand_profile_returns_existing_via_product():
    """已存在时经由 ProductProfile → BrandProfile 链路返回正确记录"""
    from pipeline.models.brand_profile import BrandProfile
    from pipeline.models.product_profile import ProductProfile
    from pipeline.models.base import get_session
    from pipeline.layers.brand_profiler import build_brand_profile

    pid = _make_project()
    session = get_session()
    bp_obj = BrandProfile(brand_tone="复古")
    session.add(bp_obj)
    session.flush()
    session.add(ProductProfile(project_id=pid, brand_profile_id=bp_obj.id, tenant_id=1))
    session.commit()
    session.close()

    bp = build_brand_profile(pid)
    assert bp.brand_tone == "复古"


# ---- 路由测试 ----


@pytest.fixture
def client():
    from pipeline.web.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        from tests.conftest import inject_auth

        inject_auth(c)
        yield c


def test_brand_profile_get_200(client):
    """GET /brand-profile/<id> 返回 200"""
    pid = _make_project()
    resp = client.get(f"/brand-profile/{pid}")
    assert resp.status_code == 200
    assert "品牌画像" in resp.data.decode()


def test_brand_profile_get_404(client):
    """不存在的项目返回 404"""
    resp = client.get("/brand-profile/99999")
    assert resp.status_code == 404


def test_brand_profile_post_updates(client):
    """POST 更新维度数据并 redirect"""
    pid = _make_project()
    resp = client.post(
        f"/brand-profile/{pid}",
        data={
            "brand_tone": "潮流街头",
            "color_system": "荧光色系",
            "font_preference": "",
            "photo_style": "",
            "model_type": "",
            "scene_preference": "",
            "composition_preference": "",
            "material_texture": "",
            "competitor_positioning": "",
            "brand_story": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    # 验证数据已保存
    resp2 = client.get(f"/brand-profile/{pid}")
    assert "潮流街头" in resp2.data.decode()
    assert "荧光色系" in resp2.data.decode()
