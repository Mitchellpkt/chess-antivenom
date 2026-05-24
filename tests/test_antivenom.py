"""End-to-end tests for the antivenom pipeline.

Stockfish-dependent tests are skipped if the binary isn't found.
Wildcard-player detection tests don't need Stockfish.
"""
from __future__ import annotations

import pytest

from src.v0.antivenom import (
    _detect_wildcard_player,
    run_antivenom,
)
from src.v0.chess_tools.evaluation import find_stockfish


needs_stockfish = pytest.mark.skipif(
    find_stockfish() is None, reason="Stockfish not installed"
)


class TestDetectWildcardPlayer:
    """Pure-Python tests for inferring the wildcard player from a parsed spec."""

    def test_black_wildcards_silly_knight(self):
        # 1. Nf3 __ 2. Ne5 __  →  white concrete, black all wildcards
        moves: list[str | None] = ["Nf3", None, "Ne5", None]
        assert _detect_wildcard_player(moves=moves) == "black"

    def test_white_wildcards_fangs_black(self):
        # 1. __ f6 2. __ c6 3. __  →  black concrete, white all wildcards
        moves = [None, "f6", None, "c6", None]
        assert _detect_wildcard_player(moves=moves) == "white"

    def test_black_wildcards_fool(self):
        moves = ["g4", None, "f3", None, "Nc3", None]
        assert _detect_wildcard_player(moves=moves) == "black"

    def test_only_wildcards_raises(self):
        moves = [None, None, None]
        with pytest.raises(ValueError, match="only wildcards"):
            _detect_wildcard_player(moves=moves)

    def test_mixed_concrete_and_wildcard_on_same_side_raises(self):
        # White: e4 (concrete) + None (wildcard) → malformed
        moves = ["e4", None, None, "Nf6"]
        with pytest.raises(ValueError, match="malformed"):
            _detect_wildcard_player(moves=moves)


@needs_stockfish
class TestRunAntivenomSillyKnight:
    """The README example: 1. Nf3 __ 2. Ne5 __

    The three top results for the wildcard player (black) should all win a
    knight cleanly — namely the three legal ways to capture the white knight
    after it lands on e5: dxe5, fxe5, Nxe5.
    """

    def test_top_three_are_the_knight_captures(self):
        result = run_antivenom(
            spec="1. Nf3 __ 2. Ne5 __",
            stockfish_depth=8,
            stockfish_threads=1,
            stockfish_hash_mb=128,
            wildcard_symbol="__",
            stockfish_path=None,
            verbosity=0,
        )

        assert result.wildcard_player == "black"
        assert result.total_leaves > 0

        top_three_lines: set[tuple[str, ...]] = {
            r.line for r in result.results[:3]
        }
        expected: set[tuple[str, ...]] = {
            ("Nf3", "Nc6", "Ne5", "Nxe5"),
            ("Nf3", "d6", "Ne5", "dxe5"),
            ("Nf3", "f6", "Ne5", "fxe5"),
        }
        assert top_three_lines == expected, (
            f"Top 3 lines were {top_three_lines}, expected {expected}"
        )

    def test_top_three_eval_indicates_knight_advantage(self):
        """All three top results should show black up roughly a knight."""
        result = run_antivenom(
            spec="1. Nf3 __ 2. Ne5 __",
            stockfish_depth=8,
            stockfish_threads=1,
            stockfish_hash_mb=128,
            wildcard_symbol="__",
            stockfish_path=None,
            verbosity=0,
        )

        for r in result.results[:3]:
            # wildcard_player_centipawns: positive means good for black (the WP).
            # Winning a knight should be ~+300 cp for black.
            assert r.wildcard_player_centipawns is not None
            assert r.wildcard_player_centipawns >= 200, (
                f"Line {r.line} only scored {r.wildcard_player_centipawns} cp "
                f"for the wildcard player — expected ≥+200 (knight up)."
            )


@needs_stockfish
class TestRunAntivenomFoolMate:
    """Fool's-mate edge case: 1. g4 __ 2. f3 __

    Black has TWO ways to mate at ply 4: 1...e5 2. f3 Qh4# and 1...e6 2. f3 Qh4#.
    Both have length 4 (terminal short-circuit prevented the tree from trying
    to apply any further system moves). The top two results should be these
    mates; everything else should be a non-terminal length-4 leaf.
    """

    def test_top_two_are_fool_mates(self):
        result = run_antivenom(
            spec="1. g4 __ 2. f3 __",
            stockfish_depth=6,
            stockfish_threads=1,
            stockfish_hash_mb=128,
            wildcard_symbol="__",
            stockfish_path=None,
            verbosity=0,
        )

        assert result.wildcard_player == "black"

        expected_mates: set[tuple[str, ...]] = {
            ("g4", "e5", "f3", "Qh4#"),
            ("g4", "e6", "f3", "Qh4#"),
        }

        top_two_lines: set[tuple[str, ...]] = {r.line for r in result.results[:2]}
        assert top_two_lines == expected_mates, (
            f"Top 2 lines were {top_two_lines}, expected {expected_mates}"
        )
        for r in result.results[:2]:
            assert r.terminal == "black_wins"
            assert len(r.line) == 4

    def test_full_fool_spec_keeps_mate_at_top(self):
        """With the full 6-ply fool spec, the mate branches still rank #1 and #2
        and their lines remain length 4 (the third system ply '3. Nc3' was never
        applied because the game was already over).
        """
        result = run_antivenom(
            spec="1. g4 __ 2. f3 __ 3. Nc3 __",
            stockfish_depth=4,
            stockfish_threads=1,
            stockfish_hash_mb=128,
            wildcard_symbol="__",
            stockfish_path=None,
            verbosity=0,
        )

        top = result.results[0]
        second = result.results[1]
        assert top.terminal == "black_wins"
        assert second.terminal == "black_wins"
        assert {top.line, second.line} == {
            ("g4", "e5", "f3", "Qh4#"),
            ("g4", "e6", "f3", "Qh4#"),
        }
        assert len(top.line) == 4
        assert len(second.line) == 4

        # Plenty of non-mate length-6 leaves should also exist.
        non_terminal_length_6 = [
            r for r in result.results if r.terminal is None and len(r.line) == 6
        ]
        assert len(non_terminal_length_6) > 100


@needs_stockfish
class TestRunAntivenomSmoke:
    """Smoke test: trivial spec, just confirm the pipeline produces output."""

    def test_minimal_pipeline_runs(self):
        # White is system (plays e4), black is wildcard (one ply).
        result = run_antivenom(
            spec="1. e4 __",
            stockfish_depth=4,
            stockfish_threads=1,
            stockfish_hash_mb=64,
            wildcard_symbol="__",
            stockfish_path=None,
            verbosity=0,
        )

        assert result.wildcard_player == "black"
        assert result.total_leaves == 20
        # No transpositions possible with a single wildcard ply.
        assert result.unique_leaves == 20
        assert len(result.results) == 20
        # All results should have line length 2.
        assert all(len(r.line) == 2 for r in result.results)
        # Each primary carries a path_evals tuple of length len(line)+1.
        for r in result.results:
            assert len(r.path_evals) == len(r.line) + 1
            assert r.path_evals[0].ply == 0
            assert r.path_evals[-1].fen == r.fen
            assert r.transpositions == ()
        # JSON shape includes meta + results.
        d = result.to_json_dict()
        assert "meta" in d
        assert "results" in d
        assert d["meta"]["wildcard_player"] == "black"
        assert d["meta"]["total_leaves"] == 20
        assert d["meta"]["unique_leaves"] == 20
        assert d["meta"]["unique_positions_evaluated"] >= 21  # root + 20 ply-1 positions
        assert len(d["results"]) == 20
        assert d["results"][0]["rank"] == 1
        assert "path_evals" in d["results"][0]
        assert "transpositions" in d["results"][0]


@needs_stockfish
class TestRunAntivenomTranspositions:
    """When two distinct wildcard-player move orders reach the same leaf FEN,
    they're folded into one primary + N transpositions."""

    def test_two_wildcards_produce_transpositions(self):
        # 4-ply: white plays two wildcards, black is forced f6/c6. Any pair of
        # non-interacting white moves will transpose (e.g. Nf3-Nc3 == Nc3-Nf3).
        result = run_antivenom(
            spec="1. __ f6 2. __ c6",
            stockfish_depth=6,
            stockfish_threads=1,
            stockfish_hash_mb=64,
            wildcard_symbol="__",
            stockfish_path=None,
            verbosity=0,
        )

        assert result.wildcard_player == "white"
        # Strictly fewer primaries than total enumerated leaves.
        assert result.unique_leaves < result.total_leaves, (
            f"Expected some transpositions, but got {result.unique_leaves} "
            f"primaries from {result.total_leaves} leaves."
        )
        total_trans = sum(len(r.transpositions) for r in result.results)
        # The leaves are partitioned into (primaries) + (their transpositions).
        assert result.unique_leaves + total_trans == result.total_leaves

    def test_transpositions_share_leaf_fen_with_primary(self):
        result = run_antivenom(
            spec="1. __ f6 2. __ c6",
            stockfish_depth=4,
            stockfish_threads=1,
            stockfish_hash_mb=64,
            wildcard_symbol="__",
            stockfish_path=None,
            verbosity=0,
        )

        # Pick any primary that has transpositions, then verify they all reach
        # the same final FEN by replay.
        import chess as _chess

        for r in result.results:
            if not r.transpositions:
                continue
            for t in r.transpositions:
                board = _chess.Board()
                for san in t.line:
                    board.push_san(san)
                assert board.fen() == r.fen, (
                    f"Transposition line {t.line} reached {board.fen()}, "
                    f"expected primary FEN {r.fen}"
                )
            break  # one such example is enough
        else:
            pytest.fail("Expected at least one primary with transpositions in this spec.")
