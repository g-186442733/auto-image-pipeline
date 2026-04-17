"""CLI entry point for auto-image-pipeline."""

from __future__ import annotations

import sys

import click

from pipeline.orchestrator import (
    run_full_pipeline,
    step_analyze,
    step_generate,
    step_init,
    step_plan,
    step_qa,
    step_report,
)


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


if __name__ == "__main__":
    cli()
