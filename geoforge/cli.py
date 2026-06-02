"""
cli.py — GeoForge command-line interface.

Commands:
  geoforge run config.yaml          Run the pipeline
  geoforge run config.yaml -v       Verbose / debug output
  geoforge generate-example         Create a sample project with synthetic data
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from . import __version__


def _setup_logging(verbose: bool):
    level  = logging.DEBUG if verbose else logging.INFO
    fmt    = "%(asctime)s [%(levelname)s] %(message)s" if verbose else "[%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S",
                        handlers=[logging.StreamHandler(sys.stdout)])


@click.group()
@click.version_option(__version__, prog_name="geoforge")
def cli():
    """GeoForge — Convert 2D map layers + LiDAR into 3D city models."""


# ── run ───────────────────────────────────────────────────────────────────────
@cli.command()
@click.argument("config", type=click.Path(exists=True, dir_okay=False))
@click.option("--verbose", "-v",   is_flag=True, help="Show debug output")
@click.option("--output",  "-o",   default=None, help="Override output directory")
@click.option("--formats", "-f",   multiple=True,
              type=click.Choice(["obj","cityjson","citygml","stl","postgis","csv"],
                                case_sensitive=False),
              help="Override output formats from config")
def run(config, verbose, output, formats):
    """Run the GeoForge pipeline from CONFIG (a YAML file)."""
    _setup_logging(verbose)
    from .config import load_config
    from .pipeline import run as _run

    cfg = load_config(config)
    if formats:
        cfg.output_formats = list(formats)
    if output:
        cfg.output_dir = output

    click.echo(f"\nGeoForge v{__version__}")
    click.echo(f"  Config   : {config}")
    click.echo(f"  Cloud    : {cfg.pointcloud}")
    click.echo(f"  Layers   : {len(cfg.layers)}")
    click.echo(f"  Formats  : {', '.join(cfg.output_formats)}")
    click.echo(f"  Output   : {cfg.output_dir}\n")

    try:
        features = _run(cfg)
        click.secho(f"\n✓  {len(features)} 3D features built successfully", fg="green")
    except Exception as e:
        click.secho(f"\n✗  Pipeline failed: {e}", fg="red", err=True)
        if verbose:
            import traceback; traceback.print_exc()
        sys.exit(1)


# ── generate-example ──────────────────────────────────────────────────────────
@cli.command("generate-example")
@click.option("--output", "-o", default="example_project", show_default=True,
              help="Directory to write example files into")
def generate_example(output):
    """Create a ready-to-run example project with synthetic data."""
    _setup_logging(False)
    from .example_gen import generate
    out = Path(output)
    generate(out)
    click.secho(f"\n✓  Example project created: {out.resolve()}", fg="green")
    click.echo(f"\nRun it with:")
    click.echo(f"  geoforge run {out / 'config.yaml'}")


def main():
    cli()


if __name__ == "__main__":
    main()
