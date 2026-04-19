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


def _valid_brief(**kwargs):
    brief = {"name": "Test Product", "asin": "B012345678", "category": "electronics"}
    brief.update(kwargs)
    return brief


def test_create_project_success():
    from pipeline.layers.input_layer import create_project

    project = create_project(_valid_brief())
    assert project.id is not None
    assert project.status == "draft"
    assert project.asin == "B012345678"


def test_create_project_missing_fields():
    from pipeline.layers.input_layer import create_project

    with pytest.raises(ValueError, match="E_INPUT_001"):
        create_project({"name": "X"})


def test_create_project_invalid_asin():
    from pipeline.layers.input_layer import create_project

    with pytest.raises(ValueError, match="E_INPUT_002"):
        create_project(_valid_brief(asin="INVALID"))


def test_get_intake_checklist_returns_none_when_no_data():
    from pipeline.layers.input_layer import create_project, get_intake_checklist

    project = create_project(_valid_brief())
    assert get_intake_checklist(project.id) is None


def test_get_intake_checklist_returns_none_for_nonexistent_project():
    from pipeline.layers.input_layer import get_intake_checklist

    assert get_intake_checklist(99999) is None


def test_get_intake_checklist_returns_record_after_create_with_checklist():
    from pipeline.layers.input_layer import create_project, get_intake_checklist

    checklist_data = {
        "product_photos": "photo1.jpg, photo2.jpg",
        "brand_guide": "brand_guide.pdf",
        "competitor_asins": "B000000001,B000000002",
        "platform_requirements": "Amazon A+ content",
    }
    project = create_project(_valid_brief(), intake_checklist=checklist_data)
    result = get_intake_checklist(project.id)
    assert result is not None
    assert result.project_id == project.id
    assert result.product_photos == "photo1.jpg, photo2.jpg"
    assert result.competitor_asins == "B000000001,B000000002"


def test_create_project_without_checklist_stays_backward_compatible():
    from pipeline.layers.input_layer import create_project, get_intake_checklist

    project = create_project(_valid_brief())
    assert project.id is not None
    assert get_intake_checklist(project.id) is None


def test_create_project_with_partial_checklist():
    from pipeline.layers.input_layer import create_project, get_intake_checklist

    project = create_project(
        _valid_brief(), intake_checklist={"product_photos": "hero.png"}
    )
    result = get_intake_checklist(project.id)
    assert result is not None
    assert result.product_photos == "hero.png"
    assert result.brand_guide is None


def test_upsert_brand_profile_create():
    from pipeline.layers.input_layer import create_project, upsert_brand_profile

    project = create_project(_valid_brief())
    profile = upsert_brand_profile({"project_id": project.id, "brand_tone": "premium"})
    assert profile.id is not None
    assert profile.brand_tone == "premium"


def test_upsert_brand_profile_update():
    from pipeline.layers.input_layer import create_project, upsert_brand_profile

    project = create_project(_valid_brief())
    upsert_brand_profile({"project_id": project.id, "brand_tone": "Old"})
    updated = upsert_brand_profile({"project_id": project.id, "brand_tone": "New"})
    assert updated.brand_tone == "New"


def test_upsert_brand_profile_invalid_project():
    from pipeline.layers.input_layer import upsert_brand_profile

    with pytest.raises(ValueError, match="E_INPUT_003"):
        upsert_brand_profile({"project_id": 99999, "brand_tone": "X"})
