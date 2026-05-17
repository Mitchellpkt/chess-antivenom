"""Wildcard expansion for PGN-with-wildcards into opening trees."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import chess
from loguru import logger

from .parser import parse_game_string_simple


# Sentinel reasons a leaf node has no children.
_LEAF_TERMINAL: str = "game_over"  # checkmate / stalemate / draw at this node
_LEAF_SPEC_DONE: str = "spec_complete"  # all system moves applied, sequence ended


class _IllegalSystemMove(Exception):
    """Internal: raised when a system (concrete) move cannot be played in the current position.

    Caught at the nearest enclosing wildcard branch and used to prune that branch.
    If it bubbles to the top level (no wildcard above), expand_wildcards re-raises
    it as a ValueError because the spec itself is malformed.
    """


@dataclass(frozen=True)
class MoveNode:
    """A node in the opening tree.

    Represents a position reached after a move, with all possible continuations
    as children. The root node has move=None.
    """

    move: str | None
    """SAN move that led to this position (None for root)."""

    fen: str
    """FEN string of the position after this move."""

    children: tuple[MoveNode, ...]
    """Child nodes representing possible continuations."""

    def flatten(self) -> list[tuple[str, ...]]:
        """Return all complete lines as tuples of SAN moves.

        Each tuple represents a path from the root to a leaf node.
        The root's move (None) is excluded from the output.
        """
        return self._flatten_recursive(prefix=())

    def _flatten_recursive(self, prefix: tuple[str, ...]) -> list[tuple[str, ...]]:
        current: tuple[str, ...] = prefix + (self.move,) if self.move else prefix
        if not self.children:
            return [current] if current else [()]
        lines: list[tuple[str, ...]] = []
        for child in self.children:
            lines.extend(child._flatten_recursive(current))
        return lines

    def iter_leaves(self) -> Iterator[tuple[tuple[str, ...], str]]:
        """Yield (line, fen) for every leaf in the tree.

        A leaf is any node with no children. This includes:
          - Nodes where the spec ran out of moves (natural end of sequence).
          - Nodes where the position became game-over (checkmate / stalemate / draw)
            and expansion stopped before applying any remaining system moves.

        Yields one (line, fen) per leaf, in deterministic depth-first order.
        """
        yield from self._iter_leaves_recursive(prefix=())

    def _iter_leaves_recursive(
        self, prefix: tuple[str, ...]
    ) -> Iterator[tuple[tuple[str, ...], str]]:
        current: tuple[str, ...] = prefix + (self.move,) if self.move else prefix
        if not self.children:
            yield (current, self.fen)
            return
        for child in self.children:
            yield from child._iter_leaves_recursive(current)

    @property
    def line_count(self) -> int:
        """Total number of leaf positions (complete lines)."""
        if not self.children:
            return 1
        return sum(child.line_count for child in self.children)


def expand_wildcards(
    pgn_with_wildcards: str,
    wildcard_symbol: str = "__",
) -> MoveNode:
    """Expand a PGN-with-wildcards string into a tree of all variations.

    Branching rules:
      - Wildcard ply (``wildcard_symbol``): branch into every legal move.
      - Concrete (system) ply: single branch. If the move is illegal in the
        position reached down some wildcard subtree, that subtree is silently
        pruned (the wildcard choice leading there is dropped from the tree).
        If the move is illegal at the root level (no wildcard above it), a
        ``ValueError`` is raised — the spec itself is malformed.
      - Game-over (checkmate / stalemate / draw): expansion stops immediately;
        the current node becomes a leaf regardless of remaining system moves.

    Args:
        pgn_with_wildcards: PGN string where ``wildcard_symbol`` means "any legal move".
        wildcard_symbol: The symbol representing wildcards (default: "__").

    Returns:
        MoveNode tree. The root has ``move=None`` and represents the starting position.
    """
    moves: list[str | None] = parse_game_string_simple(
        s=pgn_with_wildcards, wildcard_symbol=wildcard_symbol
    )
    board: chess.Board = chess.Board()

    try:
        children: tuple[MoveNode, ...] = _expand_moves(board=board, moves=moves)
    except _IllegalSystemMove as e:
        # Bubbled up past every wildcard catch — spec is unconditionally illegal.
        raise ValueError(
            f"Illegal move in spec: {e}. The move is not legal in this position. "
            f"This can happen when a repertoire move becomes illegal after certain "
            f"opponent responses."
        ) from None

    if moves and not children:
        logger.warning(
            f"Spec parsed to {len(moves)} plies but produced no valid lines "
            f"(all wildcard branches were pruned because the system move became illegal)."
        )

    return MoveNode(move=None, fen=board.fen(), children=children)


def _expand_moves(
    *, board: chess.Board, moves: list[str | None]
) -> tuple[MoveNode, ...]:
    """Recursively expand a remaining move sequence into a tree of children.

    Returns the children of the current (caller's) node. An empty tuple means
    "the caller's node is a leaf" — either because the spec is done, the game
    is over, or (only at the wildcard layer) every candidate child was pruned.
    """
    # Game-over: stop expanding. The caller's node is a terminal leaf.
    if board.is_game_over():
        return ()

    # Spec exhausted: stop expanding. The caller's node is a natural-end leaf.
    if not moves:
        return ()

    current_move: str | None = moves[0]
    remaining: list[str | None] = moves[1:]

    if current_move is None:
        # Wildcard: branch into every legal move. If a child subtree fails because
        # a downstream system move is illegal, silently drop that child.
        children: list[MoveNode] = []
        for legal_move in board.legal_moves:
            san: str = board.san(legal_move)
            new_board: chess.Board = board.copy()
            new_board.push(legal_move)
            try:
                grand_children: tuple[MoveNode, ...] = _expand_moves(
                    board=new_board, moves=remaining
                )
            except _IllegalSystemMove:
                continue
            children.append(
                MoveNode(move=san, fen=new_board.fen(), children=grand_children)
            )
        return tuple(children)

    # Concrete (system) move: single branch. Bubble _IllegalSystemMove up to the
    # nearest enclosing wildcard so it can prune the branch.
    try:
        parsed_move: chess.Move = board.parse_san(current_move)
    except (chess.IllegalMoveError, chess.InvalidMoveError, chess.AmbiguousMoveError, ValueError):
        raise _IllegalSystemMove(f"'{current_move}' in position {board.fen()}") from None

    new_board = board.copy()
    new_board.push(parsed_move)
    return (
        MoveNode(
            move=current_move,
            fen=new_board.fen(),
            children=_expand_moves(board=new_board, moves=remaining),
        ),
    )
