# Future engine integration

There is no engine implementation in Phase 1. The application supports local
Human vs Human only.

In Phase 2, a standalone C++17/20 executable will own its position representation,
legal move generation, material evaluation, and depth-limited Minimax or Negamax.
It must run without this GUI and must not delegate search/evaluation to Stockfish.

The Python application will use `chess.engine.SimpleEngine.popen_uci` in a worker
thread so UCI I/O never blocks the Pygame event loop. Send a board copy retaining
its move stack and retain the game's revision at dispatch. Return results to the
main thread; discard results if New Game, Undo, or another move changed the
revision. Submit accepted moves through `Game.play`, which validates legality.
Terminate the process cleanly on application shutdown.

Add only essential UCI commands and basic search first. Alpha-beta comparisons,
diagnostics, and modern search techniques belong to subsequent requested phases.
