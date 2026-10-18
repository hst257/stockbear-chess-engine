"""Shared deterministic rule/search fixtures for correctness checks."""

import json
import re
import time
import chess
import chess.engine

POSITIONS = {'opening': 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', 'middlegame': 'r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 7', 'tactical': 'r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1', 'endgame': '8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1', 'zugzwang': '8/3k4/3P4/3K4/8/8/8/8 w - - 0 1', 'mate': '7k/8/5KQ1/8/8/8/8/8 w - - 0 1', 'stalemate': '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1'}

PERFT = (('start', 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', [20, 400, 8902, 197281, 4865609]), ('kiwipete', 'r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1', [48, 2039, 97862, 4085603]), ('endgame_ep', '8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1', [14, 191, 2812, 43238, 674624]), ('promotions_checks', 'r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1', [6, 264, 9467, 422333]), ('underpromotion', 'rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8', [44, 1486, 62379, 2103487]), ('pins', 'r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10', [46, 2079, 89890, 3894594]))

def measure(engine, board, depth=None, ms=None, nodes=None):
    stats = {}
    profile = None
    start = time.perf_counter()
    limit = chess.engine.Limit(depth=depth, time=30, nodes=nodes) if depth else chess.engine.Limit(time=ms / 1000)
    with engine.analysis(board, limit, info=chess.engine.INFO_ALL) as analysis:
        for info in analysis:
            if info.get("string", "").startswith("profile "):
                profile = json.loads(info["string"][8:])
            stats.update({k: int(v) for k, v in re.findall(r"\b([a-z_]+)\s+(\d+)\b", info.get("string", ""))})
        result = analysis.wait()
        info = analysis.info
    wall = time.perf_counter() - start
    assert result.move in board.legal_moves if result.move else board.is_game_over(claim_draw=True)
    if depth and not nodes:
        assert info["depth"] == depth
    elif not depth:
        assert wall < ms / 1000 + 2
    replay = board.copy()
    for move in info.get("pv", []):
        assert move in replay.legal_moves
        replay.push(move)
    return {"depth": info["depth"], "nodes": info["nodes"], "qnodes": stats.get("qnodes"),
            "seconds": info["time"], "wall_seconds": wall, "nps": info["nps"],
            "score": str(info["score"].white()) if "score" in info else None, "move": result.move.uci() if result.move else "0000",
            "profile": profile, "pv": [m.uci() for m in info.get("pv", [])], "counters": stats,
            "tt_hit_rate": stats.get("hits", 0) / max(1, stats.get("probes", 0))}

def counters(info):
    words = info.get("string", "").split()
    if "optim" not in words:
        return {}
    pairs = words[words.index("optim") + 1:]
    return {k: int(v) for k, v in zip(pairs[::2], pairs[1::2])}
