"""Cancelable UCI work off the Pygame thread. Workers never mutate a Game."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import queue
import subprocess
import threading

import chess
import chess.engine

DEFAULT_ENGINE = (Path(__file__).resolve().parents[1] / "engine" / "build" /
                  ("chesslab-engine.exe" if os.name == "nt" else "chesslab-engine"))
SEARCH_SECONDS = 15.0


@dataclass(frozen=True)
class EngineSettings:
    enabled: bool = False
    human_color: chess.Color = chess.WHITE
    alpha_beta: bool = True
    depth: int = 3
    iterative_deepening: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.depth <= 5:
            raise ValueError("GUI search depth must be between 1 and 5 plies.")

    @property
    def algorithm(self) -> str:
        return "Alpha-beta" if self.alpha_beta else "Minimax"


@dataclass(frozen=True)
class SearchIteration:
    """One completed pass; nodes/time are cumulative from the search start."""
    depth: int
    nodes: int
    seconds: float
    san: str
    score: str


@dataclass(frozen=True)
class SearchStats:
    algorithm: str
    requested_depth: int
    depth: int
    nodes: int
    seconds: float
    move: chess.Move | None
    san: str
    score: str
    complete: bool  # Target reached; a shallower completed pass can still be valid.
    iterative_deepening: bool = True
    iterations: tuple[SearchIteration, ...] = ()


@dataclass(frozen=True)
class EngineMessage:
    token: int
    revision: int
    kind: str
    stats: tuple[SearchStats, ...] = ()
    error: str = ""
    finished: bool = True  # Progress must never trigger move application.


@dataclass
class _Job:
    token: int
    canceled: threading.Event = field(default_factory=threading.Event)
    stop_requested: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    engine: chess.engine.SimpleEngine | None = None
    analysis: chess.engine.SimpleAnalysisResult | None = None


def search_stats(info: chess.engine.InfoDict, move: chess.Move | None, board: chess.Board,
                 settings: EngineSettings, pruning: bool,
                 iterations: tuple[SearchIteration, ...]) -> SearchStats:
    depth = info.get("depth", 0)
    score = info.get("score")
    white_score = score.white() if score else None
    score_text = "—"
    # A completed shallower pass still has a proven score when the target is missed.
    if white_score is not None and depth > 0:
        mate = white_score.mate()
        score_text = f"Mate {mate:+d}" if mate is not None else f"{white_score.score() / 100:+.2f}"
    return SearchStats("Alpha-beta" if pruning else "Minimax", settings.depth, depth,
                       info.get("nodes", 0), info.get("time", 0.0), move,
                       board.san(move) if move else "—", score_text, depth == settings.depth,
                       settings.iterative_deepening, iterations)


class EngineClient:
    def __init__(self, path: Path = DEFAULT_ENGINE) -> None:
        self.path = Path(path)
        self.messages: queue.Queue[EngineMessage] = queue.Queue()
        self._token = 0
        self._job: _Job | None = None

    @property
    def busy(self) -> bool:
        return self._job is not None

    def cancel(self) -> None:
        self._token += 1
        job, self._job = self._job, None
        if job:
            job.canceled.set()
            with job.lock:
                if job.engine:
                    # close() schedules transport shutdown; it does not wait for search.
                    job.engine.close()

    def start(self, board: chess.Board, revision: int, settings: EngineSettings,
              kind: str = "play") -> int:
        self.cancel()
        job = _Job(self._token)
        self._job = job
        snapshot = board.copy(stack=True)
        threading.Thread(target=self._work, args=(job, snapshot, revision, settings, kind),
                         name="ChessLab-UCI", daemon=True).start()
        return job.token

    def stop(self) -> None:
        """Stop gracefully and retain the engine's last completed iteration."""
        job = self._job
        if job:
            job.stop_requested.set()
            with job.lock:
                if job.analysis:
                    job.analysis.stop()

    def poll(self) -> list[EngineMessage]:
        messages = []
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            if message.token == self._token:
                if message.finished:
                    self._job = None
                messages.append(message)
        return messages

    def _work(self, job: _Job, board: chess.Board, revision: int,
              settings: EngineSettings, kind: str) -> None:
        engine = None
        try:
            if not self.path.is_file():
                raise FileNotFoundError("Engine not built. Run build_engine.bat, then retry.")
            flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            engine = chess.engine.SimpleEngine.popen_uci(str(self.path), timeout=5, **flags)
            with job.lock:
                if job.canceled.is_set():
                    engine.close()
                    return
                job.engine = engine
            rows = []
            modes = (False, True) if kind == "compare" else (settings.alpha_beta,)
            for pruning in modes:
                if job.canceled.is_set():
                    return
                if rows and job.stop_requested.is_set():
                    break
                engine.configure({"AlphaBeta": pruning, "IterativeDeepening": settings.iterative_deepening})
                iterations: list[SearchIteration] = []
                with engine.analysis(board, chess.engine.Limit(depth=settings.depth, time=SEARCH_SECONDS),
                                     info=chess.engine.INFO_ALL) as analysis:
                    with job.lock:
                        job.analysis = analysis
                        if job.stop_requested.is_set():
                            analysis.stop()
                    for info in analysis:
                        if job.canceled.is_set():
                            return
                        if info.get("depth", 0) <= 0:
                            continue
                        pv = info.get("pv", [])
                        progress = search_stats(info, pv[0] if pv else None, board, settings, pruning, ())
                        iterations.append(SearchIteration(progress.depth, progress.nodes,
                                                          progress.seconds, progress.san, progress.score))
                        progress = search_stats(info, progress.move, board, settings, pruning, tuple(iterations))
                        self.messages.put(EngineMessage(job.token, revision, kind,
                                                        (*rows, progress), finished=False))
                    result = analysis.wait()
                    info = analysis.info.copy()
                with job.lock:
                    job.analysis = None
                # python-chess represents UCI bestmove 0000 as a falsey null Move.
                move = result.move if result.move else None
                if move is not None and move not in board.legal_moves:
                    raise RuntimeError("Engine returned an illegal move; game unchanged.")
                rows.append(search_stats(info, move, board, settings, pruning, tuple(iterations)))
            if not job.canceled.is_set():
                self.messages.put(EngineMessage(job.token, revision, kind, tuple(rows)))
        except (OSError, chess.engine.EngineError, TimeoutError, RuntimeError) as error:
            if not job.canceled.is_set():
                self.messages.put(EngineMessage(job.token, revision, kind, error=str(error)))
        finally:
            if engine:
                # Shutdown on the worker, keeping the GUI responsive even if quit hangs.
                try:
                    if not job.canceled.is_set():
                        engine.quit()
                except (chess.engine.EngineError, TimeoutError):
                    pass
                finally:
                    engine.close()

    def close(self) -> None:
        self.cancel()
