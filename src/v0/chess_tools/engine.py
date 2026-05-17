"""Persistent Stockfish engine for batch position evaluation.

The standalone helpers in ``evaluation.py`` spin up a Stockfish process per call,
which dominates runtime for trees of more than a handful of leaves. This wrapper
opens one Stockfish process, queries it N times via ``evaluate()``, then closes
it on context exit.

Terminal positions (checkmate, stalemate, insufficient material, etc.) are
detected via python-chess and short-circuited without an engine call —
``chess.engine.analyse`` behavior on already-finished positions is engine-specific
and not worth depending on.
"""

from __future__ import annotations

import chess
import chess.engine
from loguru import logger

from .evaluation import EvaluationResult, _parse_single_result, find_stockfish


def _terminal_status(*, board: chess.Board) -> str | None:
    """Classify a finished position. Returns None if the game is not over.

    Categories:
      - 'white_wins' / 'black_wins': checkmate (side that just moved delivered mate).
      - 'draw_stalemate': side to move has no legal moves but is not in check.
      - 'draw_insufficient_material': neither side has enough material to mate.
      - 'draw_seventyfive_moves': 75-move rule (forced draw, no claim needed).
      - 'draw_fivefold_repetition': fivefold repetition (forced draw, no claim needed).
      - 'draw_other': covers any future is_game_over() draw the above don't catch.
    """
    if not board.is_game_over():
        return None
    if board.is_checkmate():
        # The side to move is mated → the *other* side delivered mate.
        return "black_wins" if board.turn == chess.WHITE else "white_wins"
    if board.is_stalemate():
        return "draw_stalemate"
    if board.is_insufficient_material():
        return "draw_insufficient_material"
    if board.is_seventyfive_moves():
        return "draw_seventyfive_moves"
    if board.is_fivefold_repetition():
        return "draw_fivefold_repetition"
    return "draw_other"


def _synthesize_terminal_result(*, board: chess.Board, terminal: str) -> EvaluationResult:
    """Build an EvaluationResult for a position that's already game-over.

    No engine call needed; PV is empty and depth is 0.
    """
    return EvaluationResult(
        centipawns=None,
        mate_in=None,
        best_move="",
        best_move_uci="",
        principal_variation=(),
        depth=0,
        terminal=terminal,
    )


class StockfishEngine:
    """Context-managed wrapper around a single persistent Stockfish process.

    Usage:
        with StockfishEngine(depth=20, threads=1, hash_mb=256) as engine:
            for fen in fens:
                result = engine.evaluate(fen=fen)

    All Stockfish configuration is set at open time. Terminal positions are
    short-circuited (no engine round-trip).
    """

    def __init__(
        self,
        *,
        depth: int,
        threads: int,
        hash_mb: int,
        stockfish_path: str | None = None,
    ) -> None:
        self.depth: int = depth
        self.threads: int = threads
        self.hash_mb: int = hash_mb
        self._configured_stockfish_path: str | None = stockfish_path
        self._engine: chess.engine.SimpleEngine | None = None
        self._resolved_path: str | None = None

    def __enter__(self) -> "StockfishEngine":
        path: str | None = self._configured_stockfish_path or find_stockfish()
        if path is None:
            raise FileNotFoundError(
                "Stockfish not found. Install it (e.g. `sudo apt install stockfish` "
                "on Debian/Ubuntu) or pass stockfish_path explicitly."
            )
        self._resolved_path = path
        self._engine = chess.engine.SimpleEngine.popen_uci(path)
        self._engine.configure({"Threads": self.threads, "Hash": self.hash_mb})
        logger.info(
            f"Stockfish engine opened (path={path}, depth={self.depth}, "
            f"threads={self.threads}, hash_mb={self.hash_mb})"
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._engine is not None:
            self._engine.quit()
            self._engine = None
            logger.info("Stockfish engine closed")

    def evaluate(self, *, fen: str) -> EvaluationResult:
        """Evaluate a single position. Must be called inside the context manager."""
        if self._engine is None:
            raise RuntimeError(
                "StockfishEngine must be used as a context manager "
                "(with StockfishEngine(...) as engine: ...)"
            )

        board: chess.Board = chess.Board(fen)

        terminal: str | None = _terminal_status(board=board)
        if terminal is not None:
            return _synthesize_terminal_result(board=board, terminal=terminal)

        info: chess.engine.InfoDict = self._engine.analyse(
            board, chess.engine.Limit(depth=self.depth)
        )
        return _parse_single_result(board, info)

    @property
    def resolved_stockfish_path(self) -> str | None:
        """The actual Stockfish path in use (resolved at __enter__)."""
        return self._resolved_path
