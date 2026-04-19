import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.models.base import Base
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.review_cluster import ReviewCluster
from pipeline.models.qa_entry import QAEntry
from pipeline.models.image_brief import ImageBrief
from pipeline.models.customer_brief import CustomerBrief


SAMPLE_PROJECT_ID = 42

FAKE_BRIEF_JSON = json.dumps(
    {
        "slots": [
            {
                "slot_index": 0,
                "concept": "Hero shot showing premium build quality",
                "copy_overlay": "Unmatched Sound. Unmatched Comfort.",
                "visual_style": "lifestyle",
            },
            {
                "slot_index": 1,
                "concept": "Close-up of ear cushion comfort",
                "copy_overlay": "Designed for All-Day Wear",
                "visual_style": "detail",
            },
        ]
    }
)


def _make_listing(project_id=SAMPLE_PROJECT_ID):
    return CompetitorListing(
        asin="B09V3KXJPB",
        title="Premium Wireless Headphones",
        bullet_points="Great sound|Comfortable|Long battery",
        description="High-end wireless headphones",
        selling_points_map='{"sound": "excellent", "comfort": "high"}',
        project_id=project_id,
    )


def _make_clusters():
    return [
        ReviewCluster(
            asin="B09V3KXJPB",
            cluster_label="sound_quality",
            sentiment="positive",
            count=10,
            representative_reviews='["Great sound"]',
        ),
        ReviewCluster(
            asin="B09V3KXJPB",
            cluster_label="comfort",
            sentiment="mixed",
            count=5,
            representative_reviews='["Comfortable but tight"]',
        ),
    ]


def _make_qa_entries():
    return [
        QAEntry(
            asin="B09V3KXJPB",
            question="Is it noise cancelling?",
            answer="Yes, active noise cancellation.",
            frequency=15,
            category="features",
        ),
        QAEntry(
            asin="B09V3KXJPB",
            question="How long does battery last?",
            answer="Up to 30 hours.",
            frequency=8,
            category="battery",
        ),
    ]


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestGenerateBrief:
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_returns_list_of_image_briefs(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = FAKE_BRIEF_JSON
        result = generate_brief(
            SAMPLE_PROJECT_ID,
            _make_listing(),
            _make_clusters(),
            _make_qa_entries(),
            session=db_session,
        )
        assert isinstance(result, list)
        assert all(isinstance(b, ImageBrief) for b in result)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_brief_has_correct_project_id(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = FAKE_BRIEF_JSON
        result = generate_brief(
            SAMPLE_PROJECT_ID,
            _make_listing(),
            _make_clusters(),
            _make_qa_entries(),
            session=db_session,
        )
        assert result[0].project_id == SAMPLE_PROJECT_ID

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_returns_one_brief_per_slot(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = FAKE_BRIEF_JSON
        result = generate_brief(
            SAMPLE_PROJECT_ID,
            _make_listing(),
            _make_clusters(),
            _make_qa_entries(),
            session=db_session,
        )
        assert len(result) == 2
        assert result[0].slot_index == 0
        assert result[1].slot_index == 1

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_brief_written_to_database(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = FAKE_BRIEF_JSON
        generate_brief(
            SAMPLE_PROJECT_ID,
            _make_listing(),
            _make_clusters(),
            _make_qa_entries(),
            session=db_session,
        )
        briefs = db_session.query(ImageBrief).all()
        assert len(briefs) == 2
        assert all(b.project_id == SAMPLE_PROJECT_ID for b in briefs)

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_gemini_failure_returns_default_brief(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.side_effect = Exception("API error")
        result = generate_brief(
            SAMPLE_PROJECT_ID,
            _make_listing(),
            _make_clusters(),
            _make_qa_entries(),
            session=db_session,
        )
        assert isinstance(result, list)
        assert len(result) == 1

    @patch.dict(os.environ, {"GOOGLE_API_KEY": ""})
    def test_no_api_key_returns_default_brief(self, db_session):
        from pipeline.layers.brief_generator import generate_brief

        result = generate_brief(
            SAMPLE_PROJECT_ID,
            _make_listing(),
            _make_clusters(),
            _make_qa_entries(),
            session=db_session,
        )
        assert isinstance(result, list)
        assert len(result) == 1

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_invalid_json_response_returns_default(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = "not valid json {{{{"
        result = generate_brief(
            SAMPLE_PROJECT_ID,
            _make_listing(),
            _make_clusters(),
            _make_qa_entries(),
            session=db_session,
        )
        assert isinstance(result, list)
        assert len(result) == 1

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_gemini_prompt_includes_listing_and_reviews(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = FAKE_BRIEF_JSON
        generate_brief(
            SAMPLE_PROJECT_ID,
            _make_listing(),
            _make_clusters(),
            _make_qa_entries(),
            session=db_session,
        )
        mock_gemini.assert_called_once()
        prompt = mock_gemini.call_args[0][0]
        assert "Premium Wireless Headphones" in prompt
        assert "sound_quality" in prompt
        assert "noise cancelling" in prompt


class TestCallGeminiBrief:
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    def test_call_gemini_returns_text(self):
        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value.generate_content.return_value.text = (
            '{"slots": []}'
        )
        google_mock = MagicMock()
        google_mock.generativeai = mock_genai

        with patch.dict(
            sys.modules, {"google": google_mock, "google.generativeai": mock_genai}
        ):
            from pipeline.layers.brief_generator import _call_gemini

            result = _call_gemini("Generate brief")
            assert result == '{"slots": []}'

    @patch.dict(os.environ, {"GOOGLE_API_KEY": ""})
    def test_call_gemini_no_key_returns_empty_json(self):
        from pipeline.layers.brief_generator import _call_gemini

        result = _call_gemini("anything")
        assert result == "{}"


class TestCustomerBriefInjection:
    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_three_filled_fields_appear_in_prompt(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = FAKE_BRIEF_JSON
        cb = CustomerBrief(
            project_id=SAMPLE_PROJECT_ID,
            brand_voice="Bold and modern",
            target_audience="Gen Z",
            product_usp="Eco-friendly",
        )
        db_session.add(cb)
        db_session.commit()

        generate_brief(
            SAMPLE_PROJECT_ID,
            _make_listing(),
            _make_clusters(),
            _make_qa_entries(),
            session=db_session,
        )

        prompt = mock_gemini.call_args[0][0]
        assert "--- Customer Brief ---" in prompt
        assert "Brand Voice: Bold and modern" in prompt
        assert "Target Audience: Gen Z" in prompt
        assert "Product USP: Eco-friendly" in prompt
        assert "Budget Range" not in prompt
        assert "Timeline" not in prompt
        assert "Special Instructions" not in prompt
        assert "Visual Preferences" not in prompt
        assert "Competitor References" not in prompt
        assert "Campaign Goal" not in prompt
        assert "Reference Images" not in prompt

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_no_customer_brief_still_works(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = FAKE_BRIEF_JSON
        result = generate_brief(
            SAMPLE_PROJECT_ID,
            _make_listing(),
            _make_clusters(),
            _make_qa_entries(),
            session=db_session,
        )
        assert isinstance(result, list)
        assert len(result) == 2
        prompt = mock_gemini.call_args[0][0]
        assert "--- Customer Brief ---" not in prompt

    @patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-key"})
    @patch("pipeline.layers.brief_generator._call_gemini")
    def test_all_null_fields_no_section(self, mock_gemini, db_session):
        from pipeline.layers.brief_generator import generate_brief

        mock_gemini.return_value = FAKE_BRIEF_JSON
        cb = CustomerBrief(project_id=SAMPLE_PROJECT_ID)
        db_session.add(cb)
        db_session.commit()

        generate_brief(
            SAMPLE_PROJECT_ID,
            _make_listing(),
            _make_clusters(),
            _make_qa_entries(),
            session=db_session,
        )

        prompt = mock_gemini.call_args[0][0]
        assert "--- Customer Brief ---" not in prompt
