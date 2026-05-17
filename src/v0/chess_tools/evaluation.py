"""Stockfish engine evaluation for chess positions."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import chess
import chess.engine

if TYPE_CHECKING:
    from collections.abc import Sequence

# Default Stockfish paths to search
_DEFAULT_STOCKFISH_PATHS = [
    "/usr/bin/stockfish",
    "/usr/local/bin/stockfish",
    "/opt/homebrew/bin/stockfish",
    "stockfish",  # Rely on PATH
]


@dataclass(frozen=True)
class EvaluationResult:
    """Result of a Stockfish position evaluation."""

    centipawns: int | None
    """
    Evaluation in centipawns from White's perspective.
    None if the position is a forced mate.
    """

    mate_in: int | None
    """
    Number of moves until mate (positive = White mates, negative = Black mates).
    None if no forced mate is found.
    """

    best_move: str
    """Best move in SAN notation."""

    best_move_uci: str
    """Best move in UCI notation."""

    principal_variation: tuple[str, ...]
    """Principal variation (best line) in SAN notation."""

    depth: int
    """Search depth reached."""

    terminal: str | None = None
    """
    Set when the evaluated position is already game-over (no engine call needed).
    One of: 'white_wins', 'black_wins', 'draw_stalemate', 'draw_insufficient_material',
    'draw_seventyfive_moves', 'draw_fivefold_repetition', 'draw_other'. None otherwise.
    """

    @property
    def is_mate(self) -> bool:
        """Whether the evaluation is a forced mate."""
        return self.mate_in is not None

    @property
    def is_terminal(self) -> bool:
        """Whether the position is already a finished game (checkmate, stalemate, draw)."""
        return self.terminal is not None

    @property
    def evaluation_str(self) -> str:
        """Human-readable evaluation string."""
        if self.terminal is not None:
            return self.terminal
        if self.mate_in is not None:
            return f"M{self.mate_in}"
        elif self.centipawns is not None:
            return f"{self.centipawns / 100:+.2f}"
        return "?"


@dataclass(frozen=True)
class MultiPVResult:
    """Result containing multiple principal variations."""

    lines: tuple[EvaluationResult, ...]
    """Evaluation results for each line, ordered by strength."""

    fen: str
    """FEN of the evaluated position."""


def find_stockfish() -> str | None:
    """
    Attempt to find the Stockfish binary.

    Returns:
        Path to Stockfish if found, None otherwise.
    """
    # First check if 'stockfish' is in PATH
    stockfish_in_path = shutil.which("stockfish")
    if stockfish_in_path:
        return stockfish_in_path

    # Check common installation paths
    for path in _DEFAULT_STOCKFISH_PATHS:
        if Path(path).is_file():
            return path

    return None


def evaluate_position(
    board: chess.Board,
    *,
    depth: int = 20,
    stockfish_path: str | None = None,
    threads: int = 1,
    hash_mb: int = 256,
    multipv: int = 1,
) -> EvaluationResult | MultiPVResult:
    """
    Evaluate a chess position using Stockfish.

    Args:
        board: A python-chess Board object to evaluate.
        depth: Search depth (higher = stronger but slower).
        stockfish_path: Path to Stockfish binary. If None, attempts auto-detection.
        threads: Number of CPU threads for Stockfish to use.
        hash_mb: Hash table size in megabytes.
        multipv: Number of principal variations to calculate (1 = best move only).

    Returns:
        EvaluationResult if multipv=1, MultiPVResult if multipv>1.

    Raises:
        FileNotFoundError: If Stockfish binary cannot be found.
        chess.engine.EngineError: If engine communication fails.

    Example:
        >>> import chess
        >>> board = chess.Board()
        >>> result = evaluate_position(board, depth=15)
        >>> print(f"Eval: {result.evaluation_str}, Best: {result.best_move}")
    """
    if stockfish_path is None:
        stockfish_path = find_stockfish()
        if stockfish_path is None:
            raise FileNotFoundError(
                "Stockfish not found. Install it or provide stockfish_path. "
                "Install via: apt install stockfish (Linux), "
                "brew install stockfish (macOS), "
                "or download from https://stockfishchess.org/download/"
            )

    engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)

    try:
        engine.configure({"Threads": threads, "Hash": hash_mb})

        limit = chess.engine.Limit(depth=depth)

        if multipv == 1:
            info = engine.analyse(board, limit)
            return _parse_single_result(board, info)
        else:
            infos = engine.analyse(board, limit, multipv=multipv)
            results = tuple(_parse_single_result(board, info) for info in infos)
            return MultiPVResult(lines=results, fen=board.fen())

    finally:
        engine.quit()


def evaluate_fen(
    fen: str,
    *,
    depth: int = 20,
    stockfish_path: str | None = None,
    threads: int = 1,
    hash_mb: int = 256,
    multipv: int = 1,
) -> EvaluationResult | MultiPVResult:
    """
    Evaluate a position specified by FEN string.

    Args:
        fen: FEN string representing the position.
        depth: Search depth.
        stockfish_path: Path to Stockfish binary.
        threads: Number of CPU threads.
        hash_mb: Hash table size in MB.
        multipv: Number of principal variations.

    Returns:
        EvaluationResult if multipv=1, MultiPVResult if multipv>1.

    Example:
        >>> result = evaluate_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
        >>> result.best_move
        'e5'
    """
    board = chess.Board(fen)
    return evaluate_position(
        board,
        depth=depth,
        stockfish_path=stockfish_path,
        threads=threads,
        hash_mb=hash_mb,
        multipv=multipv,
    )


def _parse_single_result(board: chess.Board, info: chess.engine.InfoDict) -> EvaluationResult:
    """Parse engine info dict into EvaluationResult."""
    score = info["score"].white()

    # Extract centipawns or mate score
    centipawns = None
    mate_in = None

    if score.is_mate():
        mate_in = score.mate()
    else:
        centipawns = score.score()

    # Extract PV
    pv = info.get("pv", [])
    best_move = pv[0] if pv else None

    # Convert PV to SAN
    pv_san = []
    temp_board = board.copy()
    for move in pv:
        pv_san.append(temp_board.san(move))
        temp_board.push(move)

    return EvaluationResult(
        centipawns=centipawns,
        mate_in=mate_in,
        best_move=pv_san[0] if pv_san else "",
        best_move_uci=best_move.uci() if best_move else "",
        principal_variation=tuple(pv_san),
        depth=info.get("depth", 0),
    )
