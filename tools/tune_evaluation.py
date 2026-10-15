"""Fit classical MG/EG component weights to deeper-search scores, with grouped holdout.

This is supervised calibration against a frozen engine, not an Elo measurement.
The report emits UCI settings; it never changes engine defaults automatically.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess

import chess
import chess.engine
import chess.pgn

from app.engine_client import DEFAULT_ENGINE

COMPONENTS = ("pawn_structure", "passed_pawns", "bishop_pair", "rook_activity",
              "mobility", "outposts", "king_safety", "space", "endgame")
WEIGHTS = ("Pawns", "Passers", "BishopPair", "Rooks", "Mobility", "Outposts",
           "KingSafety", "Space", "Endgame")
OPTION_NAMES = tuple(f"Weight{name}{phase}" for name in WEIGHTS for phase in ("MG", "EG"))


def truncate(numerator, denominator):
    return (1 if numerator >= 0 else -1) * (abs(numerator) // denominator)


def predict(row, weights):
    mg, eg = row["fixed"]
    for i, (mid, end) in enumerate(row["features"]):
        mg += truncate(mid * weights[2 * i], 100)
        eg += truncate(end * weights[2 * i + 1], 100)
    value = mg * row["phase"] + eg * (24 - row["phase"])
    tapered = truncate(value + (12 if value >= 0 else -12), 24)
    return truncate(tapered * row["scale"], 256)


def probability(cp):
    return 1 / (1 + math.exp(-math.log(10) * max(-4000, min(4000, cp)) / 400))


def loss(rows, weights):
    if not rows:
        raise ValueError("Training and holdout must both contain positions")
    return sum((probability(predict(r, weights)) - probability(r["target_cp"])) ** 2
               for r in rows) / len(rows)


def fit(rows):
    weights = [100] * 18
    def objective(values):
        return loss(rows, values) + .00001 * sum(((v - 100) / 100) ** 2 for v in values)
    best = objective(weights)
    for step in (20, 10, 5):
        for _ in range(5):
            changed = False
            for i in range(len(weights)):
                selected, selected_loss = weights[i], best
                for value in (weights[i] - step, weights[i] + step):
                    if not 50 <= value <= 150:
                        continue
                    trial = weights.copy()
                    trial[i] = value
                    score = objective(trial)
                    if score < selected_loss:
                        selected, selected_loss = value, score
                if selected != weights[i]:
                    weights[i], best, changed = selected, selected_loss, True
            if not changed:
                break
    return weights


def collect(args):
    rng = random.Random(args.seed)
    candidates, seen = [], set()
    with args.pgn.open(encoding="utf-8") as stream:
        game_index = 0
        while (game := chess.pgn.read_game(stream)) is not None:
            if game.errors:
                raise ValueError("Input PGN contains parse errors")
            board = game.board()
            # Consecutive color-reversed opening pairs stay in one split.
            group = game_index // 2
            for ply, move in enumerate(game.mainline_moves(), 1):
                board.push(move)
                if ply < 12 or ply % 8 or board.is_check() or board.is_game_over(claim_draw=True):
                    continue
                key = " ".join(board.fen().split()[:4])
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({"fen": board.fen(), "group": group,
                                   "split": "holdout" if group % 5 == 0 else "train"})
            game_index += 1
    rng.shuffle(candidates)
    rows = []
    with chess.engine.SimpleEngine.popen_uci(str(args.teacher), timeout=30) as teacher:
        for candidate in candidates:
            board = chess.Board(candidate["fen"])
            cp = teacher.analyse(board, chess.engine.Limit(depth=args.depth))["score"].white().score()
            if cp is None or abs(cp) > 1500:
                continue
            rows.append({**candidate, "target_cp": cp})
            if len(rows) >= args.samples:
                break
    commands = [f"setoption name {name} value 100" for name in OPTION_NAMES]
    for row in rows:
        commands.extend(("position fen " + row["fen"], "eval"))
    commands.append("quit")
    output = subprocess.run([str(args.engine)], input="\n".join(commands) + "\n", text=True,
                            capture_output=True, check=True, timeout=max(30, len(rows))).stdout
    values = [json.loads(line[len("info string eval "):]) for line in output.splitlines()
              if line.startswith("info string eval ")]
    if len(values) != len(rows):
        raise RuntimeError("Incomplete evaluation feature batch")
    for row, value in zip(rows, values):
        components = value["components"]
        row.update({"phase": value["phase"], "scale": value["scale"],
                    "fixed": [sum(components[n][phase] for n in ("material", "pst")) for phase in ("mg", "eg")],
                    "features": [[components[n][phase] for phase in ("mg", "eg")] for n in COMPONENTS]})
        assert predict(row, [100] * 18) == value["total"]
    return {"seed": args.seed, "teacher_depth": args.depth,
            "teacher_sha256": hashlib.sha256(args.teacher.read_bytes()).hexdigest(),
            "feature_engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
            "pgn_sha256": hashlib.sha256(args.pgn.read_bytes()).hexdigest(), "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--teacher", type=Path)
    parser.add_argument("--pgn", type=Path)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=800)
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261015)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new report path; existing results are immutable")
    if not args.data.exists():
        if args.teacher is None or args.pgn is None or args.samples < 20 or not 1 <= args.depth <= 8:
            parser.error("Collection needs --teacher, --pgn, >=20 samples and depth 1..8")
        data = collect(args)
        args.data.parent.mkdir(parents=True, exist_ok=True)
        args.data.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    data = json.loads(args.data.read_text(encoding="utf-8"))
    train = [r for r in data["rows"] if r["split"] == "train"]
    holdout = [r for r in data["rows"] if r["split"] == "holdout"]
    if {r["group"] for r in train} & {r["group"] for r in holdout}:
        raise ValueError("Opening pair leaked across train and holdout")
    weights = fit(train)
    report = {"method": "Bounded coordinate descent; deeper own-engine soft labels; opening-pair holdout",
              "data_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
              "train_positions": len(train), "holdout_positions": len(holdout),
              "train_before": loss(train, [100] * 18), "train_after": loss(train, weights),
              "holdout_before": loss(holdout, [100] * 18), "holdout_after": loss(holdout, weights),
              "uci_options": dict(zip(OPTION_NAMES, weights)),
              "limitations": "Own-engine targets and a small dataset; held-out loss is not playing strength. Require game tests before changing defaults."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
