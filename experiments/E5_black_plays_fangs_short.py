"""Antivenom experiment — 4-ply variant of E3 (black plays fangs).

Functionally identical to E4 but uses the unified ``ExperimentConfig`` runner
instead of the inline boilerplate. Different output tag so the two runs sit
side-by-side for comparison.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `src` importable when running this file directly (e.g. `python experiments/E5_*.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.v0.runner import ExperimentConfig, run_experiment


_REPO: Path = Path(__file__).resolve().parent.parent

config: ExperimentConfig = ExperimentConfig(
    experiment_tag="E5_black_plays_fangs_short",
    input_path=_REPO / "inputs" / "format_0" / "black_plays_fangs_4_ply.pgn",
    output_dir=_REPO / "outputs" / "E5_black_plays_fangs_short",
    num_solutions=20,
    engine_depth=20,
    engine_threads=4,
    engine_hash_mb=256,
    engine_path=None,
    wildcard_symbol="__",
    verbosity=1,
)

run_experiment(config=config)
