from pathlib import Path
from loguru import logger


# CONFIGURATION
config_experiment_tag: str = "E2_fool"
config_input_path: Path = Path.cwd() / "inputs" / "format_0" / "fool.pgn"
config_output_path: Path = Path.cwd() / "outputs" / "E1" / "fool.json"
config_num_solutions: int = 3
config_engine_depth: int | None = 20


# -----------------------------------------------------------------------
# Everything below this line should be automatic
# -----------------------------------------------------------------------

# I/O PRELIMINARIES

if not config_input_path.exists():
    raise FileNotFoundError(f"Input file does not exist: {config_input_path}")
logger.info(f"Reading from {config_input_path}")

config_output_path.parent.mkdir(parents=True, exist_ok=True)
logger.info(f"Writing to file://{config_output_path}")


