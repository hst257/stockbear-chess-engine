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
THINKING_TIMES = (("Blitz", 100), ("Fast", 500), ("Standard", 1000),
                  ("Deep", 3000), ("Maximum", 5000))


@dataclass(frozen=True)
class EngineSettings:
    enabled: bool = False
    human_color: chess.Color = chess.WHITE
    alpha_beta: bool = True
    depth: int = 3
    iterative_deepening: bool = True
    move_ordering: bool = True
    use_pst: bool = True
    transposition_table: bool = True
    quiescence: bool = True
    principal_variation_search: bool = True
    timed_search: bool = True
    thinking_time_ms: int = 1000
    aspiration_windows: bool = True
    null_move_pruning: bool = True
    late_move_reductions: bool = True
    advanced_evaluation: bool = True
    history_heuristic: bool = True
    killer_heuristic: bool = True
    static_exchange: bool = True
    adaptive_lmr: bool = True
    reverse_futility: bool = True
    futility: bool = True
    check_extensions: bool = True
    mop_up: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.depth <= 5:
            raise ValueError("GUI search depth must be between 1 and 5 plies.")
        if self.thinking_time_ms not in dict(THINKING_TIMES).values():
            raise ValueError("Thinking time must be one of 100, 500, 1000, 3000, or 5000 ms.")

    @property
    def search_label(self) -> str:
        return f"{self.thinking_time_ms / 1000:g}s" if self.timed_search else f"depth {self.depth}"

    @property
    def algorithm(self) -> str:
        return ("PVS" if self.principal_variation_search else "Alpha-beta") if self.alpha_beta else "Minimax"


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
    complete: bool  # Fixed target reached, or a timed search has a completed answer.
    iterative_deepening: bool = True
    iterations: tuple[SearchIteration, ...] = ()
    move_ordering: bool = True
    use_pst: bool = True
    transposition_table: bool = True
    tt_hits: int = 0
    tt_cutoffs: int = 0
    hashfull: int = 0
    quiescence: bool = True
    principal_variation_search: bool = True
    qnodes: int = 0
    pvs_scouts: int = 0
    pvs_researches: int = 0
    qcaps: int = 0
    ply_limit_reached: bool = False
    timed_search: bool = False
    thinking_time_ms: int = 0
    nps: int = 0
    advanced_evaluation: bool = True


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


def table_stats(info: chess.engine.InfoDict) -> dict[str, int]:
    words = info.get("string", "").split()
    try:
        index = words.index("tt")
        pairs = words[index + 1:]
        return {key: int(value) for key, value in zip(pairs[::2], pairs[1::2])
                if key in ("probes", "hits", "cutoffs")}
    except (ValueError, TypeError):
        return {}


def search_counters(info: chess.engine.InfoDict) -> dict[str, int]:
    words = info.get("string", "").split()
    try:
        pairs = words[words.index("search") + 1:]
        return {key: int(value) for key, value in zip(pairs[::2], pairs[1::2])
                if key in ("qnodes", "scouts", "researches", "qcaps", "plylimit")}
    except (ValueError, TypeError):
        return {}


def search_stats(info: chess.engine.InfoDict, move: chess.Move | None, board: chess.Board,
                 settings: EngineSettings, pruning: bool,
                 iterations: tuple[SearchIteration, ...], counters: dict[str, int] | None = None) -> SearchStats:
    depth = info.get("depth", 0)
    score = info.get("score")
    white_score = score.white() if score else None
    score_text = "—"
    # A completed shallower pass still has a proven score when the target is missed.
    if white_score is not None and depth > 0:
        mate = white_score.mate()
        score_text = f"Mate {mate:+d}" if mate is not None else f"{white_score.score() / 100:+.2f}"
    counters = counters or {**table_stats(info), **search_counters(info)}
    algorithm = ("PVS" if settings.principal_variation_search else "Alpha-beta") if pruning else "Minimax"
    complete = depth > 0 if settings.timed_search else depth == settings.depth
    return SearchStats(algorithm, 0 if settings.timed_search else settings.depth, depth,
                       info.get("nodes", 0), info.get("time", 0.0), move,
                       board.san(move) if move else "—", score_text, complete,
                       settings.timed_search or settings.iterative_deepening, iterations, settings.move_ordering, settings.use_pst,
                       settings.transposition_table, counters.get("hits", 0), counters.get("cutoffs", 0),
                       info.get("hashfull", 0), settings.quiescence, pruning and settings.principal_variation_search,
                       counters.get("qnodes", 0), counters.get("scouts", 0), counters.get("researches", 0),
                       counters.get("qcaps", 0), bool(counters.get("plylimit", 0)),
                       settings.timed_search, settings.thinking_time_ms if settings.timed_search else 0,
                       info.get("nps", 0), settings.advanced_evaluation)


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
                if job.analysis:
                    # Schedule UCI stop; the worker drains/shuts down the process.
                    # Closing its transport here can race analysis startup and
                    # leave an unobserved python-chess exception future.
                    try:
                        job.analysis.stop()
                    except chess.engine.EngineError:
                        pass

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
                    return
                job.engine = engine
            rows = []
            modes = (False, True) if kind == "compare" else (settings.alpha_beta,)
            for pruning in modes:
                if job.canceled.is_set():
                    return
                if rows and job.stop_requested.is_set():
                    break
                engine.configure({"AlphaBeta": pruning, "IterativeDeepening": settings.timed_search or settings.iterative_deepening,
                                  "MoveOrdering": settings.move_ordering, "UsePST": settings.use_pst,
                                  "UseAdvancedEvaluation": settings.advanced_evaluation,
                                  "TranspositionTable": settings.transposition_table,
                                  "Quiescence": settings.quiescence, "PVS": settings.principal_variation_search,
                                  "UseAspirationWindows": settings.aspiration_windows,
                                  "UseNullMovePruning": settings.null_move_pruning, "UseLMR": settings.late_move_reductions,
                                  "UseHistory": settings.history_heuristic, "UseKillers": settings.killer_heuristic,
                                  "UseSEE": settings.static_exchange, "UseAdaptiveLMR": settings.adaptive_lmr,
                                  "UseReverseFutility": settings.reverse_futility, "UseFutility": settings.futility,
                                  "UseCheckExtensions": settings.check_extensions, "UseMopUp": settings.mop_up})
                if job.canceled.is_set():
                    return
                iterations: list[SearchIteration] = []
                counters: dict[str, int] = {}
                limit = (chess.engine.Limit(time=settings.thinking_time_ms / 1000) if settings.timed_search
                         else chess.engine.Limit(depth=settings.depth, time=SEARCH_SECONDS))
                with engine.analysis(board, limit,
                                     info=chess.engine.INFO_ALL) as analysis:
                    with job.lock:
                        job.analysis = analysis
                        if job.stop_requested.is_set() or job.canceled.is_set():
                            analysis.stop()
                    for info in analysis:
                        if job.canceled.is_set():
                            return
                        counters.update(table_stats(info))
                        counters.update(search_counters(info))
                        if info.get("depth", 0) <= 0:
                            continue
                        pv = info.get("pv", [])
                        progress = search_stats(info, pv[0] if pv else None, board, settings, pruning, (), counters)
                        iterations.append(SearchIteration(progress.depth, progress.nodes,
                                                          progress.seconds, progress.san, progress.score))
                        progress = search_stats(info, progress.move, board, settings, pruning, tuple(iterations), counters)
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
                counters.update(table_stats(info))
                counters.update(search_counters(info))
                rows.append(search_stats(info, move, board, settings, pruning, tuple(iterations), counters))
            if not job.canceled.is_set():
                self.messages.put(EngineMessage(job.token, revision, kind, tuple(rows)))
        except (OSError, chess.engine.EngineError, TimeoutError, RuntimeError) as error:
            if not job.canceled.is_set():
                self.messages.put(EngineMessage(job.token, revision, kind, error=str(error)))
        finally:
            if engine:
                # Shutdown on the worker, keeping the GUI responsive even if quit hangs.
                try:
                    engine.quit()
                except (chess.engine.EngineError, TimeoutError):
                    pass
                finally:
                    engine.close()

    def close(self) -> None:
        self.cancel()
