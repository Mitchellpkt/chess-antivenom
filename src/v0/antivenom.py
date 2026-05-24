"""Top-level antivenom pipeline.

Given a PGN-with-wildcards spec where one side ("system player") commits to a
fixed move sequence and the other side ("wildcard player") branches into every
legal move at each of their plies, exhaustively enumerate the resulting tree,
evaluate every unique position (root + intermediates + leaves) with Stockfish,
and return the leaves ranked from the wildcard player's perspective.

Transposition handling: when two distinct wildcard-player move orders reach
the same leaf FEN, they're grouped. The "primary" of the group is the variation
with the best worst-case intermediate evaluation (max-of-worst, from the WP's
perspective); the rest are folded onto it as ``transpositions``.

The selection criterion is "single best leaf, opponent fully deterministic" —
no minimax, no heuristic pruning. Every legal wildcard choice is enumerated.
"""

from __future__ import annotations

import time
from collections import defaultdict
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


def _eval_str_from(
    *, terminal: str | None, mate_in: int | None, centipawns: int | None
) -> str:
    """Human-readable eval string: terminal label, M±N for mate, or cp/100."""
    if terminal is not None:
        return terminal
    if mate_in is not None:
        return f"M{mate_in:+d}"
    if centipawns is not None:
        return f"{centipawns / 100:+.2f}"
    return "?"


def _wp_centipawns(*, centipawns: int | None, wildcard_player: str) -> int | None:
    """Flip cp sign so positive = good for the wildcard player."""
    if centipawns is None:
        return None
    return centipawns if wildcard_player == "white" else -centipawns


class PathEval(BaseModel):
    """Evaluation of one position along a leaf's path (root → ... → leaf)."""

    model_config = ConfigDict(frozen=True)

    ply: int
    """0 = starting position; ply k = position after the k-th ply was played."""

    move: str | None
    """SAN of the move that produced this position. None for ply 0 (root)."""

    fen: str
    centipawns: int | None
    """Engine eval (white POV). None for mate or terminal."""

    mate_in: int | None
    terminal: str | None
    wildcard_player_centipawns: int | None
    """Centipawns from the wildcard player's perspective. None for mate/terminal."""

    evaluation_str: str


class Transposition(BaseModel):
    """An alternate move order that reaches the same leaf FEN as its primary.

    The leaf-level data (cp, mate_in, terminal, best_move, PV) is by
    construction identical to the primary's, so we don't repeat it here —
    only the differing path (line + per-ply evals) is stored.
    """

    model_config = ConfigDict(frozen=True)

    line: tuple[str, ...]
    path_evals: tuple[PathEval, ...]


class LeafResult(BaseModel):
    """Evaluation of one enumerated leaf line (a primary, post-dedup)."""

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

    path_evals: tuple[PathEval, ...]
    """Per-ply evaluation along the primary's path (ply 0 = root, ply N = leaf)."""

    transpositions: tuple[Transposition, ...] = Field(default_factory=tuple)
    """Alternate move orders that reach the same leaf FEN."""

    sort_category: int
    """Bucket used for ranking — see _compute_sort_key."""

    sort_secondary: int
    """Tie-break within bucket — see _compute_sort_key."""

    @property
    def evaluation_str(self) -> str:
        return _eval_str_from(
            terminal=self.terminal, mate_in=self.mate_in, centipawns=self.centipawns
        )


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
    """Total enumerated leaves BEFORE transposition deduplication."""

    unique_leaves: int
    """Distinct leaf FENs (== len(results), each is one primary)."""

    unique_positions_evaluated: int
    """Distinct FENs sent to Stockfish (root + intermediates + leaves)."""

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
                "unique_leaves": self.unique_leaves,
                "unique_positions_evaluated": self.unique_positions_evaluated,
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
                    "path_evals": [_path_eval_to_dict(pe) for pe in r.path_evals],
                    "transpositions": [
                        {
                            "line": list(t.line),
                            "path_evals": [_path_eval_to_dict(pe) for pe in t.path_evals],
                        }
                        for t in r.transpositions
                    ],
                }
                for i, r in enumerate(self.results)
            ],
        }


def _path_eval_to_dict(pe: PathEval) -> dict[str, Any]:
    return {
        "ply": pe.ply,
        "move": pe.move,
        "fen": pe.fen,
        "centipawns": pe.centipawns,
        "mate_in": pe.mate_in,
        "terminal": pe.terminal,
        "wildcard_player_centipawns": pe.wildcard_player_centipawns,
        "evaluation_str": pe.evaluation_str,
    }


def _build_path_evals(
    *,
    line: tuple[str, ...],
    path_fens: tuple[str, ...],
    eval_cache: dict[str, EvaluationResult],
    wildcard_player: str,
) -> tuple[PathEval, ...]:
    """Assemble the per-ply PathEval list for a single leaf path."""
    out: list[PathEval] = []
    # path_fens has length len(line) + 1; index 0 is root, index k is after move k.
    for ply, fen in enumerate(path_fens):
        move: str | None = None if ply == 0 else line[ply - 1]
        ev: EvaluationResult = eval_cache[fen]
        out.append(
            PathEval(
                ply=ply,
                move=move,
                fen=fen,
                centipawns=ev.centipawns,
                mate_in=ev.mate_in,
                terminal=ev.terminal,
                wildcard_player_centipawns=_wp_centipawns(
                    centipawns=ev.centipawns, wildcard_player=wildcard_player
                ),
                evaluation_str=_eval_str_from(
                    terminal=ev.terminal,
                    mate_in=ev.mate_in,
                    centipawns=ev.centipawns,
                ),
            )
        )
    return tuple(out)


def _worst_intermediate_key(
    *, path_evals: tuple[PathEval, ...], wildcard_player: str
) -> tuple[int, int]:
    """Min sort-key across strictly-intermediate plies (excluding root and leaf).

    "Worst" = lowest (sort_category, sort_secondary) from the WP's perspective.
    Used to pick a primary among transpositions: the variation whose worst
    intermediate is the highest wins (max-of-worst).

    For paths with zero intermediate plies (line length ≤ 1) there's nothing
    to compare; return a sentinel that compares equal across all candidates so
    insertion order acts as the tie-break.
    """
    intermediates: list[PathEval] = list(path_evals[1:-1])  # drop root + leaf
    if not intermediates:
        # Sentinel: a very-high key so it never artificially de-ranks anyone.
        return (10**9, 10**9)
    keys: list[tuple[int, int]] = [
        _compute_sort_key(
            terminal=pe.terminal,
            mate_in=pe.mate_in,
            centipawns=pe.centipawns,
            line_length=pe.ply,
            wildcard_player=wildcard_player,
        )
        for pe in intermediates
    ]
    return min(keys)


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
    evaluate every UNIQUE position (root + intermediates + leaves) with one
    persistent Stockfish process → assemble per-ply evals per leaf → group
    leaves by leaf FEN (transpositions) → pick a primary per group via
    max-of-worst intermediate eval → sort primaries from the WP's perspective.
    """
    started_at: float = time.time()

    moves: list[str | None] = parse_game_string_simple(
        s=spec, wildcard_symbol=wildcard_symbol
    )
    wildcard_player: str = _detect_wildcard_player(moves=moves)
    if verbosity >= 1:
        logger.info(f"Spec: {spec!r}, wildcard player: {wildcard_player}")

    tree = expand_wildcards(spec, wildcard_symbol=wildcard_symbol)
    leaf_paths: list[tuple[tuple[str, ...], tuple[str, ...]]] = list(
        tree.iter_leaf_paths()
    )
    total_leaves: int = len(leaf_paths)
    unique_fens: tuple[str, ...] = tree.unique_fens()
    if verbosity >= 1:
        logger.info(
            f"Expanded tree: {total_leaves} leaves, "
            f"{len(unique_fens)} unique positions to evaluate"
        )

    eval_cache: dict[str, EvaluationResult] = {}
    with StockfishEngine(
        depth=stockfish_depth,
        threads=stockfish_threads,
        hash_mb=stockfish_hash_mb,
        stockfish_path=stockfish_path,
    ) as engine:
        resolved_path: str = engine.resolved_stockfish_path or ""
        for fen in tqdm(unique_fens, desc="Evaluating positions", mininterval=1):
            eval_cache[fen] = engine.evaluate(fen=fen)

    # Group leaves by leaf FEN (transpositions).
    groups: dict[str, list[tuple[tuple[str, ...], tuple[str, ...]]]] = defaultdict(list)
    for line, path_fens in leaf_paths:
        groups[path_fens[-1]].append((line, path_fens))

    leaf_results: list[LeafResult] = []
    for leaf_fen, members in groups.items():
        # Build path_evals for every member, then choose the primary.
        with_evals: list[
            tuple[tuple[str, ...], tuple[str, ...], tuple[PathEval, ...]]
        ] = []
        for line, path_fens in members:
            pe: tuple[PathEval, ...] = _build_path_evals(
                line=line,
                path_fens=path_fens,
                eval_cache=eval_cache,
                wildcard_player=wildcard_player,
            )
            with_evals.append((line, path_fens, pe))

        # Max-of-worst tie-breaker; ties broken by original (deterministic) order.
        with_evals.sort(
            key=lambda item: _worst_intermediate_key(
                path_evals=item[2], wildcard_player=wildcard_player
            ),
            reverse=True,
        )
        primary_line, _primary_fens, primary_path_evals = with_evals[0]
        transpositions: tuple[Transposition, ...] = tuple(
            Transposition(line=line, path_evals=pe) for line, _, pe in with_evals[1:]
        )

        leaf_eval: EvaluationResult = eval_cache[leaf_fen]
        wp_cp: int | None = _wp_centipawns(
            centipawns=leaf_eval.centipawns, wildcard_player=wildcard_player
        )
        sort_cat, sort_sec = _compute_sort_key(
            terminal=leaf_eval.terminal,
            mate_in=leaf_eval.mate_in,
            centipawns=leaf_eval.centipawns,
            line_length=len(primary_line),
            wildcard_player=wildcard_player,
        )

        leaf_results.append(
            LeafResult(
                line=primary_line,
                fen=leaf_fen,
                centipawns=leaf_eval.centipawns,
                mate_in=leaf_eval.mate_in,
                terminal=leaf_eval.terminal,
                best_move=leaf_eval.best_move,
                principal_variation=leaf_eval.principal_variation,
                wildcard_player_centipawns=wp_cp,
                path_evals=primary_path_evals,
                transpositions=transpositions,
                sort_category=sort_cat,
                sort_secondary=sort_sec,
            )
        )

    leaf_results.sort(key=lambda r: (r.sort_category, r.sort_secondary), reverse=True)

    elapsed: float = time.time() - started_at
    if verbosity >= 1:
        total_transpositions: int = sum(len(r.transpositions) for r in leaf_results)
        logger.info(
            f"Evaluated {len(unique_fens)} positions in {elapsed:.1f}s; "
            f"{total_leaves} leaves → {len(leaf_results)} primaries "
            f"+ {total_transpositions} transpositions"
        )

    return AntivenomResult(
        spec=spec,
        wildcard_player=wildcard_player,
        wildcard_symbol=wildcard_symbol,
        stockfish_depth=stockfish_depth,
        stockfish_threads=stockfish_threads,
        stockfish_hash_mb=stockfish_hash_mb,
        stockfish_path=resolved_path,
        total_leaves=total_leaves,
        unique_leaves=len(leaf_results),
        unique_positions_evaluated=len(unique_fens),
        evaluated_at_unix=started_at,
        elapsed_seconds=elapsed,
        results=tuple(leaf_results),
    )
