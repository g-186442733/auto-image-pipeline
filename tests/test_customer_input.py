"""TDD 测试：引导式客户输入 UI（10 组问题分步表单）"""

import json
import pytest
import pipeline.models.base as base_mod


def _reset_db():
    base_mod._engine = None
    base_mod._SessionLocal = None
    base_mod.create_all("sqlite:///:memory:")


@pytest.fixture(autouse=True)
def reset_db():
    _reset_db()
    yield
    base_mod._engine = None
    base_mod._SessionLocal = None


@pytest.fixture
def client():
    from pipeline.web.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------- 必填字段 ----------
REQUIRED_FIELDS = {
    "product_name": "蓝牙耳机",
    "asin": "B012345678",
    "product_category": "Electronics",
    "key_selling_points": "降噪,长续航",
    "target_age": "25-35",
    "target_gender": "不限",
    "lifestyle": "都市白领",
    "purchase_motivation": "通勤使用",
    "competitor_asins": "B098765432",
    "differentiation": "更好的降噪算法",
    "primary_color": "#1a1a2e",
    "style_keywords": "科技感,简约",
    "budget_level": "mid",
    "deadline": "7天",
}


def _full_form_data(**overrides):
    """返回完整的表单数据（必填+可选）"""
    data = {**REQUIRED_FIELDS}
    # 可选字段
    data.update(
        {
            "reference_urls": "",
            "brand_history": "",
            "founding_idea": "",
            "usp_core": "",
            "usp_proof": "",
            "pain_points": "",
            "usage_scenario": "",
            "lifestyle_image": "",
            "season_relevance": "",
            "holiday_promo": "",
        }
    )
    data.update(overrides)
    return data


# ========== GET /input/new ==========
class TestGetInputNew:
    def test_returns_200(self, client):
        resp = client.get("/input/new")
        assert resp.status_code == 200

    def test_contains_form(self, client):
        resp = client.get("/input/new")
        html = resp.data.decode()
        assert "<form" in html
        assert 'name="product_name"' in html

    def test_contains_step_indicator(self, client):
        resp = client.get("/input/new")
        html = resp.data.decode()
        assert "step" in html.lower()


# ========== POST /input/new ==========
class TestPostInputNew:
    def test_success_redirects(self, client):
        resp = client.post("/input/new", data=_full_form_data())
        assert resp.status_code == 302
        assert "/project/" in resp.headers["Location"]

    def test_creates_project_with_brief(self, client):
        client.post("/input/new", data=_full_form_data())
        session = base_mod.get_session()
        try:
            from pipeline.models.project import Project

            project = session.query(Project).first()
            assert project is not None
            assert project.name == "蓝牙耳机"
            brief = json.loads(project.customer_brief)
            assert brief["asin"] == "B012345678"
            assert brief["primary_color"] == "#1a1a2e"
        finally:
            session.close()

    def test_missing_required_returns_400(self, client):
        data = _full_form_data()
        del data["product_name"]
        resp = client.post("/input/new", data=data)
        assert resp.status_code == 400

    def test_missing_multiple_required_returns_400(self, client):
        resp = client.post("/input/new", data={"budget_level": "high"})
        assert resp.status_code == 400


# ========== GET /input/<id>/edit ==========
class TestGetInputEdit:
    def _create_project(self, client):
        resp = client.post("/input/new", data=_full_form_data())
        # 从 redirect 拿 project id
        loc = resp.headers["Location"]
        project_id = int(loc.rstrip("/").split("/")[-1])
        return project_id

    def test_returns_200(self, client):
        pid = self._create_project(client)
        resp = client.get(f"/input/{pid}/edit")
        assert resp.status_code == 200

    def test_prefills_data(self, client):
        pid = self._create_project(client)
        resp = client.get(f"/input/{pid}/edit")
        html = resp.data.decode()
        assert "蓝牙耳机" in html
        assert "B012345678" in html

    def test_nonexistent_returns_404(self, client):
        resp = client.get("/input/99999/edit")
        assert resp.status_code == 404


# ========== POST /input/<id>/edit ==========
class TestPostInputEdit:
    def _create_project(self, client):
        resp = client.post("/input/new", data=_full_form_data())
        loc = resp.headers["Location"]
        return int(loc.rstrip("/").split("/")[-1])

    def test_update_success_redirects(self, client):
        pid = self._create_project(client)
        resp = client.post(
            f"/input/{pid}/edit",
            data=_full_form_data(product_name="无线耳机"),
        )
        assert resp.status_code == 302

    def test_update_persists(self, client):
        pid = self._create_project(client)
        client.post(
            f"/input/{pid}/edit",
            data=_full_form_data(product_name="无线耳机"),
        )
        session = base_mod.get_session()
        try:
            from pipeline.models.project import Project

            project = session.get(Project, pid)
            assert project.name == "无线耳机"
            brief = json.loads(project.customer_brief)
            assert brief["product_name"] == "无线耳机"
        finally:
            session.close()

    def test_nonexistent_returns_404(self, client):
        resp = client.post("/input/99999/edit", data=_full_form_data())
        assert resp.status_code == 404
