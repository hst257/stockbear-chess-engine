"""Color-balanced baseline/advanced smoke games; not an Elo estimate."""
import argparse
from contextlib import ExitStack
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import subprocess
import time
import errno

import chess
import chess.engine
import chess.pgn

from app.engine_client import DEFAULT_ENGINE
from tools.benchmark_optimizations import configure_stage

OPENINGS = ((), ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"),
            ("d2d4", "d7d5", "c2c4", "e7e6"), ("e2e4", "c7c5", "g1f3", "d7d6"))


def write_record(path, text):
    """Keep the previous complete record intact across transient Windows locks."""
    temporary = path.with_name(path.name + ".tmp")
    for attempt in range(20):
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            return
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EBUSY, errno.EINVAL, errno.EPERM) or attempt == 19:
                raise
            time.sleep(.1)


def strength_summary(records, *, neutral_book=False):
    counts = Counter(r["candidate_outcome"] for r in records)
    completed = counts["win"] + counts["draw"] + counts["loss"]
    score = (counts["win"] + .5 * counts["draw"]) / completed if completed else None
    pairs = []
    for i in range(0, len(records) - 1, 2):
        outcomes = [r["candidate_outcome"] for r in records[i:i + 2]]
        if "unfinished" not in outcomes:
            pairs.append(sum({"win": 1, "draw": .5, "loss": 0}[r] for r in outcomes) / 2)
    pair_score = sum(pairs) / len(pairs) if pairs else None
    # Conservative bound for bounded [0,1] pair scores, keeping colors together.
    margin = math.sqrt(math.log(40) / (2 * len(pairs))) if pairs else None
    interval = [max(0, pair_score - margin), min(1, pair_score + margin)] if pairs else [None, None]
    def rating(s):
        return 400 * math.log10(s / (1 - s)) if s is not None and 0 < s < 1 else None
    return {"wins": counts["win"], "draws": counts["draw"], "losses": counts["loss"],
            "unfinished": counts["unfinished"], "completed_games": completed,
            "score_percent": score * 100 if score is not None else None,
            "rating_difference_estimate": rating(score), "complete_pairs": len(pairs),
            "paired_score": pair_score, "paired_score_95_bound": interval,
            "paired_rating_95_bound": [rating(s) for s in interval],
            "uncertainty_method": "Hoeffding bounded pair-score 95% interval; nominal independent opening pairs",
            "limitations": ("Frozen evaluator-neutral opening book; capped pairs excluded from complete-pair inference; no universal Elo claim. Null rating endpoints mean unbounded tails."
                            if neutral_book else "Fast time control; own-evaluator opening filter; capped pairs excluded; no universal Elo claim. Null rating endpoints mean unbounded tails.")}


def version_match(args):
    if args.opponent is None:
        raise ValueError("--comparison versions requires --opponent ORIGINAL_EXECUTABLE")
    if args.output.exists():
        raise ValueError("Refusing to overwrite a completed match record")
    progress = args.output.with_suffix(".progress.json")
    hashes = {"candidate": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
              "original": hashlib.sha256(args.opponent.read_bytes()).hexdigest()}
    book_path = getattr(args, "opening_book", None)
    book_hash = hashlib.sha256(book_path.read_bytes()).hexdigest() if book_path else None
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with ExitStack() as stack:
        candidate = stack.enter_context(chess.engine.SimpleEngine.popen_uci(str(args.engine), timeout=10, **flags))
        original = stack.enter_context(chess.engine.SimpleEngine.popen_uci(str(args.opponent), timeout=10, **flags))
        overrides = {}
        for label, player, path in (("candidate", candidate, args.candidate_options),
                                    ("original", original, args.opponent_options)):
            config = json.loads(path.read_text(encoding="utf-8")) if path else {}
            config = config.get("uci_options", config)
            player.configure(config)
            overrides[label] = config
        if args.resume:
            data = json.loads(progress.read_text(encoding="utf-8"))
            assert data["hashes"] == hashes and data["requested_games"] == args.games
            assert data["movetime_ms"] == args.movetime and data["max_plies"] == args.max_plies
            assert data.get("overrides", {"candidate": {}, "original": {}}) == overrides
            assert data.get("opening_book_sha256") == book_hash
        else:
            if progress.exists():
                raise ValueError("Progress exists; use --resume or choose another output")
            rng = random.Random(args.seed)
            suite, seen = [], set()
            attempts = 0
            if book_path:
                book = json.loads(book_path.read_text(encoding="utf-8"))
                suite = book["openings"][:args.games // 2]
                if len(suite) != args.games // 2:
                    raise ValueError("Opening book has too few unique pairs")
                for opening in suite:
                    board = chess.Board()
                    for uci in opening["moves"]:
                        board.push_uci(uci)
                    assert board.fen() == opening["fen"] and not board.is_game_over(claim_draw=True)
                assert len({o["fen"] for o in suite}) == len(suite)
            while len(suite) < args.games // 2:
                attempts += 1
                if attempts > args.games * 200:
                    raise RuntimeError("Could not construct enough unique filtered opening pairs")
                board = chess.Board()
                base = OPENINGS[len(suite) % len(OPENINGS)]
                for uci in base:
                    board.push_uci(uci)
                for _ in range(rng.choice((4, 6, 8))):
                    quiet = [m for m in board.legal_moves if not board.is_capture(m) and not board.gives_check(m)]
                    if not quiet:
                        break
                    board.push(rng.choice(quiet))
                key = " ".join(board.fen().split()[:4])
                if key in seen or board.is_game_over(claim_draw=True):
                    continue
                info = original.analyse(board, chess.engine.Limit(depth=3))
                score = info["score"].white().score()
                if score is None or abs(score) > 80:
                    continue
                seen.add(key)
                suite.append({"moves": [m.uci() for m in board.move_stack], "fen": board.fen(),
                              "baseline_depth3_cp": score, "parent_opening": len(suite) % len(OPENINGS)})
            data = {"generated_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
                    "comparison": "candidate versus original executables/options", "hashes": hashes,
                    "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                    "options": {"candidate": {n: o.default for n, o in candidate.options.items()},
                                "original": {n: o.default for n, o in original.options.items()}},
                    "overrides": overrides,
                    "builds": {label: json.loads(path.with_suffix(".build.json").read_text())
                               if path.with_suffix(".build.json").exists() else None
                               for label, path in (("candidate", args.engine), ("original", args.opponent))},
                    "paths": {"candidate": str(args.engine), "original": str(args.opponent)},
                    "names": {"candidate": candidate.id, "original": original.id},
                    "requested_games": args.games, "movetime_ms": args.movetime, "max_plies": args.max_plies,
                    "seed": args.seed, "opening_filter": "Seeded noncapture/noncheck continuations of four named openings; original depth3 |cp| <=80; heuristic balance only",
                    "opening_book_sha256": book_hash,
                    "openings": suite, "games": []}
            if book_path:
                data["opening_filter"] = book["method"]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        session_games = 0
        for index in range(len(data["games"]), args.games):
            game_started = time.perf_counter()
            board = chess.Board()
            opening = data["openings"][index // 2]
            for uci in opening["moves"]:
                board.push_uci(uci)
            candidate_color = index % 2 == 0
            searches = []
            for _ in range(args.max_plies):
                if board.is_game_over(claim_draw=True):
                    break
                optimized = board.turn == candidate_color
                player = candidate if optimized else original
                move_started = time.perf_counter()
                result = player.play(board, chess.engine.Limit(time=args.movetime / 1000),
                                     game=index, info=chess.engine.INFO_ALL)
                wall_seconds = time.perf_counter() - move_started
                assert result.move in board.legal_moves
                searches.append({"candidate": optimized, "move": result.move.uci(),
                                 "depth": result.info.get("depth", 0), "nodes": result.info["nodes"],
                                 "seconds": result.info["time"], "wall_seconds": wall_seconds,
                                 "nps": result.info["nps"],
                                 "score_white": str(result.info["score"].white()) if "score" in result.info else None})
                board.push(result.move)
            outcome = board.outcome(claim_draw=True)
            record = {"game": index + 1, "pair": index // 2 + 1, "opening": opening["moves"],
                      "candidate_color": "white" if candidate_color else "black",
                      "result": outcome.result() if outcome else "*",
                      "termination": outcome.termination.name.lower() if outcome else "ply cap (unfinished)",
                      "candidate_outcome": "unfinished" if outcome is None else "draw" if outcome.winner is None else
                                           "win" if outcome.winner == candidate_color else "loss",
                      "plies": len(board.move_stack), "wall_seconds": time.perf_counter() - game_started,
                      "searches": searches}
            data["games"].append(record)
            write_record(progress, json.dumps(data, indent=2) + "\n")
            print(f"Game {index + 1}/{args.games}: candidate {record['candidate_color']} {record['result']} "
                  f"({record['candidate_outcome']}, {record['plies']} plies)", flush=True)
            session_games += 1
            if getattr(args, "max_new_games", None) and session_games >= args.max_new_games and index + 1 < args.games:
                print("Pilot/checkpoint complete; resume the unchanged scheduled cohort with --resume", flush=True)
                return
    data["summary_neutral_book"] = bool(book_path)
    data["summary"] = strength_summary(data["games"], neutral_book=bool(book_path))
    write_record(args.output, json.dumps(data, indent=2) + "\n")
    games = []
    evaluator_match = any("Evaluator" in options for options in overrides.values())
    labels = {label: {"nnue": "StockBear NNUE", "classical": "StockBear Classical"}.get(
              options.get("Evaluator"), "Optimized" if label == "candidate" else "Original")
              for label, options in overrides.items()}
    for label, options in overrides.items():
        build = data.get("builds", {}).get(label) or {}
        if options.get("Evaluator") == "nnue" and build.get("nnue"):
            labels[label] += " " + Path(build["nnue"]["model"]).stem + " (" + options.get("NNUEKernel", "auto") + ")"
    for record in data["games"]:
        board = chess.Board()
        for uci in record["opening"] + [s["move"] for s in record["searches"]]:
            board.push_uci(uci)
        game = chess.pgn.Game.from_board(board)
        game.headers.update({"Event": "NNUE versus classical evaluator match" if evaluator_match else "Original versus optimized audit match", "Round": str(record["game"]),
                             "White": labels["candidate"] if record["candidate_color"] == "white" else labels["original"],
                             "Black": labels["original"] if record["candidate_color"] == "white" else labels["candidate"],
                             "Result": record["result"], "ThinkTimeMs": str(args.movetime),
                             "Termination": record["termination"]})
        games.append(str(game))
    write_record(args.output.with_suffix(".pgn"), "\n\n".join(games) + "\n")
    progress.unlink()
    print(json.dumps(data["summary"], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--comparison", choices=("search", "evaluation", "versions"), default="search",
                        help="Compare search stages or baseline/advanced evaluation.")
    parser.add_argument("--games", type=int, default=4)
    parser.add_argument("--movetime", type=int, default=100)
    parser.add_argument("--opponent", type=Path)
    parser.add_argument("--candidate-options", type=Path, help="JSON UCI options or a tuning report with uci_options.")
    parser.add_argument("--opponent-options", type=Path)
    parser.add_argument("--opening-book", type=Path, help="Frozen shared JSON openings; bypass per-opponent filtering.")
    parser.add_argument("--seed", type=int, default=20261015)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-new-games", type=int, help="Pause after this many new games, preserving the full schedule for --resume.")
    parser.add_argument("--max-plies", type=int, default=160)
    parser.add_argument("--output", type=Path, default=Path("artifacts/optimization-matches.json"))
    args = parser.parse_args()
    if args.max_plies < 1 or args.games < 2 or args.games % 2 or args.movetime < 1 or (args.max_new_games is not None and args.max_new_games < 1):
        parser.error("Use positive time/plies and a positive even game count")
    if args.comparison == "versions":
        version_match(args)
        return
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    records, pgns = [], []
    options = {"AlphaBeta": True, "IterativeDeepening": True, "MoveOrdering": True, "UseAdvancedEvaluation": False, "UsePST": True,
               "TranspositionTable": True, "Hash": 16, "PVS": True, "Quiescence": True, "AspirationDelta": 25, "LMRReduction": 1}
    with chess.engine.SimpleEngine.popen_uci(str(args.engine), timeout=10, **flags) as engine:
        engine.configure(options)
        for index in range(args.games):
            board = chess.Board()
            opening = OPENINGS[(index // 2) % len(OPENINGS)]
            for uci in opening:
                board.push_uci(uci)
            advanced_color = index % 2 == 0
            searches = []
            for _ in range(args.max_plies):
                if board.is_game_over(claim_draw=True):
                    break
                advanced = board.turn == advanced_color
                configure_stage(engine, 3 if args.comparison == "evaluation" or advanced else 0)
                engine.configure({"UseAdvancedEvaluation": advanced if args.comparison == "evaluation" else False})
                result = engine.play(board, chess.engine.Limit(time=args.movetime / 1000), info=chess.engine.INFO_ALL)
                assert result.move in board.legal_moves
                searches.append({"advanced": advanced, "move": result.move.uci(),
                                 "depth": result.info.get("depth", 0), "nodes": result.info["nodes"],
                                 "seconds": result.info["time"]})
                board.push(result.move)
            outcome = board.outcome(claim_draw=True)
            result_text = outcome.result() if outcome else "*"
            record = {"game": index + 1, "opening": list(opening),
                      "advanced_color": "white" if advanced_color else "black", "result": result_text,
                      "termination": outcome.termination.name.lower() if outcome else "ply cap (unfinished)",
                      "advanced_outcome": "unfinished" if outcome is None else "draw" if outcome.winner is None else
                                          "win" if outcome.winner == advanced_color else "loss",
                      "plies": len(board.move_stack), "searches": searches}
            records.append(record)
            game = chess.pgn.Game.from_board(board)
            game.headers.update({"Event": f"{args.comparison.title()} smoke match", "White": "Advanced" if advanced_color else "Baseline",
                                 "Black": "Baseline" if advanced_color else "Advanced", "Result": result_text,
                                 "ThinkTimeMs": str(args.movetime), "Termination": record["termination"]})
            pgns.append(str(game))
            print(f"Game {index + 1}: advanced {record['advanced_color']} {result_text} "
                  f"({record['advanced_outcome']}; {record['termination']}; {record['plies']} plies)", flush=True)
        data = {"generated_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
                "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
                "settings": options, "comparison": args.comparison, "movetime_ms": args.movetime,
                "search_stage": "3 for both" if args.comparison == "evaluation" else "0 vs 3",
                "max_plies": args.max_plies, "games": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_record(args.output, json.dumps(data, indent=2) + "\n")
    write_record(args.output.with_suffix(".pgn"), "\n\n".join(pgns) + "\n")
    print(f"Saved {args.output} and PGNs. Tiny samples establish no reliable Elo gain.")


if __name__ == "__main__":
    main()
