"""TDD tests for review page and QA dashboard (Task 4b)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.project import Project
from pipeline.models.delivery_version import DeliveryVersion
from pipeline.models.qa_record import QARecord
from pipeline.models.prompt_asset import PromptAsset

TEST_PID = 10040

_mem_engine = create_engine("sqlite:///:memory:")
_MemSession = sessionmaker(bind=_mem_engine)


@pytest.fixture(autouse=True)
def _setup_db():
    """每个测试前创建全新的内存数据库。"""
    Base.metadata.create_all(_mem_engine)
    session = _MemSession()
    try:
        # 项目
        session.add(Project(id=TEST_PID, name="Review Test Project", status="draft"))
        # pending 版本（未签收、未自动交付）
        session.add(
            DeliveryVersion(
                id=1,
                project_id=TEST_PID,
                version_number=1,
                trigger="initial",
                change_summary="第一版",
                auto_delivered=False,
                client_signed_at=None,
            )
        )
        session.add(
            DeliveryVersion(
                id=2,
                project_id=TEST_PID,
                version_number=2,
                trigger="revision",
                change_summary="修订版",
                auto_delivered=False,
                client_signed_at=None,
            )
        )
        # 已签收版本（不应出现在 pending 列表）
        from datetime import datetime

        session.add(
            DeliveryVersion(
                id=3,
                project_id=TEST_PID,
                version_number=3,
                trigger="initial",
                change_summary="已签收",
                auto_delivered=True,
                client_signed_at=datetime(2025, 1, 1),
            )
        )
        # QA 记录
        session.add(
            PromptAsset(
                id=100,
                project_id=TEST_PID,
                slot_index=1,
                prompt_text="test prompt",
                negative_prompt="",
                model_name="flux",
                version=1,
            )
        )
        session.add(
            QARecord(
                id=1,
                prompt_asset_id=100,
                check_type="resolution",
                passed=1,
                score=0.95,
                details="通过",
            )
        )
        session.add(
            QARecord(
                id=2,
                prompt_asset_id=100,
                check_type="text_legibility",
                passed=0,
                score=0.3,
                details="文字不清晰",
            )
        )
        session.commit()
    finally:
        session.close()
    yield
    Base.metadata.drop_all(_mem_engine)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("pipeline.web.app.get_session", _MemSession)
    from pipeline.web.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---- /review GET ----


class TestReviewPage:
    def test_review_get_200(self, client):
        resp = client.get("/review")
        assert resp.status_code == 200

    def test_review_shows_pending_versions(self, client):
        resp = client.get("/review")
        # 应该包含 pending 版本的摘要
        assert "第一版".encode() in resp.data
        assert "修订版".encode() in resp.data

    def test_review_excludes_signed_versions(self, client):
        resp = client.get("/review")
        # 已签收版本不应出现
        assert "已签收".encode() not in resp.data

    def test_review_has_approve_button(self, client):
        resp = client.get("/review")
        assert b"approve" in resp.data.lower() or "批准".encode() in resp.data

    def test_review_has_reject_button(self, client):
        resp = client.get("/review")
        assert b"reject" in resp.data.lower() or "驳回".encode() in resp.data


# ---- /review/<id>/approve POST ----


class TestApproveReject:
    def test_approve_redirects(self, client):
        resp = client.post("/review/1/approve", follow_redirects=False)
        assert resp.status_code in (302, 303)

    def test_approve_sets_signed(self, client):
        client.post("/review/1/approve")
        session = _MemSession()
        try:
            dv = session.get(DeliveryVersion, 1)
            assert dv.client_signed_at is not None
        finally:
            session.close()

    def test_approve_not_found(self, client):
        resp = client.post("/review/9999/approve")
        assert resp.status_code == 404

    def test_reject_redirects(self, client):
        resp = client.post(
            "/review/2/reject",
            data={"reason": "颜色不对"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

    def test_reject_updates_record(self, client):
        client.post("/review/2/reject", data={"reason": "颜色不对"})
        session = _MemSession()
        try:
            dv = session.get(DeliveryVersion, 2)
            # rejected 版本的 change_summary 中应包含驳回原因
            assert "颜色不对" in (dv.change_summary or "")
        finally:
            session.close()

    def test_reject_not_found(self, client):
        resp = client.post("/review/9999/reject")
        assert resp.status_code == 404


# ---- /qa-dashboard GET ----


class TestQADashboard:
    def test_qa_dashboard_get_200(self, client):
        resp = client.get("/qa-dashboard")
        assert resp.status_code == 200

    def test_qa_dashboard_shows_records(self, client):
        resp = client.get("/qa-dashboard")
        assert b"resolution" in resp.data
        assert b"text_legibility" in resp.data

    def test_qa_dashboard_shows_pass_rate(self, client):
        resp = client.get("/qa-dashboard")
        # 2 条记录中 1 条通过 → 50%
        assert b"50" in resp.data
