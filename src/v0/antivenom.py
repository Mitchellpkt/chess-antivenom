"""Top-level antivenom pipeline.

Given a PGN-with-wildcards spec where one side ("system player") commits to a
fixed move sequence and the other side ("wildcard player") branches into every
legal move at each of their plies, exhaustively enumerate the resulting tree,
evaluate every leaf position with Stockfish, and return the leaves ranked from
the wildcard player's perspective (best result first).

The selection criterion is "single best leaf, opponent fully deterministic" —
no minimax, no heuristic pruning. Every legal wildcard choice is enumerated.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from tqdm.auto import tqdm

from .chess_tools.engine import StockfishEngine
from .chess_tools.evaluation import EvaluationResult
from .utils.parser import parse_game_string_simple
from .utils.tree import expand_wildcards


def _detect_wildcard_player(*, moves: list[str | None]) -> str:
    """Determine which side's plies are all wildcards.

    Convention: ply index 0 is white, index 1 is black, alternating. The
    "wildcard player" is whichever side has every one of their plies set to
    None in the parsed move list. If neither side fits or both do, raise.
    """
    white_plies: list[str | None] = moves[0::2]
    black_plies: list[str | None] = moves[1::2]

    white_all_wild: bool = len(white_plies) > 0 and all(m is None for m in white_plies)
    black_all_wild: bool = len(black_plies) > 0 and all(m is None for m in black_plies)
    white_any_concrete: bool = any(m is not None for m in white_plies)
    black_any_concrete: bool = any(m is not None for m in black_plies)

    if white_all_wild and not black_any_concrete:
        raise ValueError(
            "Spec has only wildcards (no system player). Cannot determine wildcard player."
        )
    if white_all_wild and black_any_concrete and not white_any_concrete:
        return "white"
    if black_all_wild and white_any_concrete and not black_any_concrete:
        return "black"
    raise ValueError(
        f"Spec is malformed: one side must be all wildcards and the other all "
        f"concrete moves. Got white_plies={white_plies}, black_plies={black_plies}."
    )


def _compute_sort_key(
    *,
    terminal: str | None,
    mate_in: int | None,
    centipawns: int | None,
    line_length: int,
    wildcard_player: str,
) -> tuple[int, int]:
    """Build a (category, secondary) sort key.

    Sorted descending, higher tuple = better outcome for the wildcard player.

    Categories (most-preferred to least):
        +4 — wildcard player just delivered checkmate (terminal). Tie-break: shorter line wins.
        +3 — engine sees forced mate by wildcard player. Tie-break: smaller mate distance wins.
        +1 — normal centipawn eval. Tie-break: higher cp from WP's perspective wins.
         0 — draw (terminal). No tie-break.
        -3 — engine sees forced mate against wildcard player. Tie-break: larger mate distance is less bad.
        -4 — wildcard player just got checkmated (terminal). Tie-break: longer line is less bad.
    """
    wp_is_white: bool = wildcard_player == "white"

    if terminal is not None:
        if terminal == "white_wins":
            if wp_is_white:
                return (4, -line_length)
            return (-4, line_length)
        if terminal == "black_wins":
            if not wp_is_white:
                return (4, -line_length)
            return (-4, line_length)
        # All draw_* cases.
        return (0, 0)

    if mate_in is not None:
        # Engine convention: positive = white delivers mate in N plies.
        if mate_in > 0:
            return (3, -mate_in) if wp_is_white else (-3, mate_in)
        n: int = -mate_in
        return (3, -n) if not wp_is_white else (-3, n)

    cp: int = centipawns if centipawns is not None else 0
    wp_cp: int = cp if wp_is_white else -cp
    return (1, wp_cp)


class LeafResult(BaseModel):
    """Evaluation of one enumerated leaf line."""

    model_config = ConfigDict(frozen=True)

    line: tuple[str, ...]
    """SAN moves from the starting position to this leaf."""

    fen: str
    """FEN of the leaf position."""

    centipawns: int | None
    """Engine eval in centipawns (white POV). None for terminal or mate."""

    mate_in: int | None
    """Engine-detected forced mate in plies (positive=white mates). None otherwise."""

    terminal: str | None
    """If the leaf position is already game-over, the kind of ending."""

    best_move: str
    """Engine's best continuation from the leaf (SAN). Empty for terminal."""

    principal_variation: tuple[str, ...]
    """Engine PV from the leaf (SAN). Empty for terminal."""

    wildcard_player_centipawns: int | None
    """Centipawns from the wildcard player's perspective. None for terminal or mate."""

    sort_category: int
    """Bucket used for ranking — see _compute_sort_key."""

    sort_secondary: int
    """Tie-break within bucket — see _compute_sort_key."""

    @property
    def evaluation_str(self) -> str:
        if self.terminal is not None:
            return self.terminal
        if self.mate_in is not None:
            return f"M{self.mate_in:+d}"
        if self.centipawns is not None:
            return f"{self.centipawns / 100:+.2f}"
        return "?"


class AntivenomResult(BaseModel):
    """Full result of an antivenom run."""

    model_config = ConfigDict(frozen=True)

    spec: str
    wildcard_player: str
    wildcard_symbol: str
    stockfish_depth: int
    stockfish_threads: int
    stockfish_hash_mb: int
    stockfish_path: str
    total_leaves: int
    evaluated_at_unix: float
    elapsed_seconds: float
    results: tuple[LeafResult, ...] = Field(default_factory=tuple)

    def to_json_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dict matching the agreed schema."""
        return {
            "meta": {
                "spec": self.spec,
                "wildcard_player": self.wildcard_player,
                "wildcard_symbol": self.wildcard_symbol,
                "stockfish": {
                    "path": self.stockfish_path,
                    "depth": self.stockfish_depth,
                    "threads": self.stockfish_threads,
                    "hash_mb": self.stockfish_hash_mb,
                },
                "total_leaves": self.total_leaves,
                "evaluated_at_unix": self.evaluated_at_unix,
                "elapsed_seconds": self.elapsed_seconds,
            },
            "results": [
                {
                    "rank": i + 1,
                    "line": list(r.line),
                    "fen": r.fen,
                    "centipawns": r.centipawns,
                    "mate_in": r.mate_in,
                    "terminal": r.terminal,
                    "wildcard_player_centipawns": r.wildcard_player_centipawns,
                    "evaluation_str": r.evaluation_str,
                    "best_move": r.best_move,
                    "principal_variation": list(r.principal_variation),
                }
                for i, r in enumerate(self.results)
            ],
        }


def run_antivenom(
    *,
    spec: str,
    stockfish_depth: int,
    stockfish_threads: int,
    stockfish_hash_mb: int,
    wildcard_symbol: str,
    stockfish_path: str | None,
    verbosity: int = 1,
) -> AntivenomResult:
    """Run the full antivenom pipeline on a PGN-with-wildcards spec.

    Pipeline: parse → detect wildcard player → expand wildcards exhaustively →
    evaluate every leaf with a single persistent Stockfish process → sort
    descending from the wildcard player's perspective.

    Args:
        spec: PGN with wildcards (e.g. ``"1. Nf3 __ 2. Ne5 __"``).
        stockfish_depth: Engine search depth at each leaf.
        stockfish_threads: Engine thread count.
        stockfish_hash_mb: Engine hash size in MB.
        wildcard_symbol: The token treated as "any legal move".
        stockfish_path: Explicit Stockfish binary path. ``None`` = auto-detect.
        verbosity: 0=silent, 1=info-level progress (default).

    Returns:
        AntivenomResult with ranked leaf evaluations.
    """
    started_at: float = time.time()

    moves: list[str | None] = parse_game_string_simple(
        s=spec, wildcard_symbol=wildcard_symbol
    )
    wildcard_player: str = _detect_wildcard_player(moves=moves)
    if verbosity >= 1:
        logger.info(f"Spec: {spec!r}, wildcard player: {wildcard_player}")

    tree = expand_wildcards(spec, wildcard_symbol=wildcard_symbol)
    leaves: list[tuple[tuple[str, ...], str]] = list(tree.iter_leaves())
    total_leaves: int = len(leaves)
    if verbosity >= 1:
        logger.info(f"Expanded tree: {total_leaves} leaves to evaluate")

    leaf_results: list[LeafResult] = []
    with StockfishEngine(
        depth=stockfish_depth,
        threads=stockfish_threads,
        hash_mb=stockfish_hash_mb,
        stockfish_path=stockfish_path,
    ) as engine:
        resolved_path: str = engine.resolved_stockfish_path or ""
        for line, fen in tqdm(leaves, desc="Evaluating leaves", mininterval=1):
            eval_result: EvaluationResult = engine.evaluate(fen=fen)

            wp_cp: int | None = None
            if (
                eval_result.terminal is None
                and eval_result.mate_in is None
                and eval_result.centipawns is not None
            ):
                wp_cp = (
                    eval_result.centipawns
                    if wildcard_player == "white"
                    else -eval_result.centipawns
                )

            sort_cat, sort_sec = _compute_sort_key(
                terminal=eval_result.terminal,
                mate_in=eval_result.mate_in,
                centipawns=eval_result.centipawns,
                line_length=len(line),
                wildcard_player=wildcard_player,
            )

            leaf_results.append(
                LeafResult(
                    line=line,
                    fen=fen,
                    centipawns=eval_result.centipawns,
                    mate_in=eval_result.mate_in,
                    terminal=eval_result.terminal,
                    best_move=eval_result.best_move,
                    principal_variation=eval_result.principal_variation,
                    wildcard_player_centipawns=wp_cp,
                    sort_category=sort_cat,
                    sort_secondary=sort_sec,
                )
            )

    leaf_results.sort(key=lambda r: (r.sort_category, r.sort_secondary), reverse=True)

    elapsed: float = time.time() - started_at
    if verbosity >= 1:
        logger.info(f"Evaluated {total_leaves} leaves in {elapsed:.1f}s")

    return AntivenomResult(
        spec=spec,
        wildcard_player=wildcard_player,
        wildcard_symbol=wildcard_symbol,
        stockfish_depth=stockfish_depth,
        stockfish_threads=stockfish_threads,
        stockfish_hash_mb=stockfish_hash_mb,
        stockfish_path=resolved_path,
        total_leaves=total_leaves,
        evaluated_at_unix=started_at,
        elapsed_seconds=elapsed,
        results=tuple(leaf_results),
    )
