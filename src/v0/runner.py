"""Generic experiment runner.

Per-experiment scripts construct an ``ExperimentConfig`` at the top of the file
and call ``run_experiment(config=config)``. The runner handles input loading,
output directory setup, JSON + HTML writing, and the top-N console summary, so
each experiment file collapses to a config block plus one call.

All knobs live on ``ExperimentConfig`` — no hidden defaults inside this module.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, ConfigDict

from .antivenom import AntivenomResult, run_antivenom
from .report import json_to_html


class ExperimentConfig(BaseModel):
    """All settings for one antivenom experiment run.

    Constructed explicitly at the top of each experiment script; passed once
    to ``run_experiment``. Frozen so accidental mutation mid-run is caught.
    """

    model_config = ConfigDict(frozen=True)

    experiment_tag: str
    input_path: Path
    output_dir: Path

    num_solutions: int
    """Top-N printed to console AND inlined as boards in the HTML report."""

    engine_depth: int
    engine_threads: int
    engine_hash_mb: int
    engine_path: str | None
    """None = auto-detect Stockfish via PATH / common install locations."""

    wildcard_symbol: str
    verbosity: int


def run_experiment(*, config: ExperimentConfig) -> AntivenomResult:
    """Run one antivenom experiment end-to-end.

    Reads the spec from ``config.input_path``, runs the antivenom pipeline,
    writes ``results.json`` and ``report.html`` into ``config.output_dir``, and
    logs a top-N summary. Returns the ``AntivenomResult`` for further inspection
    in the calling script (e.g. interactive use in an IDE).
    """
    if not config.input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {config.input_path}")
    logger.info(f"Reading from file://{config.input_path}")
    spec: str = config.input_path.read_text().strip()
    logger.info(f"Spec: {spec!r}")

    config.output_dir.mkdir(parents=True, exist_ok=True)
    results_json_path: Path = config.output_dir / "results.json"
    report_html_path: Path = config.output_dir / "report.html"

    result: AntivenomResult = run_antivenom(
        spec=spec,
        stockfish_depth=config.engine_depth,
        stockfish_threads=config.engine_threads,
        stockfish_hash_mb=config.engine_hash_mb,
        wildcard_symbol=config.wildcard_symbol,
        stockfish_path=config.engine_path,
        verbosity=config.verbosity,
    )

    output_dict: dict = result.to_json_dict()
    output_dict["meta"]["experiment_tag"] = config.experiment_tag
    output_dict["meta"]["input_path"] = str(config.input_path)

    results_json_path.write_text(json.dumps(output_dict, indent=4))
    logger.info(
        f"Wrote {len(result.results)} ranked primaries to file://{results_json_path}"
    )

    report_html: str = json_to_html(
        data=output_dict, top_n_with_boards=config.num_solutions
    )
    report_html_path.write_text(report_html)
    logger.info(f"Wrote HTML report to file://{report_html_path}")

    logger.info(
        f"Top {config.num_solutions} for wildcard player ({result.wildcard_player}):"
    )
    for i, r in enumerate(result.results[: config.num_solutions]):
        line_str: str = " ".join(r.line)
        n_trans: int = len(r.transpositions)
        trans_note: str = (
            f" (+{n_trans} transposition{'s' if n_trans != 1 else ''})"
            if n_trans
            else ""
        )
        logger.info(f"  #{i + 1}: {line_str}   →   {r.evaluation_str}{trans_note}")

    return result
