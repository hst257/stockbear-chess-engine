import os
from pathlib import Path

# Set before importing Pygame, so CI never opens windows or audio devices.
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import chess.engine
import pytest

from app.engine_client import DEFAULT_ENGINE


@pytest.fixture(scope="session")
def engine_path():
    path = Path(os.environ.get("CHESSLAB_TEST_ENGINE", str(DEFAULT_ENGINE)))
    assert path.is_file(), "Build the C++ engine first: run build_engine.bat"
    return path


@pytest.fixture
def engine(engine_path):
    with chess.engine.SimpleEngine.popen_uci(str(engine_path), timeout=3) as instance:
        # Preserve historical material/search baselines. Evaluation tests opt in;
        # fresh-process tests verify the production defaults independently.
        instance.configure({"UseAdvancedEvaluation": False, "UsePST": False, "TranspositionTable": False, "Quiescence": False, "PVS": False, "UseAspirationWindows": False, "UseNullMovePruning": False, "UseLMR": False})
        instance.configure({'UseHistory': False, 'UseKillers': False, 'UseSEE': False, 'UseAdaptiveLMR': False, 'UseReverseFutility': False, 'UseFutility': False, 'UseCheckExtensions': False})
        yield instance
