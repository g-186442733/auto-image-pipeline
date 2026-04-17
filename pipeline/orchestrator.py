"""Pipeline orchestrator — runs the full pipeline end-to-end."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.config import config
from pipeline.models.base import get_session, create_all
from pipeline.models.project import Project
from pipeline.layers.input_layer import create_project
from pipeline.layers.amazon_data import fetch_asin_detail, fetch_category_top
from pipeline.layers.vision_analyzer import analyze_competitor_listing
from pipeline.layers.slot_planner import generate_slot_plan
from pipeline.layers.prompt_engine import generate_slot_prompts
from pipeline.layers.qa_gate import run_qa_checks
from pipeline.layers.feedback_loop import export_project_report
from pipeline.adapters.registry import get_adapter
from pipeline.utils.logger import setup_logger

logger = setup_logger("aip.orchestrator")


def _update_status(project_id: int, status: str) -> None:
    """Update project status in DB."""
    session = get_session()
    try:
        proj = session.query(Project).get(project_id)
        if proj:
            proj.status = status
            session.commit()
    finally:
        session.close()


def step_init(brief_path: str) -> Project:
    """Load brief JSON and create project. Sets status='initialized'."""
    path = Path(brief_path)
    if not path.exists():
        raise FileNotFoundError(f"Brief file not found: {brief_path}")
    brief = json.loads(path.read_text(encoding="utf-8"))
    create_all()
    project = create_project(brief)
    _update_status(project.id, "initialized")
    logger.info("Project %d created: %s", project.id, project.name)
    return project


def step_analyze(project_id: int) -> dict:
    """Fetch Amazon data and analyze competitors. Sets status='analyzed'."""
    if not config.keepa_api_key:
        raise RuntimeError("E_CONFIG_001: KEEPA_API_KEY not set")
    if not config.openai_api_key:
        raise RuntimeError("E_CONFIG_002: OPENAI_API_KEY not set")

    session = get_session()
    try:
        proj = session.query(Project).get(project_id)
        if not proj:
            raise ValueError(f"Project {project_id} not found")

        asin_detail = fetch_asin_detail(proj.asin)
        category_top = fetch_category_top(proj.category)
        competitor_analysis = analyze_competitor_listing(proj.asin)
    finally:
        session.close()

    _update_status(project_id, "analyzed")
    logger.info("Analysis complete for project %d", project_id)
    return {
        "asin_detail": asin_detail,
        "category_top": category_top,
        "competitor_analysis": competitor_analysis,
    }


def step_plan(project_id: int) -> list:
    """Generate slot plan. Sets status='planned'."""
    slots = generate_slot_plan(project_id)
    _update_status(project_id, "planned")
    logger.info("Slot plan generated for project %d: %d slots", project_id, len(slots))
    return slots


def step_generate(project_id: int, adapter_name: str = "mock") -> dict[str, str]:
    """Generate prompts and run image adapter. Sets status='generated'."""
    prompts = generate_slot_prompts(project_id)
    adapter = get_adapter(adapter_name)

    results = {}
    for slot_label, prompt_text in prompts.items():
        result = adapter.generate(prompt_text)
        results[slot_label] = result
        logger.info("Generated image for %s via %s", slot_label, adapter_name)

    _update_status(project_id, "generated")
    return results


def step_qa(project_id: int) -> list:
    """Run QA checks on generated images. Sets status='qa_passed' or 'qa_failed'."""
    session = get_session()
    try:
        from pipeline.models.slot_plan import SlotPlan

        slots = session.query(SlotPlan).filter(SlotPlan.project_id == project_id).all()
        slot_ids = [s.id for s in slots]
    finally:
        session.close()

    all_records = []
    all_passed = True
    for slot_id in slot_ids:
        records = run_qa_checks(slot_id)
        all_records.extend(records)
        for r in records:
            if not r.passed:
                all_passed = False

    status = "qa_passed" if all_passed else "qa_failed"
    _update_status(project_id, status)
    logger.info("QA %s for project %d", status, project_id)
    return all_records


def step_report(project_id: int) -> dict:
    """Export project report. Sets status='completed'."""
    report = export_project_report(project_id)
    _update_status(project_id, "completed")
    logger.info("Report exported for project %d", project_id)
    return report


def run_full_pipeline(brief_path: str, adapter_name: str = "mock") -> dict:
    """Run all pipeline steps end-to-end.

    Returns dict with keys: project_id, status, report.
    On failure, sets project status to 'failed' and re-raises.
    """
    project = step_init(brief_path)
    project_id = project.id

    try:
        step_analyze(project_id)
        step_plan(project_id)
        step_generate(project_id, adapter_name)
        step_qa(project_id)
        report = step_report(project_id)
        return {
            "project_id": project_id,
            "status": "completed",
            "report": report,
        }
    except Exception:
        _update_status(project_id, "failed")
        raise
