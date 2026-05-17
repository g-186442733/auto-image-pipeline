import json
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.prompt_asset import PromptAsset
from pipeline.models.qa_record import QARecord
from pipeline.models.project import Project
from pipeline.layers.delivery import build_delivery_package

PROJECT_ID = 42


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    project = Project(id=PROJECT_ID, name="Test Project", asin="B000TEST42")
    session.add(project)
    session.commit()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def tmp_output(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)


class TestBuildDeliveryPackage:
    def test_returns_path_and_manifest_with_passed_slots(self, db_session, tmp_path):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"PNG")
            img1 = f.name
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"PNG")
            img2 = f.name

        asset1 = PromptAsset(
            project_id=PROJECT_ID, slot_index=1, prompt_text="prompt1", image_path=img1
        )
        asset2 = PromptAsset(
            project_id=PROJECT_ID, slot_index=2, prompt_text="prompt2", image_path=img2
        )
        db_session.add_all([asset1, asset2])
        db_session.commit()

        db_session.add_all(
            [
                QARecord(
                    prompt_asset_id=asset1.id,
                    score=80.0,
                    passed=1,
                    check_type="resolution",
                ),
                QARecord(
                    prompt_asset_id=asset2.id,
                    score=80.0,
                    passed=1,
                    check_type="resolution",
                ),
            ]
        )
        db_session.commit()

        result = build_delivery_package(PROJECT_ID, session=db_session)

        assert result == os.path.join("output", str(PROJECT_ID), "delivery")
        manifest_path = os.path.join(result, "manifest.json")
        assert os.path.exists(manifest_path)
        with open(manifest_path) as f:
            manifest = json.load(f)
        assert len(manifest["slots"]) == 2

    def test_no_passed_slots_returns_empty_manifest(self, db_session):
        result = build_delivery_package(PROJECT_ID, session=db_session)

        manifest_path = os.path.join(result, "manifest.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        assert manifest["slots"] == []

    def test_skips_slot_with_none_image_path(self, db_session):
        result = build_delivery_package(PROJECT_ID, session=db_session)

        manifest_path = os.path.join(result, "manifest.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        assert manifest["slots"] == []

    def test_skips_slot_where_file_not_on_disk(self, db_session):
        result = build_delivery_package(PROJECT_ID, session=db_session)

        manifest_path = os.path.join(result, "manifest.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        assert manifest["slots"] == []

    def test_manifest_has_correct_structure(self, db_session):
        result = build_delivery_package(PROJECT_ID, session=db_session)

        manifest_path = os.path.join(result, "manifest.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        assert "project_id" in manifest
        assert "slots" in manifest
        assert "created_at" in manifest
        assert manifest["project_id"] == PROJECT_ID

    def test_copied_image_exists_in_delivery_dir(self, db_session):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"PNG_DATA")
            img = f.name

        asset = PromptAsset(
            project_id=PROJECT_ID, slot_index=5, prompt_text="prompt5", image_path=img
        )
        db_session.add(asset)
        db_session.commit()

        db_session.add(
            QARecord(
                prompt_asset_id=asset.id, score=80.0, passed=1, check_type="resolution"
            )
        )
        db_session.commit()

        result = build_delivery_package(PROJECT_ID, session=db_session)

        assert os.path.exists(os.path.join(result, "slot_5.png"))


class TestDeliveryScoreFilter:
    def test_score_70_included_in_manifest(self, db_session, tmp_path):
        """score=70 (sum=70, NOT < 70) → included."""
        import tempfile as _tmp
        with _tmp.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"PNG")
            img = f.name
        asset = PromptAsset(
            project_id=PROJECT_ID, slot_index=10, prompt_text="p", image_path=img
        )
        db_session.add(asset)
        db_session.commit()
        db_session.add(
            QARecord(prompt_asset_id=asset.id, score=70.0, passed=1, check_type="qa")
        )
        db_session.commit()
        result = build_delivery_package(PROJECT_ID, session=db_session)
        with open(os.path.join(result, "manifest.json")) as f:
            manifest = json.load(f)
        assert any(s["slot_index"] == 10 for s in manifest["slots"])

    def test_score_69_skipped_in_manifest(self, db_session):
        """score=69 (sum=69 < 70) → skipped."""
        import tempfile as _tmp
        with _tmp.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"PNG")
            img = f.name
        asset = PromptAsset(
            project_id=PROJECT_ID, slot_index=11, prompt_text="p", image_path=img
        )
        db_session.add(asset)
        db_session.commit()
        db_session.add(
            QARecord(prompt_asset_id=asset.id, score=69.0, passed=0, check_type="qa")
        )
        db_session.commit()
        result = build_delivery_package(PROJECT_ID, session=db_session)
        with open(os.path.join(result, "manifest.json")) as f:
            manifest = json.load(f)
        assert not any(s["slot_index"] == 11 for s in manifest["slots"])

    def test_mixed_scores_only_high_included(self, db_session):
        """80→include, 69→skip, 70→include."""
        import tempfile as _tmp
        slots_scores = [(20, 80.0), (21, 69.0), (22, 70.0)]
        for slot_index, score in slots_scores:
            with _tmp.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(b"PNG")
                img = f.name
            asset = PromptAsset(
                project_id=PROJECT_ID,
                slot_index=slot_index,
                prompt_text="p",
                image_path=img,
            )
            db_session.add(asset)
            db_session.commit()
            db_session.add(
                QARecord(
                    prompt_asset_id=asset.id,
                    score=score,
                    passed=1 if score >= 70 else 0,
                    check_type="qa",
                )
            )
            db_session.commit()
        result = build_delivery_package(PROJECT_ID, session=db_session)
        with open(os.path.join(result, "manifest.json")) as f:
            manifest = json.load(f)
        slot_indices = [s["slot_index"] for s in manifest["slots"]]
        assert 20 in slot_indices
        assert 22 in slot_indices
        assert 21 not in slot_indices
