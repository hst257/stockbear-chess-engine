"""Exercise the actual standalone executable, not a Python search substitute."""

import os
import json
import queue
import random
import subprocess
import threading
import time

import chess
import chess.engine
import pytest


class Protocol:
    def __init__(self, path):
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.process = subprocess.Popen([str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, **flags)
        self.lines = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.send("setoption name UsePST value false")  # Legacy material baselines.

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line.strip())

    def send(self, line):
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def until(self, prefix, timeout=3):
        deadline = time.monotonic() + timeout
        lines = []
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            lines.append(line)
            if line.startswith(prefix):
                return lines
        pytest.fail(f"No {prefix!r} received; output: {lines!r}")

    def close(self):
        if self.process.poll() is None:
            self.send("quit")
            self.process.wait(timeout=3)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


@pytest.fixture
def protocol(engine_path):
    instance = Protocol(engine_path)
    yield instance
    instance.close()


def test_uci_handshake_options_and_unknown_commands(engine):
    assert engine.id["name"].startswith("ChessLab")
    assert engine.options["AlphaBeta"].default is True
    assert engine.options["IterativeDeepening"].default is True
    assert engine.options["MoveOrdering"].default is True
    assert engine.options["UsePST"].default is True
    assert engine.options["Depth"].default == 3
    engine.ping()


def test_uci_evaluation_diagnostics_use_info_strings_and_preserve_position(protocol):
    protocol.send("position startpos moves g1f3")
    for enabled in (True, False, True):
        protocol.send(f"setoption name UsePST value {str(enabled).lower()}")
        protocol.send("eval")
        lines = protocol.until("info string eval ")
        assert all(line.startswith("info string ") for line in lines)
        value = json.loads(lines[-1].removeprefix("info string eval "))
        assert value["use_pst"] == enabled and value["material"] == 0
        assert value["total"] == (50 if enabled else 0)
        assert value["phase"] == 24
        assert value["positional"] == sum(value["pst"].values())
    protocol.send("go depth 1")
    lines = protocol.until("bestmove")
    board = chess.Board()
    board.push_uci("g1f3")
    assert chess.Move.from_uci(lines[-1].split()[1]) in board.legal_moves


@pytest.mark.parametrize("depth,nodes", [(0, 1), (1, 20), (2, 400), (3, 8902), (4, 197281)])
def test_starting_position_perft(engine_path, depth, nodes):
    result = subprocess.run([str(engine_path), "--perft", str(depth)], capture_output=True, text=True,
                            timeout=5, check=True)
    assert int(result.stdout) == nodes


def test_castling_position_perft(engine_path):
    fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
    result = subprocess.run([str(engine_path), "--perft", "3", fen], capture_output=True,
                            text=True, timeout=5, check=True)
    assert int(result.stdout) == 97862


SPECIAL_FENS = [
    "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
    "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1",
    "7k/P7/8/8/8/8/8/7K w - - 0 1",
    "7k/8/8/8/8/8/p7/7K b - - 0 1",
    "4r1k1/8/8/8/8/8/4R3/4K3 w - - 0 1",
    "7k/8/8/3pP3/8/8/8/7K w - d6 0 2",
]


@pytest.mark.parametrize("fen", SPECIAL_FENS)
def test_special_legal_moves_match_python_chess(engine_path, fen):
    result = subprocess.run([str(engine_path), "--legal-moves", fen], capture_output=True,
                            text=True, timeout=5, check=True)
    assert set(result.stdout.split()) == {move.uci() for move in chess.Board(fen).legal_moves}


def test_legal_moves_across_seeded_game_match_independent_rules(engine_path):
    rng = random.Random(37)
    board = chess.Board()
    for ply in range(100):
        if board.is_game_over():
            break
        if ply % 8 == 0:
            result = subprocess.run([str(engine_path), "--legal-moves", board.fen()],
                                    capture_output=True, text=True, timeout=5, check=True)
            assert set(result.stdout.split()) == {move.uci() for move in board.legal_moves}
        board.push(rng.choice(list(board.legal_moves)))


@pytest.mark.parametrize("ordering", [False, True])
@pytest.mark.parametrize("fen", [chess.STARTING_FEN, *SPECIAL_FENS,
                                "7k/8/5KQ1/8/8/8/8/8 w - - 0 1"])
def test_pruning_preserves_move_and_score_at_identical_depth(engine, fen, ordering):
    engine.configure({"IterativeDeepening": False, "MoveOrdering": ordering})
    board = chess.Board(fen)
    results = []
    for pruning in (False, True):
        engine.configure({"AlphaBeta": pruning})
        result = engine.play(board, chess.engine.Limit(depth=3, time=5), info=chess.engine.INFO_ALL)
        assert result.info["depth"] == 3
        assert result.move in board.legal_moves
        pv_board = board.copy()
        for move in result.info.get("pv", []):
            assert move in pv_board.legal_moves
            pv_board.push(move)
        results.append(result)
    assert results[0].move == results[1].move
    assert results[0].info["score"] == results[1].info["score"]
    assert results[1].info["nodes"] <= results[0].info["nodes"]
    if fen == chess.STARTING_FEN:
        assert results[0].info["nodes"] == 9323
        assert results[1].info["nodes"] < 1000


@pytest.mark.parametrize("pruning", [False, True])
def test_material_search_takes_free_queen(engine, pruning):
    board = chess.Board("7k/8/8/8/8/8/q7/R6K w - - 0 1")
    engine.configure({"AlphaBeta": pruning})
    result = engine.play(board, chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    assert result.move == chess.Move.from_uci("a1a2")
    assert result.info["score"].white().score() == 500


def test_black_score_sign_and_mate_selection(engine):
    board = chess.Board("r6k/Q7/8/8/8/8/8/7K b - - 0 1")
    result = engine.play(board, chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    assert result.move == chess.Move.from_uci("a8a7")
    assert result.info["score"].relative.score() == 500
    assert result.info["score"].white().score() == -500
    board = chess.Board("7k/8/5KQ1/8/8/8/8/8 w - - 99 50")
    result = engine.play(board, chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    board.push(result.move)
    assert board.is_checkmate()
    assert result.info["score"].relative.mate() == 1


@pytest.mark.parametrize("fen,mate", [
    ("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", True),
    ("7k/6Q1/5K2/8/8/8/8/8 b - - 150 76", True),
    ("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", False),
    ("7k/8/8/8/8/8/8/7K w - - 0 1", False),
    ("7k/8/8/8/8/8/R7/7K w - - 150 76", False),
])
def test_terminal_positions_have_no_move(engine, fen, mate):
    result = engine.play(chess.Board(fen), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    assert not result.move
    assert result.info["score"].relative.is_mate() == mate
    if not mate:
        assert result.info["score"].relative.score() == 0


def test_uci_position_move_stack_preserves_threefold(engine):
    board = chess.Board()
    for _ in range(2):
        for uci in ("g1f3", "g8f6", "f3g1", "f6g8"):
            board.push_uci(uci)
    result = engine.play(board, chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    assert not result.move
    assert result.info["score"].relative.score() == 0


def test_stop_and_isready_remain_responsive_during_search(protocol):
    protocol.send("setoption name AlphaBeta value false")
    protocol.send("setoption name IterativeDeepening value false")
    protocol.send("go infinite")
    protocol.send("isready")
    protocol.until("readyok", timeout=2)
    start = time.monotonic()
    protocol.send("stop")
    lines = protocol.until("bestmove", timeout=2)
    assert time.monotonic() - start < 2
    assert any(line.startswith("info depth 0 ") for line in lines)
    assert chess.Move.from_uci(lines[-1].split()[1]) in chess.Board().legal_moves


@pytest.mark.parametrize("limit", ["nodes 50", "movetime 10"])
def test_interrupted_search_is_not_reported_as_full_depth(protocol, limit):
    protocol.send("setoption name AlphaBeta value false")
    protocol.send("setoption name IterativeDeepening value false")
    protocol.send(f"go depth 8 {limit}")
    lines = protocol.until("bestmove")
    assert any(line.startswith("info depth 0 ") for line in lines)
    assert any("incomplete minimax" in line for line in lines)
    assert all("score " not in line for line in lines)


@pytest.mark.parametrize("command", [
    "position fen 8/8/8/8/8/8/8/8 w - - 0 1",
    "position startpos moves e2e4 e7e9",
    "position fen 7k/8/8/8/8/8/8/7K w - - bad 1",
    "go depth 999", "setoption name AlphaBeta value maybe",
    "setoption name IterativeDeepening value maybe",
    "setoption name MoveOrdering value maybe",
    "setoption name UsePST value maybe",
])
def test_invalid_commands_do_not_kill_engine_or_replace_position(protocol, command):
    protocol.send(command)
    protocol.until("info string error:")
    protocol.send("unknown_command")
    protocol.send("isready")
    protocol.until("readyok")
    protocol.send("go depth 1")
    lines = protocol.until("bestmove")
    assert chess.Move.from_uci(lines[-1].split()[1]) in chess.Board().legal_moves


def test_quit_during_search_exits_cleanly(protocol):
    protocol.send("go infinite")
    protocol.send("quit")
    assert protocol.process.wait(timeout=3) == 0


def test_iterative_progress_is_ordered_and_fixed_mode_has_one_pass(protocol):
    protocol.send("go depth 3")
    lines = protocol.until("bestmove")
    depths = [int(line.split()[2]) for line in lines if line.startswith("info depth ")]
    assert depths == [1, 2, 3]
    protocol.send("setoption name IterativeDeepening value false")
    protocol.send("go depth 3")
    fixed = protocol.until("bestmove")
    assert [int(line.split()[2]) for line in fixed if line.startswith("info depth ")] == [3]
    assert lines[-1] == fixed[-1]


@pytest.mark.parametrize("pruning", [False, True])
@pytest.mark.parametrize("fen", [chess.STARTING_FEN,
                                "7k/8/8/1p6/p7/Q7/8/7K w - - 0 1",
                                "7k/8/5KQ1/8/8/8/8/8 w - - 0 1"])
def test_iterative_final_result_matches_direct_search(engine, pruning, fen):
    # Preserve exact traversal/PV checks for the original unsorted baseline.
    # PV-guided sorting can choose different equally good moves between passes.
    engine.configure({"MoveOrdering": False})
    board = chess.Board(fen)
    results = []
    for iterative in (False, True):
        engine.configure({"AlphaBeta": pruning, "IterativeDeepening": iterative})
        result = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
        results.append(result)
    fixed, iterative = results
    assert iterative.move == fixed.move
    assert iterative.info["depth"] == fixed.info["depth"] == 3
    assert iterative.info["score"] == fixed.info["score"]
    assert iterative.info.get("pv") == fixed.info.get("pv")
    assert iterative.info["nodes"] >= fixed.info["nodes"]


def test_node_budget_is_shared_between_passes(engine):
    engine.configure({"AlphaBeta": False})
    result = engine.play(chess.Board(), chess.engine.Limit(depth=8, nodes=50), info=chess.engine.INFO_ALL)
    assert result.info["nodes"] == 50
    assert result.info["depth"] == 1
    assert result.info["score"].relative.score() == 0
    assert result.move == result.info["pv"][0]
    assert len(result.info["pv"]) == 1


@pytest.mark.parametrize("ordering", [False, True])
@pytest.mark.parametrize("pruning", [False, True])
@pytest.mark.parametrize("use_pst", [False, True])
def test_interrupted_deeper_pass_preserves_saved_tactical_move_score_and_pv(engine, pruning, ordering, use_pst):
    # Qxa4 wins a pawn at depth 1, but depth 2 sees ...bxa4 winning the queen.
    board = chess.Board("7k/8/8/1p6/p7/Q7/8/7K w - - 0 1")
    engine.configure({"AlphaBeta": pruning, "IterativeDeepening": False,
                      "MoveOrdering": ordering, "UsePST": use_pst})
    shallow = engine.play(board, chess.engine.Limit(depth=1), info=chess.engine.INFO_ALL)
    deep = engine.play(board, chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    assert shallow.move != deep.move
    budget = shallow.info["nodes"] + deep.info["nodes"] // 2
    engine.configure({"IterativeDeepening": True})
    interrupted = engine.play(board, chess.engine.Limit(depth=3, nodes=budget), info=chess.engine.INFO_ALL)
    assert interrupted.info["depth"] == 1
    assert interrupted.info["nodes"] == budget
    assert interrupted.move == shallow.move
    assert interrupted.info["score"] == shallow.info["score"]
    assert interrupted.info["pv"] == shallow.info["pv"]


def test_budget_before_first_completed_pass_returns_unscored_legal_fallback(engine):
    result = engine.play(chess.Board(), chess.engine.Limit(depth=8, nodes=1), info=chess.engine.INFO_ALL)
    assert result.move in chess.Board().legal_moves
    assert result.info["depth"] == 0
    assert result.info["nodes"] == 1
    assert "score" not in result.info and "pv" not in result.info


def test_stop_after_completed_depth_retains_that_result(protocol):
    protocol.send("setoption name AlphaBeta value false")
    protocol.send("go infinite")
    before = protocol.until("info depth 2 ")
    protocol.send("stop")
    after = protocol.until("bestmove")
    completed = [line for line in before + after if line.startswith("info depth ") and " score " in line]
    last = completed[-1].split()
    assert int(last[2]) >= 2
    assert after[-1] == "bestmove " + last[last.index("pv") + 1]
    assert any("incomplete minimax iterative" in line for line in after)


def test_time_budget_without_explicit_depth_keeps_deepening(engine):
    engine.configure({"AlphaBeta": False, "Depth": 1})
    start = time.monotonic()
    result = engine.play(chess.Board(), chess.engine.Limit(time=.05), info=chess.engine.INFO_ALL)
    assert time.monotonic() - start < 3
    assert 1 < result.info["depth"] < 64
    assert result.move == result.info["pv"][0]
    assert "score" in result.info
