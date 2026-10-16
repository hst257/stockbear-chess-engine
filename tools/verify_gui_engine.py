"""Exercise real UCI workers through the Pygame app without desktop input."""
import json
import argparse
import os
from pathlib import Path
import statistics
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import chess
import pygame

from app.application import Application
from app.engine_client import DEFAULT_ENGINE, EngineSettings, THINKING_TIMES


def drain(app, seconds=10):
    frames, jobs = [], []
    deadline = time.monotonic() + seconds
    while app.engine.busy:
        job = app.engine._job
        if job and job not in jobs:
            jobs.append(job)
        start = time.perf_counter()
        for event in pygame.event.get():
            app.handle_event(event)
        app.update_engine()
        app.draw()
        pygame.display.flip()
        frames.append((time.perf_counter() - start) * 1000)
        assert time.monotonic() < deadline, "GUI worker watchdog expired"
        time.sleep(.002)
    assert not app.engine_error, app.engine_error
    return frames, jobs


def timings(frames):
    ordered = sorted(frames)
    return {"frames": len(frames), "median_ms": statistics.median(frames),
            "p95_ms": ordered[int((len(ordered) - 1) * .95)],
            "p99_ms": ordered[int((len(ordered) - 1) * .99)], "maximum_ms": max(frames)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/audit"))
    parser.add_argument("--evaluator", choices=("classical", "nnue", "nnue_v3"), default="classical")
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    report = {"method": "SDL dummy driver; real Pygame app and UCI subprocesses; not desktop interaction",
              "evaluator": args.evaluator,
              "engine": str(args.engine.resolve()),
              "budgets": []}
    all_jobs = []
    for _, ms in THINKING_TIMES:
        app = Application(settings=EngineSettings(enabled=True, thinking_time_ms=ms, evaluator=args.evaluator), engine_path=args.engine)
        try:
            for _ in range(5):
                app.draw()
            assert app.game.play(chess.Move.from_uci("e2e4"))
            app.update_engine()
            frames, jobs = drain(app, ms / 1000 + 5)
            all_jobs += jobs
            assert len(app.game.board.move_stack) == 2 and app.last_play_stats.advanced_evaluation
            replay = chess.Board()
            for move in app.game.board.move_stack:
                assert move in replay.legal_moves
                replay.push(move)
            row = {"budget_ms": ms, "completed_depth": app.last_play_stats.depth, **timings(frames)}
            assert row["p99_ms"] < 100, row
            report["budgets"].append(row)
            if ms == 1000:
                pygame.image.save(app.surface, output / "gui-default.png")
        finally:
            app.close()
    app = Application(size=(960, 680), settings=EngineSettings(enabled=True, evaluator=args.evaluator), engine_path=args.engine)
    try:
        for action in ("undo", "new"):
            assert app.game.play(chess.Move.from_uci("e2e4"))
            app.update_engine()
            all_jobs.append(app.engine._job)
            app.action(action)
            deadline = time.monotonic() + .15
            while time.monotonic() < deadline:
                app.update_engine()
                app.draw()
                time.sleep(.005)
            assert app.game.board.fen() == chess.STARTING_FEN and not app.engine.busy
        app.action("diagnostics")
        before = app.game.board.fen()
        app.start_search("compare")
        frames, jobs = drain(app, 6)
        all_jobs += jobs
        assert len(app.search_rows) == 2 and app.game.board.fen() == before
        assert all(row.advanced_evaluation and row.move in app.game.board.legal_moves for row in app.search_rows)
        report["comparison"] = {"depths": [row.depth for row in app.search_rows], **timings(frames)}
        report["undo_and_new_reject_stale_moves"] = True
        pygame.image.save(app.surface, output / "gui-minimum.png")
    finally:
        app.close()
    codes = [job.engine.returncode.result(timeout=5) for job in all_jobs if job and job.engine]
    assert all(code == 0 for code in codes), codes
    report["worker_exit_codes"] = codes
    (output / "gui-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
