import os

# Set before importing Pygame, so CI never opens windows or audio devices.
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import chess.engine
import pytest

from app.engine_client import DEFAULT_ENGINE


@pytest.fixture(scope="session")
def engine_path():
    assert DEFAULT_ENGINE.is_file(), "Build the C++ engine first: run build_engine.bat"
    return DEFAULT_ENGINE


@pytest.fixture
def engine(engine_path):
    with chess.engine.SimpleEngine.popen_uci(str(engine_path), timeout=3) as instance:
        # Preserve the legacy material/search baselines. PST tests opt in;
        # a separate fresh-process check verifies the default is actually on.
        instance.configure({"UsePST": False, "TranspositionTable": False, "Quiescence": False, "PVS": False, "UseAspirationWindows": False, "UseNullMovePruning": False, "UseLMR": False})
        yield instance
