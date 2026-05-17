"""Antivenom experiment runner.

Reads a PGN-with-wildcards spec, exhaustively enumerates every legal move at
each wildcard ply (no heuristics, no pruning beyond illegal-move skips),
evaluates every leaf position with Stockfish, and writes two files into
``config_output_dir``: ``results.json`` (full ranked data) and
``report.html`` (self-contained human-readable report).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `src` importable when running this file directly (e.g. `python experiments/E1.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from src.v0.antivenom import run_antivenom
from src.v0.report import json_to_html


# CONFIGURATION
config_experiment_tag: str = "E1_silly_knight"
config_input_path: Path = Path.cwd() / "inputs" / "format_0" / "silly_knight_moves.pgn"
config_output_dir: Path = Path.cwd() / "outputs" / config_experiment_tag

# Solutions: the JSON file always contains every enumerated leaf, sorted from
# the wildcard player's best to worst. config_num_solutions controls how many
# top entries get printed to the console as a quick-look summary, AND how many
# of the top solutions get inline board diagrams in the HTML report.
config_num_solutions: int = 5

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

config_output_dir.mkdir(parents=True, exist_ok=True)
results_json_path: Path = config_output_dir / "results.json"
report_html_path: Path = config_output_dir / "report.html"

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

results_json_path.write_text(json.dumps(output_dict, indent=4))
logger.info(
    f"Wrote {len(result.results)} ranked results to file://{results_json_path}"
)

report_html: str = json_to_html(data=output_dict, top_n_with_boards=config_num_solutions)
report_html_path.write_text(report_html)
logger.info(f"Wrote HTML report to file://{report_html_path}")

logger.info(
    f"Top {config_num_solutions} for wildcard player ({result.wildcard_player}):"
)
for i, r in enumerate(result.results[:config_num_solutions]):
    line_str: str = " ".join(r.line)
    logger.info(f"  #{i + 1}: {line_str}   →   {r.evaluation_str}")
