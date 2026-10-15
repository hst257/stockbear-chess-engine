"""Finalize the user's 35-game stop without treating an unpaired game as a pair."""
from datetime import datetime, timezone
import json
import shutil

import chess
import chess.pgn

from tools.match_optimizations import strength_summary
from tools.nnue_throughput import ART, ROOT, save
from tools.verify_match_records import verify_record


def main() -> None:
    output = ROOT / "validation-500ms.json"
    checkpoint = output.with_suffix(".progress.json")
    data = json.loads(checkpoint.read_text())
    assert len(data["games"]) == 35
    amendment_path = ROOT / "validation-amendment.json"
    if not amendment_path.exists():
        save(amendment_path, {"utc": datetime.now(timezone.utc).isoformat(), "original_games": 60,
            "completed_games": 35, "complete_opening_pairs": 17, "unpaired_game": 35,
            "instruction": "actually stop at 35 games, no need for 60",
            "method": "Human-requested mid-run stop. Study process tree stopped after the atomic 35-game checkpoint. Original 60-game checkpoint/plan retained; no automatic outcome-based stopping or extra completed games. Game 35 reported separately from paired uncertainty."})
    original_plan = ROOT / "validation-original-plan.json"
    if not original_plan.exists():
        shutil.copyfile(ROOT / "validation-plan.json", original_plan)
    plan = json.loads(original_plan.read_text())
    plan.update(original_games=60, games=35, opening_pairs=17, unpaired_game=35,
                method="User-amended 35-game limit: first 17 complete neutral opening pairs plus White half of pair 18. First smoke pair retained. Paired inference uses games 1–34; game 35 is separate.")
    save(ROOT / "validation-plan.json", plan)
    if not output.exists():
        data["original_requested_games"] = data["requested_games"]
        data["requested_games"] = 35
        data["incomplete_last_pair"] = True
        data["openings"] = data["openings"][:18]
        data["stop_amendment"] = json.loads(amendment_path.read_text())
        data["summary_neutral_book"] = True
        data["summary"] = strength_summary(data["games"], neutral_book=True)
        save(output, data)
        pgns = []
        for record in data["games"]:
            board = chess.Board()
            for uci in record["opening"] + [s["move"] for s in record["searches"]]:
                board.push_uci(uci)
            game = chess.pgn.Game.from_board(board)
            labels = {True: "Optimized Compact v2 NNUE", False: "Baseline Compact v2 NNUE"}
            white = record["candidate_color"] == "white"
            game.headers.update(Event="NNUE implementation throughput validation", Round=str(record["game"]),
                White=labels[white], Black=labels[not white], Result=record["result"], ThinkTimeMs="500",
                Termination=record["termination"])
            pgns.append(str(game))
        output.with_suffix(".pgn").write_text("\n\n".join(pgns) + "\n", encoding="utf-8", newline="\n")
    verified = verify_record(output, check_binaries=True)
    verified.update(complete_pairs=17, unpaired_game=35, original_checkpoint_retained=True)
    save(ROOT / "validation-replay.json", verified)
    status_path = ART / "final-status.json"
    status = json.loads(status_path.read_text())
    stage = "validation-35games-500ms"
    if stage not in status["completed"]:
        status["completed"].append(stage)
    status.update(state="complete", active=None, amended_completed_games=35,
                  stop_reason="Human-requested 35-game limit; paired analysis uses first 34 games")
    save(status_path, status)
    print("Finalized and independently replayed exactly 35 games; 17 pairs plus one unpaired game.")


if __name__ == "__main__":
    main()
