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

    def __post_init__(self) -> None:
        if not 1 <= self.depth <= 5:
            raise ValueError("GUI search depth must be between 1 and 5 plies.")

    @property
    def algorithm(self) -> str:
        return "Alpha-beta" if self.alpha_beta else "Minimax"


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
    complete: bool


@dataclass(frozen=True)
class EngineMessage:
    token: int
    revision: int
    kind: str
    stats: tuple[SearchStats, ...] = ()
    error: str = ""


@dataclass
class _Job:
    token: int
    canceled: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    engine: chess.engine.SimpleEngine | None = None


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

    def poll(self) -> list[EngineMessage]:
        messages = []
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            if message.token == self._token:
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
                engine.configure({"AlphaBeta": pruning})
                result = engine.play(board, chess.engine.Limit(depth=settings.depth, time=SEARCH_SECONDS),
                                     info=chess.engine.INFO_ALL)
                info = result.info
                # python-chess represents UCI bestmove 0000 as a falsey null Move.
                move = result.move if result.move else None
                if move is not None and move not in board.legal_moves:
                    raise RuntimeError("Engine returned an illegal move; game unchanged.")
                complete = info.get("depth", 0) == settings.depth
                score = info.get("score")
                # Display from White's perspective, regardless of engine color.
                white_score = score.white() if score else None
                score_text = "—"
                if white_score is not None and complete:
                    mate = white_score.mate()
                    score_text = f"Mate {mate:+d}" if mate is not None else f"{white_score.score() / 100:+.2f}"
                rows.append(SearchStats("Alpha-beta" if pruning else "Minimax", settings.depth,
                                        info.get("depth", 0), info.get("nodes", 0),
                                        info.get("time", 0.0), move,
                                        board.san(move) if move else "—",
                                        score_text, complete))
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
