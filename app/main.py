"""Launch with ``python -m app.main`` from the repository root."""

import argparse
import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


def main() -> int:
    parser = argparse.ArgumentParser(description="ChessLab: local two-player chess")
    parser.add_argument("--smoke-test", type=int, metavar="FRAMES",
                        help="Render FRAMES frames and exit (for verification).")
    parser.add_argument("--screenshot", metavar="PNG", help="Save the final frame as a PNG.")
    parser.add_argument("--mode", choices=("local", "engine"), default="local")
    parser.add_argument("--human-color", choices=("white", "black"), default="white")
    parser.add_argument("--algorithm", choices=("minimax", "alphabeta"), default="alphabeta")
    parser.add_argument("--depth", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--engine", metavar="PATH", help="Path to the compiled ChessLab UCI executable.")
    args = parser.parse_args()
    if args.smoke_test is not None and args.smoke_test < 1:
        parser.error("--smoke-test must be at least 1")
    try:
        from app.application import Application
        from app.engine_client import DEFAULT_ENGINE, EngineSettings
        from pathlib import Path
        import pygame
    except ImportError as error:
        print(f"ChessLab could not load a dependency: {error}\n"
              "Run setup.bat on Windows, or install requirements.txt in your virtual environment.",
              file=sys.stderr)
        return 1
    app = None
    try:
        settings = EngineSettings(args.mode == "engine", args.human_color == "white",
                                  args.algorithm == "alphabeta", args.depth)
        app = Application(settings=settings, engine_path=Path(args.engine) if args.engine else DEFAULT_ENGINE)
        app.run(args.smoke_test, args.screenshot)
        return 0
    except (pygame.error, OSError) as error:
        print(f"ChessLab could not start or save its display: {error}\n"
              "Check the display is available and app/assets/pieces contains all twelve PNGs.",
              file=sys.stderr)
        return 1
    finally:
        if app is not None:
            app.close()
        else:
            pygame.quit()


if __name__ == "__main__":
    raise SystemExit(main())
