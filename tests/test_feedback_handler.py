"""TDD tests for client feedback system (Task 10)."""

import json
import pytest

from pipeline.models.base import Base, get_engine, get_session, create_all
from pipeline.models.project import Project
from pipeline.models.client_feedback import ClientFeedback
from pipeline.layers.feedback_handler import (
    submit_feedback,
    get_feedback_summary,
    apply_feedback,
)

TEST_PID = 10010


@pytest.fixture(autouse=True)
def _setup_db():
    """Ensure tables exist and clean up test data."""
    create_all()
    session = get_session()
    try:
        session.query(ClientFeedback).filter_by(project_id=TEST_PID).delete()
        session.query(Project).filter_by(id=TEST_PID).delete()
        session.commit()
        session.add(Project(id=TEST_PID, name="Feedback Test Project", status="draft"))
        session.commit()
    finally:
        session.close()
    yield
    session = get_session()
    try:
        session.query(ClientFeedback).filter_by(project_id=TEST_PID).delete()
        session.query(Project).filter_by(id=TEST_PID).delete()
        session.commit()
    finally:
        session.close()


class TestSubmitFeedback:
    def test_creates_record(self):
        session = get_session()
        try:
            fb = submit_feedback(session, TEST_PID, "slot_1", "approve", "Looks good")
            assert fb.id is not None
            assert fb.project_id == TEST_PID
            assert fb.slot_name == "slot_1"
            assert fb.feedback_type == "approve"
            assert fb.feedback_text == "Looks good"
        finally:
            session.close()

    def test_rejects_invalid_type(self):
        session = get_session()
        try:
            with pytest.raises(ValueError):
                submit_feedback(session, TEST_PID, "slot_1", "invalid_type", "")
        finally:
            session.close()

    def test_multiple_feedback_same_slot(self):
        session = get_session()
        try:
            submit_feedback(session, TEST_PID, "slot_1", "revise", "Change color")
            submit_feedback(session, TEST_PID, "slot_1", "approve", "Now OK")
            records = (
                session.query(ClientFeedback)
                .filter_by(project_id=TEST_PID, slot_name="slot_1")
                .all()
            )
            assert len(records) == 2
        finally:
            session.close()


class TestGetFeedbackSummary:
    def test_returns_dict_with_slots(self):
        session = get_session()
        try:
            submit_feedback(session, TEST_PID, "slot_1", "approve", "")
            submit_feedback(session, TEST_PID, "slot_2", "revise", "Fix text")
            summary = get_feedback_summary(session, TEST_PID)
            assert isinstance(summary, dict)
            assert "slot_1" in summary
            assert "slot_2" in summary
            assert summary["slot_1"]["latest_type"] == "approve"
            assert summary["slot_2"]["latest_type"] == "revise"
        finally:
            session.close()

    def test_empty_project(self):
        session = get_session()
        try:
            summary = get_feedback_summary(session, TEST_PID)
            assert summary == {}
        finally:
            session.close()


class TestApplyFeedback:
    def test_approve_marks_done(self):
        session = get_session()
        try:
            submit_feedback(session, TEST_PID, "slot_1", "approve", "")
            result = apply_feedback(session, TEST_PID)
            assert "slot_1" in result
            assert result["slot_1"] == "done"
        finally:
            session.close()

    def test_revise_marks_pending(self):
        session = get_session()
        try:
            submit_feedback(session, TEST_PID, "slot_1", "revise", "Needs changes")
            result = apply_feedback(session, TEST_PID)
            assert result["slot_1"] == "needs_revision"
        finally:
            session.close()

    def test_reject_marks_rejected(self):
        session = get_session()
        try:
            submit_feedback(session, TEST_PID, "slot_1", "reject", "Not usable")
            result = apply_feedback(session, TEST_PID)
            assert result["slot_1"] == "rejected"
        finally:
            session.close()


class TestFeedbackRoutes:
    @pytest.fixture()
    def client(self):
        from pipeline.web.app import create_app

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_get_feedback_page(self, client):
        resp = client.get(f"/project/{TEST_PID}/feedback")
        assert resp.status_code == 200
        assert b"feedback" in resp.data.lower() or b"Feedback" in resp.data

    def test_post_feedback_redirects(self, client):
        resp = client.post(
            f"/project/{TEST_PID}/feedback",
            data={
                "slot_name": "slot_1",
                "feedback_type": "approve",
                "feedback_text": "Great",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)

    def test_post_feedback_creates_record(self, client):
        client.post(
            f"/project/{TEST_PID}/feedback",
            data={
                "slot_name": "slot_1",
                "feedback_type": "revise",
                "feedback_text": "Fix color",
            },
        )
        session = get_session()
        try:
            fb = (
                session.query(ClientFeedback)
                .filter_by(project_id=TEST_PID, slot_name="slot_1")
                .order_by(ClientFeedback.created_at.desc())
                .first()
            )
            assert fb is not None
            assert fb.feedback_type == "revise"
        finally:
            session.close()
