"""CLI entry point for auto-image-pipeline."""

from __future__ import annotations

import sys

import click
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from pipeline.models.base import get_session, get_engine
from pipeline.layers.brief_generator import generate_brief
from pipeline.layers.delivery import build_delivery_package
from pipeline.layers.feedback_loop import export_conclusions
from pipeline.layers.prompt_engine import build_prompt
from pipeline.models.competitor_listing import CompetitorListing
from pipeline.models.qa_entry import QAEntry
from pipeline.models.review_cluster import ReviewCluster
from pipeline.orchestrator import (
    run_full_pipeline,
    step_analyze,
    step_aplus,
    step_generate,
    step_init,
    step_plan,
    step_qa,
    step_report,
)


def _migrate_schema() -> None:
    engine = get_engine()
    alters = [
        "ALTER TABLE aplus_contents ADD COLUMN layout TEXT",
        "ALTER TABLE tag_assignments ADD COLUMN tag_layer TEXT NOT NULL DEFAULT 'intent'",
    ]
    with engine.connect() as conn:
        for stmt in alters:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except OperationalError:
                pass


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Auto Image Pipeline — Amazon product image automation."""


@cli.command()
@click.argument("brief", type=click.Path(exists=True))
def init(brief: str):
    """Create project from a brief JSON file."""
    try:
        project = step_init(brief)
        _migrate_schema()
        click.echo(f"Project created: id={project.id} name={project.name}")
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("project_id", type=int)
def analyze(project_id: int):
    """Fetch Amazon data and analyze competitors."""
    try:
        result = step_analyze(project_id)
        click.echo(
            f"Analysis complete: {len(result.get('competitor_analysis', []))} competitors analyzed"
        )
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("project_id", type=int)
def plan(project_id: int):
    """Generate slot plan for a project."""
    try:
        slots = step_plan(project_id)
        click.echo(f"Slot plan generated: {len(slots)} slots")
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("project_id", type=int)
@click.option("--adapter", default="mock", help="Image generation adapter name.")
def generate(project_id: int, adapter: str):
    """Generate images for each slot."""
    try:
        results = step_generate(project_id, adapter)
        click.echo(f"Generated {len(results)} images via '{adapter}'")
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("project_id", type=int)
def aplus(project_id: int):
    """Generate A+ content storyboard."""
    try:
        modules = step_aplus(project_id)
        click.echo(f"A+ storyboard generated: {len(modules)} modules")
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("project_id", type=int)
def qa(project_id: int):
    """Run QA checks on generated images."""
    try:
        records = step_qa(project_id)
        passed = sum(1 for r in records if r.passed)
        click.echo(f"QA complete: {passed}/{len(records)} checks passed")
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("project_id", type=int)
def report(project_id: int):
    """Export project report."""
    try:
        result = step_report(project_id)
        click.echo(f"Report exported: {result.get('project_name', 'unknown')}")
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("brief", type=click.Path(exists=True))
@click.option("--adapter", default="mock", help="Image generation adapter name.")
def run(brief: str, adapter: str):
    """Run the full pipeline: init → analyze → plan → generate → qa → report."""
    try:
        result = run_full_pipeline(brief, adapter)
        click.echo(
            f"Pipeline complete: project_id={result['project_id']} status={result['status']}"
        )
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("project_id", type=int)
def brief(project_id: int):
    """Generate an image brief from competitor data."""
    try:
        session = get_session()
        comps = (
            session.query(CompetitorListing)
            .filter(CompetitorListing.project_id == project_id)
            .all()
        )
        clusters = (
            session.query(ReviewCluster)
            .filter(ReviewCluster.project_id == project_id)
            .all()
        )
        qa_entries = (
            session.query(QAEntry).filter(QAEntry.project_id == project_id).all()
        )
        if not comps:
            click.echo("No competitor data found; run 'analyze' first.")
            return
        result = generate_brief(
            project_id, comps[0], clusters, qa_entries, session=session
        )
        click.echo(f"Brief generated: id={result.id} slot_index={result.slot_index}")
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("project_id", type=int)
@click.option("--slot-index", default=0, type=int, help="Slot index for the prompt.")
def prompt(project_id: int, slot_index: int):
    """Build a generation prompt for a slot."""
    try:
        result = build_prompt(project_id, slot_index)
        click.echo(f"Prompt built ({len(result)} chars)")
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("project_id", type=int)
def deliver(project_id: int):
    """Package deliverables for a project."""
    try:
        path = build_delivery_package(project_id)
        click.echo(f"Delivery package: {path}")
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("project_id", type=int)
def feedback(project_id: int):
    """Export feedback conclusions."""
    try:
        result = export_conclusions(project_id)
        click.echo(f"Feedback exported: {len(result)} entries")
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
