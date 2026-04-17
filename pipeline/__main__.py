"""CLI entry point for auto-image-pipeline."""

import click


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Auto Image Pipeline — Amazon product image automation."""
    pass


@cli.command()
def info():
    """Show pipeline info."""
    click.echo("auto-image-pipeline v0.1.0")


if __name__ == "__main__":
    cli()
