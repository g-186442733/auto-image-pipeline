from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.project import Project
from pipeline.layers.revision_lookup import (
    REVISION_TABLE,
    lookup_revision_action,
    auto_apply_revision,
)


class TestLookupRevisionAction:
    def test_match_background(self):
        result = lookup_revision_action("请更换背景图片")
        assert result["action"] == "replace_background"

    def test_match_color(self):
        result = lookup_revision_action("颜色太暗了")
        assert result["action"] == "adjust_color"

    def test_match_text(self):
        result = lookup_revision_action("文字需要修改")
        assert result["action"] == "edit_text"

    def test_match_size(self):
        result = lookup_revision_action("尺寸不对")
        assert result["action"] == "resize"

    def test_match_angle(self):
        result = lookup_revision_action("换个角度拍")
        assert result["action"] == "change_angle"

    def test_match_blur(self):
        result = lookup_revision_action("图片太模糊")
        assert result["action"] == "sharpen"

    def test_match_logo_case_insensitive(self):
        result = lookup_revision_action("请修改LOGO位置")
        assert result["action"] == "update_logo"

    def test_match_layout(self):
        result = lookup_revision_action("排版需要调整")
        assert result["action"] == "adjust_layout"

    def test_fallback_no_keyword(self):
        result = lookup_revision_action("我觉得不太好看")
        assert result["action"] == "manual_review"

    def test_fallback_empty_string(self):
        result = lookup_revision_action("")
        assert result["action"] == "manual_review"

    def test_first_match_wins(self):
        result = lookup_revision_action("背景颜色都要改")
        assert result["action"] == "replace_background"

    def test_result_has_suggestion(self):
        result = lookup_revision_action("背景不行")
        assert "suggestion" in result
        assert len(result["suggestion"]) > 0


@pytest.fixture(autouse=True)
def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    _Session = sessionmaker(bind=engine)
    session = _Session()
    project = Project(name="rev-test")
    session.add(project)
    session.commit()
    yield session, project.id
    session.close()
    Base.metadata.drop_all(engine)


class TestAutoApplyRevision:
    def test_returns_matched_action(self, _db):
        session, pid = _db
        result = auto_apply_revision(session, pid, "main_image", "背景太丑了")
        assert result["slot_name"] == "main_image"
        assert result["action"] == "replace_background"
        assert result["keyword_matched"] == "背景"

    def test_fallback_returns_none_keyword(self, _db):
        session, pid = _db
        result = auto_apply_revision(session, pid, "main_image", "不喜欢")
        assert result["action"] == "manual_review"
        assert result["keyword_matched"] is None

    def test_suggestion_present(self, _db):
        session, pid = _db
        result = auto_apply_revision(session, pid, "slot_a", "文字改一下")
        assert "suggestion" in result
        assert len(result["suggestion"]) > 0


class TestRevisionTable:
    def test_table_not_empty(self):
        assert len(REVISION_TABLE) >= 5

    def test_entries_have_required_keys(self):
        for kw, entry in REVISION_TABLE.items():
            assert "action" in entry, f"Missing 'action' for keyword '{kw}'"
            assert "suggestion" in entry, f"Missing 'suggestion' for keyword '{kw}'"


class TestRevisionGuideRoute:
    @pytest.fixture()
    def client(self):
        from pipeline.web.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_revision_guide_returns_200(self, client):
        resp = client.get("/revision-guide")
        assert resp.status_code == 200

    def test_revision_guide_contains_keywords(self, client):
        resp = client.get("/revision-guide")
        html = resp.data.decode()
        assert "背景" in html
        assert "颜色" in html
        assert "manual_review" in html
