"""Tests for Stockfish evaluation."""

import pytest
import chess

from src.v0.chess_tools.evaluation import (
    evaluate_position,
    evaluate_fen,
    find_stockfish,
    EvaluationResult,
    MultiPVResult,
)


# Skip all tests in this module if Stockfish is not available
pytestmark = pytest.mark.skipif(
    find_stockfish() is None,
    reason="Stockfish not installed",
)


class TestFindStockfish:
    """Tests for Stockfish binary detection."""

    def test_find_stockfish_returns_path(self):
        """find_stockfish should return a path when Stockfish is installed."""
        path = find_stockfish()
        # If we got here, Stockfish is installed (skipif didn't trigger)
        assert path is not None
        assert isinstance(path, str)


class TestEvaluatePosition:
    """Tests for position evaluation with Board objects."""

    def test_starting_position_is_roughly_equal(self):
        """Starting position should evaluate close to 0."""
        board = chess.Board()
        result = evaluate_position(board, depth=10)

        assert isinstance(result, EvaluationResult)
        assert result.centipawns is not None
        # Should be within ±50 centipawns of equality
        assert -50 <= result.centipawns <= 50

    def test_returns_evaluation_result(self):
        """Should return an EvaluationResult dataclass."""
        board = chess.Board()
        result = evaluate_position(board, depth=8)

        assert isinstance(result, EvaluationResult)
        assert result.best_move != ""
        assert result.best_move_uci != ""
        assert len(result.principal_variation) > 0
        assert result.depth >= 8

    def test_winning_position_has_positive_eval(self):
        """A winning position for White should have positive centipawns.

        Position: Starting position but Black's queen is missing.
        White has a massive material advantage (queen = ~9 pawns).
        """
        # White is up a queen
        fen = "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        board = chess.Board(fen)
        result = evaluate_position(board, depth=10)

        assert result.centipawns is not None
        assert result.centipawns > 500  # At least 5 pawns advantage

    def test_losing_position_has_negative_eval(self):
        """A losing position for White should have negative centipawns.

        Position: Starting position but White's queen is missing.
        Black has a massive material advantage (queen = ~9 pawns).
        """
        # Black is up a queen
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 1"
        board = chess.Board(fen)
        result = evaluate_position(board, depth=10)

        assert result.centipawns is not None
        assert result.centipawns < -500

    def test_evaluation_str_for_centipawns(self):
        """evaluation_str should format centipawns correctly."""
        board = chess.Board()
        result = evaluate_position(board, depth=8)

        eval_str = result.evaluation_str
        assert eval_str.startswith("+") or eval_str.startswith("-") or eval_str.startswith("0")

    def test_is_mate_false_for_normal_position(self):
        """is_mate should be False for non-mate positions."""
        board = chess.Board()
        result = evaluate_position(board, depth=8)

        assert not result.is_mate
        assert result.mate_in is None


class TestMateDetection:
    """Tests for checkmate detection."""

    def test_mate_in_one_detected(self):
        """Should detect mate in 1.

        Position: The "Scholar's Mate" setup. White has queen on h5, bishop on c4.
        Black has played poorly (knight to c6 and f6, pawn to e5).
        White to move can play Qxf7#, checkmating the king since the f7 pawn
        is only defended by the king itself.
        """
        # White to play and mate in 1 with Qf7#
        fen = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
        board = chess.Board(fen)
        result = evaluate_position(board, depth=10)

        assert result.is_mate
        assert result.mate_in == 1
        assert result.centipawns is None

    def test_mate_evaluation_str(self):
        """evaluation_str should show mate notation.

        Same Scholar's Mate position as above - verifies the eval string
        shows "M1" or similar mate notation instead of centipawns.
        """
        fen = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
        board = chess.Board(fen)
        result = evaluate_position(board, depth=10)

        assert "M" in result.evaluation_str


class TestMultiPV:
    """Tests for multiple principal variation analysis."""

    def test_multipv_returns_multiple_lines(self):
        """multipv > 1 should return multiple lines."""
        board = chess.Board()
        result = evaluate_position(board, depth=8, multipv=3)

        assert isinstance(result, MultiPVResult)
        assert len(result.lines) == 3
        assert all(isinstance(line, EvaluationResult) for line in result.lines)

    def test_multipv_lines_are_ordered(self):
        """MultiPV lines should be ordered by evaluation."""
        board = chess.Board()
        result = evaluate_position(board, depth=10, multipv=3)

        # First line should be best (or equal)
        evals = [
            line.centipawns if line.centipawns is not None else 100000
            for line in result.lines
        ]
        # For white to move, higher is better
        assert evals[0] >= evals[-1]

    def test_multipv_includes_fen(self):
        """MultiPVResult should include the FEN."""
        board = chess.Board()
        result = evaluate_position(board, depth=8, multipv=2)

        assert result.fen == board.fen()


class TestEvaluateFen:
    """Tests for FEN string evaluation."""

    def test_evaluate_fen_works(self):
        """Should evaluate a FEN string."""
        result = evaluate_fen(chess.STARTING_FEN, depth=8)

        assert isinstance(result, EvaluationResult)
        assert result.best_move != ""

    def test_evaluate_fen_custom_position(self):
        """Should evaluate custom FEN positions.

        Position: White pawn on e4, Black pawn on c5. Non-starting position
        to verify FEN parsing works beyond the default board.
        """
        # Sicilian Defense position
        fen = "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2"
        result = evaluate_fen(fen, depth=10)

        assert isinstance(result, EvaluationResult)


class TestEngineConfiguration:
    """Tests for engine configuration options."""

    def test_depth_parameter_respected(self):
        """Higher depth should generally not give worse results."""
        board = chess.Board()

        result_low = evaluate_position(board, depth=5)
        result_high = evaluate_position(board, depth=15)

        assert result_high.depth >= result_low.depth

    def test_custom_stockfish_path(self):
        """Should accept custom Stockfish path."""
        path = find_stockfish()
        board = chess.Board()

        result = evaluate_position(board, depth=8, stockfish_path=path)

        assert isinstance(result, EvaluationResult)


class TestErrorHandling:
    """Tests for error conditions."""

    def test_invalid_stockfish_path_raises_error(self):
        """Invalid Stockfish path should raise FileNotFoundError."""
        board = chess.Board()

        with pytest.raises(FileNotFoundError):
            evaluate_position(board, stockfish_path="/nonexistent/path/stockfish")


class TestDataclassProperties:
    """Tests for dataclass behavior."""

    def test_evaluation_result_is_frozen(self):
        """EvaluationResult should be immutable."""
        board = chess.Board()
        result = evaluate_position(board, depth=8)

        with pytest.raises(AttributeError):
            result.centipawns = 100

    def test_multipv_result_is_frozen(self):
        """MultiPVResult should be immutable."""
        board = chess.Board()
        result = evaluate_position(board, depth=8, multipv=2)

        with pytest.raises(AttributeError):
            result.fen = "different"
