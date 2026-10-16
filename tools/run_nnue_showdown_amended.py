"""Resume only the user-approved 500 ms / 1 second showdown prefix."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import statistics

from tools import nnue_showdown as core


def scope(root: Path) -> tuple[dict, list[dict], list[dict]]:
    plan = core.load(root / "plan.json")
    amendment = core.load(root / "schedule-amendment.json")
    if amendment["original_plan_sha256"] != core.sha(root / "plan.json"):
        raise ValueError("Amendment does not match frozen plan")
    allowed = [g for g in plan["schedule"] if g["ms"] in (500, 1000)]
    if len(allowed) != amendment["planned_games"] or len(allowed) != 108 or allowed != plan["schedule"][:108]:
        raise ValueError("Amended schedule is not the frozen 108-game prefix")
    expected = {g["id"]: g for g in allowed}
    rows = core.records(root)
    for row in rows:
        if row["game"] != expected.get(row["game"]["id"]) or row["plan_sha256"] != core.sha(root / "plan.json"):
            raise ValueError("Completed game outside amended schedule or identity mismatch")
    for path in (root / "games").glob("*.partial.json"):
        if core.load(path)["game"] != expected.get(path.name.split(".")[0]):
            raise ValueError("Checkpoint outside amended schedule")
    if (root / "finalists.json").exists():
        raise ValueError("Unexpected longer-control finalist schedule")
    return plan, allowed, rows


def progress(root: Path, plan: dict | None = None) -> dict:
    plan, allowed, rows = scope(root)
    done = {r["game"]["id"] for r in rows}
    remaining = [g for g in allowed if g["id"] not in done]
    estimate = 0.
    for game in remaining:
        sample = [len(r["searches"]) for r in rows if r["game"]["ms"] == game["ms"]]
        sample = sample or [len(r["searches"]) for r in rows]
        estimate += (statistics.mean(sample) if sample else 100) * (game["ms"] / 1000 + .002)
    standings = core.standings(rows)
    for row in standings:
        row["formats"].pop("3000", None)
        scores = [row["formats"][str(ms)]["score_fraction"] for ms in (500, 1000)]
        row["equal_format_score"] = statistics.mean(scores) if None not in scores else None
    elapsed = (datetime.fromisoformat(core.utc()) - min(datetime.fromisoformat(r["started_utc"]) for r in rows)).total_seconds() if rows else 0
    value = {"updated_utc": core.utc(), "planned_games": 108, "completed_games": len(rows),
             "remaining_games": len(remaining), "estimated_remaining_seconds": estimate,
             "elapsed_wall_seconds": elapsed,
             "eta_note": "Measured game lengths by control plus measured-scale protocol overhead; no longer controls",
             "failures": len(list((root / "failures").glob("*.json"))), "standings": standings,
             "original_plan_sha256": core.sha(root / "plan.json"),
             "amendment_sha256": core.sha(root / "schedule-amendment.json")}
    core.save(root / "scoreboard.json", value)
    return value


def run(root: Path) -> None:
    _, allowed, rows = scope(root)
    remaining = len(allowed) - len(rows)
    if remaining:
        # Keep the signed core source and game identities intact. Only the
        # derived progress publisher and explicit new-game limit are adapted.
        original = core.publish_progress
        core.publish_progress = progress
        try:
            core.run(root, resume=True, max_new=remaining)
        finally:
            core.publish_progress = original
    progress(root)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "progress"))
    parser.add_argument("--root", type=Path, default=core.DEFAULT_ROOT)
    args = parser.parse_args()
    if args.action == "run":
        run(args.root.resolve())
    else:
        import json
        print(json.dumps(progress(args.root.resolve()), indent=2))


if __name__ == "__main__":
    main()
