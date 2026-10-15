"""Independently replay paired-match JSON and PGN records and recompute outcomes."""
import argparse
import hashlib
import io
import json
from pathlib import Path

import chess
import chess.pgn

from tools.match_optimizations import strength_summary


def verify_record(path: Path, check_binaries=False):
    data = json.loads(path.read_text(encoding="utf-8"))
    source = io.StringIO(path.with_suffix(".pgn").read_text(encoding="utf-8"))
    assert len(data["games"]) == data["requested_games"]
    partial_pair = bool(data.get("incomplete_last_pair", False))
    assert not partial_pair or len(data["games"]) % 2 == 1
    assert len(data["openings"]) == (len(data["games"]) + int(partial_pair)) // 2
    assert len({p["fen"] for p in data["openings"]}) == len(data["openings"])
    plies = 0
    for index, record in enumerate(data["games"]):
        game = chess.pgn.read_game(source)
        assert game is not None and not game.errors
        expected = record["opening"] + [s["move"] for s in record["searches"]]
        assert [m.uci() for m in game.mainline_moves()] == expected
        assert record["game"] == index + 1 and record["pair"] == index // 2 + 1
        assert record["opening"] == data["openings"][index // 2]["moves"]
        assert record["candidate_color"] == ("white" if index % 2 == 0 else "black")
        board = chess.Board()
        for uci in record["opening"]:
            board.push_uci(uci)
        for search in record["searches"]:
            assert search["candidate"] == (board.turn == (record["candidate_color"] == "white"))
            board.push_uci(search["move"])
        assert len(board.move_stack) == record["plies"]
        plies += len(board.move_stack)
        outcome = board.outcome(claim_draw=True)
        result = outcome.result() if outcome else "*"
        assert game.headers["Result"] == record["result"] == result
        label = ("unfinished" if outcome is None else "draw" if outcome.winner is None else
                 "win" if outcome.winner == (record["candidate_color"] == "white") else "loss")
        assert label == record["candidate_outcome"]
        if outcome is None:
            assert len(record["searches"]) == data["max_plies"]
        else:
            assert record["termination"] == outcome.termination.name.lower()
    assert chess.pgn.read_game(source) is None
    assert data["summary"] == strength_summary(data["games"], neutral_book=data.get("summary_neutral_book", False))
    if check_binaries:
        for label, binary in data["paths"].items():
            assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == data["hashes"][label]
    return {"record": str(path), "games": len(data["games"]), "legal_plies": plies,
            "paired_openings_colors_and_results": True, "summary_recomputed": True,
            "binary_hashes_checked": check_binaries, "declared_hashes": data["hashes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check-binaries", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh verification report path")
    report = {"checks": [verify_record(path, args.check_binaries) for path in args.records]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
