"""CLI entry point for auto-image-pipeline."""

from __future__ import annotations

import sys

import click
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from pipeline.models.base import Base, get_session, get_engine
import pipeline.models  # noqa: F401  — ensure all models register with Base.metadata
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
    """Idempotent schema migration: add any columns defined in models but missing from DB."""
    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                # Build column type string for SQLite
                col_type = col.type.compile(dialect=engine.dialect)
                nullable = "" if col.nullable else " NOT NULL"
                default = ""
                if col.server_default is not None:
                    default = f" DEFAULT {col.server_default.arg}"
                elif not col.nullable:
                    # SQLite requires DEFAULT for NOT NULL on ALTER TABLE ADD COLUMN
                    if "INT" in str(col_type).upper():
                        default = " DEFAULT 0"
                    elif "BOOL" in str(col_type).upper():
                        default = " DEFAULT 0"
                    else:
                        default = " DEFAULT ''"
                stmt = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}{nullable}{default}"
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except OperationalError:
                    pass  # column already exists or other benign error


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
@click.option(
    "--adapter", default="mock", help="Image generation adapter for QA retries."
)
def qa(project_id: int, adapter: str):
    """Run QA checks on generated images."""
    try:
        records = step_qa(project_id, adapter_name=adapter)
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


@cli.command()
@click.option("--port", default=5000, type=int, help="Port to run the web server on.")
@click.option("--debug", is_flag=True, default=False, help="Enable debug mode.")
def web(port: int, debug: bool):
    """Launch the web dashboard."""
    from pipeline.web.app import create_app

    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=debug)


if __name__ == "__main__":
    cli()
