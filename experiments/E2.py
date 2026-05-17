"""Antivenom experiment runner.

Reads a PGN-with-wildcards spec, exhaustively enumerates every legal move at
each wildcard ply (no heuristics, no pruning beyond illegal-move skips),
evaluates every leaf position with Stockfish, and writes a ranked JSON file
of all solutions plus a top-N preview to the console.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `src` importable when running this file directly (e.g. `python experiments/E1.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from src.v0.antivenom import run_antivenom


# CONFIGURATION
config_experiment_tag: str = "E2_fool"
config_input_path: Path = Path.cwd() / "inputs" / "format_0" / "fool.pgn"
config_output_path: Path = Path.cwd() / "outputs" / config_experiment_tag / "fool.json"

# Solutions: the JSON file always contains every enumerated leaf, sorted from
# the wildcard player's best to worst. config_num_solutions controls how many
# top entries get printed to the console as a quick-look summary.
config_num_solutions: int = 3

# Stockfish settings (all exposed here per project convention).
config_engine_depth: int = 20
config_engine_threads: int = 1
config_engine_hash_mb: int = 256
config_engine_path: str | None = None  # None = auto-detect via PATH / common locations.

# Parser settings.
config_wildcard_symbol: str = "__"

# Logging verbosity (0=silent, 1=info).
config_verbosity: int = 1

# -----------------------------------------------------------------------
# Everything below this line should be automatic
# -----------------------------------------------------------------------

if not config_input_path.exists():
    raise FileNotFoundError(f"Input file does not exist: {config_input_path}")
logger.info(f"Reading from file://{config_input_path}")
spec: str = config_input_path.read_text().strip()
logger.info(f"Spec: {spec!r}")

config_output_path.parent.mkdir(parents=True, exist_ok=True)

result = run_antivenom(
    spec=spec,
    stockfish_depth=config_engine_depth,
    stockfish_threads=config_engine_threads,
    stockfish_hash_mb=config_engine_hash_mb,
    wildcard_symbol=config_wildcard_symbol,
    stockfish_path=config_engine_path,
    verbosity=config_verbosity,
)

output_dict: dict = result.to_json_dict()
output_dict["meta"]["experiment_tag"] = config_experiment_tag
output_dict["meta"]["input_path"] = str(config_input_path)

config_output_path.write_text(json.dumps(output_dict, indent=4))
logger.info(
    f"Wrote {len(result.results)} ranked results to file://{config_output_path}"
)

logger.info(
    f"Top {config_num_solutions} for wildcard player ({result.wildcard_player}):"
)
for i, r in enumerate(result.results[:config_num_solutions]):
    line_str: str = " ".join(r.line)
    logger.info(f"  #{i + 1}: {line_str}   →   {r.evaluation_str}")
