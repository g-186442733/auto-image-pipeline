"""TDD tests for delivery package 5 items."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from pipeline.layers.delivery import (
    generate_delivery_notes,
    generate_preview_html,
    generate_spec_check,
    generate_version_log,
    build_delivery_package,
)


@pytest.fixture
def tmp_output(tmp_path):
    """Create a temp output dir with a fake project image."""
    project_dir = tmp_path / "1"
    assets_dir = project_dir / "assets"
    assets_dir.mkdir(parents=True)
    # Create a 200x300 test image
    img = Image.new("RGB", (200, 300), color="red")
    img.save(str(assets_dir / "hero.png"))
    img2 = Image.new("RGB", (800, 600), color="blue")
    img2.save(str(assets_dir / "lifestyle.jpg"), "JPEG")
    return str(tmp_path)


@pytest.fixture
def mock_session():
    session = MagicMock()
    # Project mock
    project = MagicMock()
    project.id = 1
    project.name = "Test Project"
    project.asin = "B000TEST"
    project.category = "Electronics"
    project.status = "delivered"
    project.notes = "Some notes"
    project.customer_brief = "Brief text"
    session.get.return_value = project
    # SlotPlan queries return empty by default
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    return session


class TestGeneratePreviewHtml:
    def test_creates_file(self, tmp_output):
        path = generate_preview_html(1, tmp_output)
        assert os.path.isfile(path)
        assert path.endswith("preview_list.html")

    def test_no_inline_style(self, tmp_output):
        path = generate_preview_html(1, tmp_output)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "<style>" not in content.lower()
        assert "<style " not in content.lower()

    def test_references_external_css(self, tmp_output):
        path = generate_preview_html(1, tmp_output)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "stylesheet" in content

    def test_lists_images(self, tmp_output):
        path = generate_preview_html(1, tmp_output)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "hero.png" in content
        assert "lifestyle.jpg" in content


class TestGenerateDeliveryNotes:
    def test_creates_file(self, tmp_output, mock_session):
        path = generate_delivery_notes(1, tmp_output, session=mock_session)
        assert os.path.isfile(path)
        assert path.endswith("delivery_notes.md")

    def test_contains_project_info(self, tmp_output, mock_session):
        path = generate_delivery_notes(1, tmp_output, session=mock_session)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "Test Project" in content


class TestGenerateVersionLog:
    def test_creates_valid_json(self, tmp_output, mock_session):
        path = generate_version_log(1, tmp_output, session=mock_session)
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "project_id" in data
        assert "entries" in data


class TestGenerateSpecCheck:
    def test_has_dimensions(self, tmp_output):
        path = generate_spec_check(1, tmp_output)
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 2
        for item in data:
            assert "width" in item
            assert "height" in item
            assert "format" in item
            assert "filesize_bytes" in item

    def test_correct_dimensions(self, tmp_output):
        path = generate_spec_check(1, tmp_output)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        by_file = {os.path.basename(d["file"]): d for d in data}
        assert by_file["hero.png"]["width"] == 200
        assert by_file["hero.png"]["height"] == 300
        assert by_file["lifestyle.jpg"]["width"] == 800
        assert by_file["lifestyle.jpg"]["height"] == 600


class TestCreateDeliveryPackage:
    def test_produces_5_items(self, tmp_output, mock_session):
        """Delivery dir should have manifest + preview_list + delivery_notes + version_log + spec_check."""
        asset = MagicMock()
        asset.id = 1
        asset.slot_index = 0
        asset.project_id = 1
        asset.image_path = os.path.join(tmp_output, "1", "assets", "hero.png")

        qa = MagicMock()
        qa.score = 90

        def query_side_effect(model):
            mock_q = MagicMock()
            if model.__tablename__ == "prompt_assets":
                mock_q.filter.return_value.order_by.return_value.all.return_value = [
                    asset
                ]
            elif model.__tablename__ == "qa_records":
                mock_q.filter.return_value.all.return_value = [qa]
            else:
                mock_q.filter.return_value.order_by.return_value.all.return_value = []
                mock_q.filter.return_value.all.return_value = []
            return mock_q

        mock_session.query.side_effect = query_side_effect

        build_delivery_package(1, session=mock_session, output_dir=tmp_output)

        delivery_dir = os.path.join(tmp_output, "1", "delivery")
        expected = {
            "manifest.json",
            "preview_list.html",
            "delivery_notes.md",
            "version_log.json",
            "spec_check.json",
        }
        actual = set(
            f
            for f in os.listdir(delivery_dir)
            if os.path.isfile(os.path.join(delivery_dir, f))
        )
        assert expected.issubset(actual), f"Missing: {expected - actual}"
