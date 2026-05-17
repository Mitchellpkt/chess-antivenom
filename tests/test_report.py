"""Tests for the JSON-to-HTML report converter.

Stockfish-free: the converter is a pure function on a results dict, so we
build a small synthetic fixture here and assert on the returned HTML string.
This is the whole point of keeping ``report.py`` standalone — iterate on the
report without re-running a Stockfish search.
"""
from __future__ import annotations

import chess
import pytest

from src.v0.report import (
    _bucket_for_result,
    _compute_aggregate_stats,
    _eval_class,
    _line_to_pgn,
    json_to_html,
)


def _make_fixture_data() -> dict:
    """A miniature antivenom result dict covering several outcome types.

    Black is the wildcard player. Results include a checkmate-by-WP, a
    knight-up centipawn win, a roughly-even line, and a losing line.
    """
    return {
        "meta": {
            "spec": "1. g4 __ 2. f3 __",
            "wildcard_player": "black",
            "wildcard_symbol": "__",
            "stockfish": {
                "path": "/usr/games/stockfish",
                "depth": 12,
                "threads": 1,
                "hash_mb": 128,
            },
            "total_leaves": 4,
            "evaluated_at_unix": 1700000000.0,
            "elapsed_seconds": 1.23,
            "experiment_tag": "test_fixture",
            "input_path": "/tmp/fake.pgn",
        },
        "results": [
            {
                "rank": 1,
                "line": ["g4", "e5", "f3", "Qh4#"],
                "fen": "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3",
                "centipawns": None,
                "mate_in": None,
                "terminal": "black_wins",
                "wildcard_player_centipawns": None,
                "evaluation_str": "black_wins",
                "best_move": "",
                "principal_variation": [],
            },
            {
                "rank": 2,
                "line": ["g4", "d6", "f3", "Nf6"],
                "fen": "rnbqkb1r/ppp1pppp/3p1n2/8/6P1/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3",
                "centipawns": -50,
                "mate_in": None,
                "terminal": None,
                "wildcard_player_centipawns": 50,
                "evaluation_str": "-0.50",
                "best_move": "e3",
                "principal_variation": ["e3", "g6"],
            },
            {
                "rank": 3,
                "line": ["g4", "Nf6", "f3", "h6"],
                "fen": "rnbqkb1r/pppppp2/5n1p/8/6P1/5P2/PPPPP2P/RNBQKBNR w KQkq - 0 3",
                "centipawns": 30,
                "mate_in": None,
                "terminal": None,
                "wildcard_player_centipawns": -30,
                "evaluation_str": "+0.30",
                "best_move": "Nc3",
                "principal_variation": ["Nc3", "Nc6"],
            },
            {
                "rank": 4,
                "line": ["g4", "Nc6", "f3", "Nb8"],
                "fen": "rnbqkbnr/pppppppp/8/8/6P1/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3",
                "centipawns": 80,
                "mate_in": None,
                "terminal": None,
                "wildcard_player_centipawns": -80,
                "evaluation_str": "+0.80",
                "best_move": "d4",
                "principal_variation": ["d4", "e5"],
            },
        ],
    }


class TestLineToPgn:
    def test_alternates_with_move_numbers(self):
        assert _line_to_pgn(line=["e4", "e5", "Nf3", "Nc6"]) == "1. e4 e5 2. Nf3 Nc6"

    def test_white_only_first_move(self):
        assert _line_to_pgn(line=["e4"]) == "1. e4"

    def test_uneven_length(self):
        assert _line_to_pgn(line=["e4", "e5", "Nf3"]) == "1. e4 e5 2. Nf3"

    def test_empty(self):
        assert _line_to_pgn(line=[]) == ""


class TestBucketing:
    def test_wp_wins_terminal_for_black_wp(self):
        r = {"terminal": "black_wins", "mate_in": None, "wildcard_player_centipawns": None}
        assert _bucket_for_result(r=r, wp="black") == "term_wp_wins"

    def test_wp_loses_terminal_for_black_wp(self):
        r = {"terminal": "white_wins", "mate_in": None, "wildcard_player_centipawns": None}
        assert _bucket_for_result(r=r, wp="black") == "term_wp_loses"

    def test_draw_terminal(self):
        r = {"terminal": "draw_stalemate", "mate_in": None, "wildcard_player_centipawns": None}
        assert _bucket_for_result(r=r, wp="black") == "term_draw"

    def test_engine_mate_for_wp(self):
        # White WP, white mates in 3 → for WP.
        r = {"terminal": None, "mate_in": 3, "wildcard_player_centipawns": None}
        assert _bucket_for_result(r=r, wp="white") == "engine_mate_for_wp"

    def test_engine_mate_against_wp(self):
        # Black WP, white mates in 3 → against WP.
        r = {"terminal": None, "mate_in": 3, "wildcard_player_centipawns": None}
        assert _bucket_for_result(r=r, wp="black") == "engine_mate_vs_wp"

    def test_cp_buckets(self):
        for wp_cp, expected in [
            (600, "wp_winning_big"),
            (200, "wp_winning"),
            (50, "even"),
            (0, "even"),
            (-50, "even"),
            (-200, "wp_losing"),
            (-600, "wp_losing_big"),
        ]:
            r = {"terminal": None, "mate_in": None, "wildcard_player_centipawns": wp_cp}
            assert _bucket_for_result(r=r, wp="white") == expected, f"failed for {wp_cp}"


class TestEvalClass:
    def test_terminal_win_for_wp(self):
        assert _eval_class(
            wp_cp=None, terminal="black_wins", mate_in=None, wp="black"
        ) == "eval-terminal-win"

    def test_terminal_loss_for_wp(self):
        assert _eval_class(
            wp_cp=None, terminal="black_wins", mate_in=None, wp="white"
        ) == "eval-terminal-loss"

    def test_high_cp_for_wp_is_best_class(self):
        assert _eval_class(
            wp_cp=400, terminal=None, mate_in=None, wp="white"
        ) == "eval-wp-best"


class TestAggregateStats:
    def test_counts_and_cp_summary(self):
        data = _make_fixture_data()
        stats = _compute_aggregate_stats(
            results=data["results"], wildcard_player="black"
        )
        assert stats["total"] == 4
        # One terminal black_wins, three cp lines.
        assert stats["buckets"]["term_wp_wins"] == 1
        # cp values for WP (black): 50, -30, -80 → mean ≈ -20.
        assert stats["cp_summary"]["count_with_cp"] == 3
        assert stats["cp_summary"]["best"] == 50
        assert stats["cp_summary"]["worst"] == -80
        # Line lengths: one length-4 (mate), three length-4 (full spec).
        assert stats["line_length_counts"] == {4: 4}


class TestJsonToHtmlIntegration:
    def test_returns_self_contained_document(self):
        html = json_to_html(data=_make_fixture_data())
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html.strip().splitlines()[-1]

    def test_no_external_assets(self):
        html = json_to_html(data=_make_fixture_data())
        # No remote stylesheets, scripts, or images.
        assert "http://" not in html.replace("http://www.w3.org", "")  # SVG xmlns allowed
        # Lichess links are intentional (user-facing only) — they go through escape().
        assert "<script" not in html
        assert "<link rel=\"stylesheet\"" not in html

    def test_contains_spec_and_top_line(self):
        html = json_to_html(data=_make_fixture_data())
        assert "1. g4 __ 2. f3 __" in html
        # PGN-formatted top line should appear in the header quickstats.
        assert "1. g4 e5 2. f3 Qh4#" in html

    def test_all_results_appear(self):
        data = _make_fixture_data()
        html = json_to_html(data=data, top_n_with_boards=2)
        # Every line should be visible somewhere in the report.
        for r in data["results"]:
            assert _line_to_pgn(line=r["line"]) in html

    def test_terminal_solution_has_terminal_class(self):
        html = json_to_html(data=_make_fixture_data())
        # The fool's-mate row uses the eval-terminal-win class for the WP.
        assert "eval-terminal-win" in html

    def test_inline_svg_present_for_top_solutions(self):
        html = json_to_html(data=_make_fixture_data(), top_n_with_boards=2)
        # python-chess emits SVG with an xmlns declaration.
        assert "<svg" in html
        assert "xmlns=\"http://www.w3.org/2000/svg\"" in html

    def test_lichess_link_present(self):
        html = json_to_html(data=_make_fixture_data())
        assert "lichess.org/analysis" in html

    def test_handles_empty_results(self):
        data = _make_fixture_data()
        data["results"] = []
        data["meta"]["total_leaves"] = 0
        html = json_to_html(data=data)
        # Should still produce a valid doc — no crash, header still there.
        assert html.startswith("<!DOCTYPE html>")
        assert "1. g4 __ 2. f3 __" in html

    def test_per_first_move_grouping(self):
        """For wildcard_player='black', WP first move is line[1]. With our fixture,
        the four lines have black first moves: e5, d6, Nf6, Nc6 — four distinct groups."""
        html = json_to_html(data=_make_fixture_data())
        assert "4 distinct first moves" in html


class TestWhiteWildcardPlayer:
    """Sanity check: when the WP is white, line[0] is their first move and
    the report should orient itself accordingly."""

    def test_white_wp_groups_by_line_index_0(self):
        data = {
            "meta": {
                "spec": "1. __ f6 2. __ c6 3. __",
                "wildcard_player": "white",
                "wildcard_symbol": "__",
                "stockfish": {"path": "x", "depth": 8, "threads": 1, "hash_mb": 64},
                "total_leaves": 2,
                "evaluated_at_unix": 0,
                "elapsed_seconds": 0.1,
                "experiment_tag": "white_wp_test",
                "input_path": "x",
            },
            "results": [
                {
                    "rank": 1,
                    "line": ["e4", "f6", "Qh5+", "c6", "Qxe5"],
                    "fen": chess.STARTING_FEN,
                    "centipawns": 200,
                    "mate_in": None,
                    "terminal": None,
                    "wildcard_player_centipawns": 200,
                    "evaluation_str": "+2.00",
                    "best_move": "Nf3",
                    "principal_variation": ["Nf3"],
                },
                {
                    "rank": 2,
                    "line": ["d4", "f6", "e3", "c6", "Nf3"],
                    "fen": chess.STARTING_FEN,
                    "centipawns": 50,
                    "mate_in": None,
                    "terminal": None,
                    "wildcard_player_centipawns": 50,
                    "evaluation_str": "+0.50",
                    "best_move": "c4",
                    "principal_variation": ["c4"],
                },
            ],
        }
        html = json_to_html(data=data)
        # Two distinct WP first moves (e4 and d4).
        assert "2 distinct first moves" in html
