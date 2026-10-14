# ChessLab

ChessLab is a desktop chess game and a project for learning search algorithms. The Python/Pygame application supports local two-player games and a custom standalone C++17 opponent. Minimax, alpha-beta pruning, iterative deepening, move ordering, advanced classical evaluation, Zobrist-based transposition tables, quiescence search, Principal Variation Search (PVS), aspiration windows, null-move pruning, and Late Move Reductions (LMR) are implemented with a comparison interface.

![ChessLab game board](docs/chesslab.png)

## Install and play on Windows

Install **Python 3.11 or newer** with Python on PATH. The verified environment is Windows with Python 3.11.8 and Pygame 2.6.1. Open PowerShell in this folder and run:

```powershell
.\setup.bat
.\launch.bat
```

Setup creates `.venv` and installs the pinned dependencies. It requires internet access on the first installation. The game uses bundled assets and needs no network connection. You can also double-click `launch.bat` after setup.

For manual installation or development:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.main
```

The launch script changes to its own folder, so it works regardless of your current working directory. Direct module commands should run from the repository root. Missing assets or dependencies produce an error with setup instructions.

### Build and play against the engine

```powershell
.\build_engine.bat
.\launch.bat --mode engine
```

Build once after setup. The script installs a portable C++ compiler in `.venv` and produces `engine/build/chesslab-engine.exe`. No global toolchain installation is needed. The first compiler download is about 80 MB. Rebuild after changing C++ sources; generated binaries are not committed.

Press **G** or click the opponent button for **Engine Thinking Time**. Choose exactly one of:

| Preset | Budget per engine move |
| --- | ---: |
| Blitz | 100 ms |
| Fast | 500 ms |
| **Standard (default)** | **1 second** |
| Deep | 3 seconds |
| Maximum | 5 seconds |

Keep **Time budget** selected and click **Apply to game** to preserve the board, history, and orientation. **Start new game** applies settings and resets the game. An active search keeps its original budget; a changed value applies to subsequent requests. You can edit settings while the worker searches. Local two-player play remains available.

**Gameplay no longer stops at depth 5.** Time mode searches depth 1, 2, 3, and onward until its deadline, with a 64-ply safety ceiling. Iterative deepening keeps the move, score, and PV from the last fully completed pass. A deeper interrupted pass cannot overwrite them; before any pass completes, the engine returns an unscored legal fallback. Terminal positions and proven mates may finish early. The board shows a subtle thinking indicator, completed depth, elapsed time, and nodes; the Pygame event loop stays responsive.

Choose **Fixed depth** for debugging and reproducible comparisons. The debug target remains 1–5 in the GUI; UCI `go depth 5` retains fixed-depth behavior. Time mode always deepens, while fixed mode retains the Deepening toggle. Search lab (**E**) compares both algorithms without moving: time mode gives each the selected budget and reports their actual completed depths, which can differ. Fixed mode compares the same target under the existing 15-second safety limit. **Stop** keeps completed work; Undo and New Game discard the request. Other feature toggles remain available.

```powershell
.\launch.bat --mode engine                         # Standard, 1 second
.\launch.bat --mode engine --thinking-time 500       # Fast, 500 ms
.\launch.bat --mode engine --search-mode depth --depth 5
.\launch.bat --mode engine --search-mode depth --depth 3 --no-iterative-deepening
.\launch.bat --mode engine --no-pst --no-transposition-table
.\launch.bat --mode engine --no-quiescence --no-pvs
```

`--engine PATH` selects another build of ChessLab. Missing engines are reported in the interface; local play remains available. Longer thinking generally helps search strength but does not guarantee a better move in every position. Scheduling, table allocation, and UCI overhead prevent exact millisecond precision. See the [time-control guide and all five measured results](docs/time-control.md).

Move ordering is also on by default: a matching table move first, then the previous completed principal variation along its original path, promotions, and captures ranked by victim value and attacker cost. Equal priorities retain their original order. Sorting can change which equally scored move wins a tie while preserving full-depth scores. With caching off, ordering alone does not reduce exhaustive Minimax's node count or guarantee a speedup.

**PST is on by default.** Classical piece-square tables add modest positional bonuses for every piece, encouraging central knights, useful development, and sheltered kings. The king blends middlegame/endgame tables using remaining non-pawn material (phase 0–24). Black mirrors ranks; scores still favor White. Choose **PST: off** in setup or Search lab to disable square bonuses. For the original material-only evaluator, also launch with `--no-advanced-evaluation`. See the [PST guide](docs/pst.md) for all tables, attribution, phase arithmetic, evaluation diagnostics, and benchmarks.

**Advanced classical evaluation is on by default.** A single phase blend combines material/PST, pawn structure and passers, safe mobility, king safety, bishop pairs, rook activity, supported outposts, space, and endgame king activity. Use `--no-advanced-evaluation` for the exact material/PST baseline. UCI exposes category switches and an `eval` JSON breakdown; the game layout and default 1-second budget stay unchanged. See [features, weights, benchmarks, and limitations](docs/advanced-evaluation.md).

**Transposition caching is on by default.** It reuses the rules library's incremental Zobrist key, guarded by the halfmove clock and repetition history. A bounded table stores completed scores, bounds, and PVs across iterative passes within one search. **Transpositions: off** restores the uncached baseline. Search lab shows hits, cutoffs, and occupancy. See the [TT guide](docs/transposition-tables.md) for safety rules, UCI memory controls, tests, and benchmarks.

**Quiescence and PVS are on by default.** Quiescence extends nominal leaves through captures, all promotions, and every legal check evasion. PVS probes later moves with narrow windows and fully re-searches promising moves; it applies only to alpha-beta. Search lab labels the pruning algorithm **PVS** or **Alpha-beta** and reports Q nodes, PVS probes, and re-searches. Both toggles preserve the current board. Turn both off to reproduce the earlier static-leaf/full-window search. See the [search guide](docs/search.md) for safety limits, protocol options, and measured comparisons.

**Aspiration windows, null-move pruning, and LMR default to on.** Aspiration retries narrow root windows until an exact pass completes. Conservative NMP and LMR reduce work selectively and can change fixed-depth scores versus Minimax. Minimax ignores all three. UCI and CLI provide independent debug switches; the gameplay layout stays unchanged:

```powershell
.\launch.bat --mode engine --no-aspiration-windows
.\launch.bat --mode engine --no-null-move-pruning --no-lmr
.\launch.bat --mode engine --search-mode depth --depth 5 --no-aspiration-windows --no-null-move-pruning --no-lmr
```

See the [optimization guide](docs/search-optimizations.md) for eligibility guards, PVS/TT interactions, staged validation, measured performance, and color-balanced smoke games. For exhaustive alpha-beta/Minimax comparisons and earlier benchmark counts, disable all three advanced switches. Longer completed depth and fewer nodes do not establish playing strength.

![Search lab comparing Minimax and PVS](docs/search-lab.png)

### Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/build_engine.py
.venv/bin/python -m app.main
```

The build needs recent C++17 GCC/Clang, or install `engine/requirements-build.txt` for the pinned compiler. Set `CXX` to override compiler selection. Linux desktop/build behavior is unverified. A graphical session is required for normal play.

## Controls

| Action | Mouse | Keyboard |
| --- | --- | --- |
| Move | Click your piece, then a legal destination | — |
| Change selection | Click another friendly piece | — |
| Deselect/cancel dialog | Click outside the board / dialog's Cancel | Escape |
| New game | New game | N |
| Undo one move | Undo move | U |
| Reverse orientation | Flip board | F |
| Claim an eligible draw | Claim draw | D |
| Choose promotion | Click Queen, Rook, Bishop, or Knight | Q, R, B, N in the promotion dialog |
| Scroll move history | Mouse wheel over the history | — |
| Choose opponent, color, algorithm, depth | Opponent button at top right | G |
| View statistics / compare algorithms | Search lab | E |

White starts at the bottom in local play; engine games initially face your color. New Game resets the position/history and keeps opponent settings. Local Undo removes one half-move. Engine Undo cancels pending work and returns to your previous decision, removing the reply and your last move when needed. The engine's opening move alone cannot be undone. Withdrawing a human draw claim leaves the board unchanged; undoing an engine claim also returns to your decision.

## Implemented features

- Resizable dark slate interface, ivory/walnut board, rank/file labels, and licensed local chess-piece artwork.
- Piece selection, legal destination dots, capture rings, previous-move highlights, and a checked-king indicator.
- Legal standard chess moves, captures, both castling sides, en passant, and all four promotion choices.
- Current turn, captured pieces grouped by capturing player, scrolling SAN move history, and clear results identifying the winner or draw reason.
- Checkmate, stalemate, insufficient material, automatic fivefold repetition, and the seventy-five-move rule.
- Explicit threefold repetition and fifty-move claims. The claim dialog lists eligible current-position claims or intended moves; scroll for additional choices. An intended-move claim declares the move without playing it.
- Reversible game endings, Undo, restart, manual board flipping, and keyboard shortcuts.
- Human vs Engine as either color, selectable Minimax/alpha-beta, five thinking-time presets, and optional fixed-depth search.
- Switchable iterative deepening retains completed answers under shared time/node limits. The fixed-depth baseline remains available.
- Switchable PV, promotion, and MVV-LVA capture ordering, including en passant and capture promotions; the original move-order baseline remains available.
- Switchable material + PST evaluation for all six piece types, with separate middlegame/endgame king tables and smooth phase interpolation.
- Switchable, bounded transposition tables with Zobrist keys, draw-context guards, exact/lower/upper bounds, normalized mate scores, and complete cached PVs.
- Switchable quiescence with check evasions, capture/promotion continuation, shared budgets, and bounded extensions.
- Switchable PVS with full re-searches; exhaustive Minimax remains the comparison reference.
- Switchable aspiration windows, guarded null-move pruning, and conservative LMR with full-depth verification of promising reduced moves.
- Search lab compares depth, nodes, time, score, and move on one unchanged position, with live completed-pass history and clear target-depth status.
- Background UCI work, cancellation, stale-result rejection, and engine error reporting.

## Architecture

```text
app/
  main.py             CLI, startup errors, and shutdown
  application.py      Pygame event loop and layout
  game.py             Validated moves, history, captures, outcomes, draw claims
  input_handler.py    Selection and pending promotion
  engine_client.py    Background UCI jobs, cancellation, and statistics
  board_renderer.py   Orientation mapping, board drawing, cached piece images
  ui/                 Shared style, sidebar, promotion and claim dialogs
  assets/             PNG pieces, original SVGs, and license/attribution
tests/                Rules, interaction, event-loop, and rendering tests
tools/prepare_assets.py  Development-only artwork conversion
engine/src/           C++ UCI protocol, shared search, evaluation, and PST arrays
engine/vendor/        Rules library and PST attribution/licenses
tools/build_engine.py C++17 build helper
tools/benchmark_evaluation.py  Matched PST/material measurements and smoke games
tools/benchmark_transpositions.py  Matched cached/uncached measurements
tools/benchmark_search.py  Four-way quiescence/PVS measurements
tools/benchmark_time.py  Historical time-control baseline
tools/benchmark_optimizations.py  Four stages at depth and all five time budgets
tools/match_optimizations.py  Color-balanced baseline/advanced smoke games
```

`Game` has no Pygame dependency. It validates a move before changing the board and records SAN and the actual captured piece before pushing. This also handles en passant and captures of promoted pieces correctly. Undo uses the original board stack, preserving castling, en passant, and repetition history.

`InputHandler` keeps temporary selection and promotion separate from committed moves. Rendering reads the game state. Board coordinates and hit testing share one orientation transform. Expensive draw eligibility checks are cached after state changes; fonts and piece images are cached, and the event loop runs at up to 60 FPS.

The engine independently represents positions and generates moves with a pinned C++ rules library. A shared Minimax function uses the selected classical or advanced evaluator, optionally orders legal moves, and optionally applies alpha-beta cutoffs. Iterative deepening saves complete passes and supplies the next pass's PV hints. A Python worker streams UCI progress from full-history snapshots; only final replies can apply a move on the GUI thread, after request/revision checks.

## Tests and verification

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\build_engine.bat
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\launch.bat --smoke-test 3 --screenshot chesslab.png
```

Benchmark every preset on seven positions (three repeats), with results saved as JSON:

```powershell
.\.venv\Scripts\python.exe -m tools.benchmark_time --output artifacts\time-benchmark.json
```

**Verified on Windows: 852 automated tests pass.** Build the engine before running the full suite; native TT tests also use the compiler. Tests cover rules, special moves, outcomes, draw claims, undo/reset, and a seeded 180-half-move game rewound position by position.

Engine checks include perft, legal moves cross-checked against python-chess, mate/score handling, Minimax/alpha-beta equivalence, UCI interruption, process errors, stale replies, and actual engine-to-GUI play/comparison. Ordering checks compare optimal moves and scores against an independent Python reference across both algorithms and deepening modes, including castling, promotions, en passant, and pinned pieces. They also verify the original node baseline, tactical node savings, per-search PV isolation, interrupted result retention, and GUI toggle behavior.

Historical ordering/PST/TT measurements below use **advanced evaluation, quiescence, PVS, and all three advanced search optimizations off**; reproduction tools explicitly retain these conditions.

With PST and transposition caching disabled, iterative alpha-beta visits 25,261 nodes at initial depth 5 with ordering, versus 38,388 without (34.2% fewer). At Kiwipete depth 4, it visits 9,754 versus 63,617 (84.7% fewer). Each pair has identical score and move. Counts include all completed passes; these are search-work measurements, not strength ratings.

PST checks cover every piece, rank/color symmetry, all game phases and rounding, unchanged material values, search/diagnostic consistency, terminal scores, and GUI selection. In the recorded uncached depth-5 comparison, PST changes b3 to e4 (+70 cp) and visits 182,596 nodes; evaluation changes can increase the tree. Four paired smoke games score 2 wins, 1 draw, and 1 loss for PST. This small sample establishes no Elo gain. Full [benchmarks and reproduction instructions](docs/pst.md#verification-and-benchmarks) include moves, scores, nodes, time, NPS, FENs, and PGNs.

With PST enabled at depth 5, transposition caching reduces initial nodes from 182,596 to 118,406 (35.2%) and Kiwipete from 87,554 to 62,262 (28.9%), preserving each move and score. Native tests exercise hashes, make/unmake, collisions, bounds, mate distances, and draw-context separation; integration checks cached moves through uncached exhaustive child searches. [Detailed results](docs/transposition-tables.md) include timing and limitations.

Quiescence tests use an independent tactical oracle and cover recaptures, quiet check evasions, en passant, promotions, terminal precedence, caps, and shared interruption budgets. PVS is checked against full-window scores with both evaluations, cache settings, and deepening modes. In the [four-way benchmark](docs/search.md#measurements), PVS with quiescence reduces Kiwipete depth-4 nodes from 141,975 to 82,297 (42.0%), with the same move and +45 cp score. Quiescence changes the leaf model and can increase work substantially; PVS gains vary by position.

Headless Pygame tests exercise mouse/keyboard events, modal dialogs, scrolling, resize, both orientations, artwork dimensions, missing-asset errors, and event-loop shutdown. Tests set SDL's dummy video driver so they do not open desktop windows. Screenshots of the initial board, promotion, checkmate, and draw dialog were visually inspected.

Advanced-search tests cover exact aspiration scores/retries, null board/hash/history restoration, zugzwang/check/mate guards, LMR tactical exclusions and verifications, deterministic feature combinations, selective interruption, and UCI stop/quit.

Time-control checks cover all presets, legal fallback/terminal replies, depths above 5, matching completed snapshots, exact-once stop/quit replies, nested move restoration, and in-flight settings changes without resetting the board. [Recorded timing results](docs/time-control.md#measurements) include 105 runs over opening, middlegame, tactical, endgame, mate, and stalemate positions.

Windows setup/build, launch smoke testing, and dependency checks passed. Native checks cover real engine play, setup selection, and Search lab comparisons with quiescence/PVS on and off on the unchanged board. All modal controls and five-pass statistics were rendered and inspected at normal and minimum sizes. Earlier native checks also cover Undo and iterative/direct toggling.

Read [AGENTS.md](AGENTS.md) for contributor instructions.

## Assets and dependencies

The Cburnett chess pieces and PNG conversions use CC BY-SA 3.0. All twelve individual source pages were checked for that license offer. See [asset attribution](app/assets/ATTRIBUTION.md) and the bundled full license. Runtime loads only the checked-in PNGs.

Rebuild the PNGs from local SVGs, without downloads:

```powershell
.\.venv\Scripts\python.exe tools\prepare_assets.py --offline
```

Running that tool without `--offline` checks the source licenses online and downloads missing originals. Third-party library notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Current limitations

- NMP/LMR are selective heuristics and can miss quiet resources or unusual zugzwangs despite conservative guards. Gains depend on the position; no reliable Elo gain is established.
- Advanced evaluation adds handcrafted positional terms with untuned weights. Mobility uses attack maps rather than full tactical legality, and material scaling is heuristic. Quiet checking moves and SEE/delta pruning remain deferred; benchmark results do not establish an Elo gain.
- Quiescence stops at non-check nodes after 16 extra plies or absolute ply 64; check evasions continue to the absolute ceiling, where an unresolved check interrupts the pass. These safety limits are heuristic boundaries. Stand-pat evaluation can miss zugzwang.
- Transposition tables are fresh per search and use conservative draw-history matching. Allocation can make tiny searches slower despite node savings; no cross-search cache is retained.
- Timed gameplay uses 100–5000 ms with a 64-ply safety ceiling. Fixed-depth GUI debugging retains depths 1–5 and a 15-second watchdog. No score is claimed before a completed pass; CPU load and communication can add timing overhead.
- The engine claims eligible draws on its turn, even when a win might exist. Search assumes currently claimable repetition/fifty-move draws are taken.
- No clocks, save/load, PGN export, or drag movement.
- Games are held in memory and are discarded when the application closes.
- The minimum supported layout is 960 × 680; text uses an available system font.
- Dead-position adjudication follows python-chess's insufficient-material detection. Unusual blocked positions that are dead for other reasons are not exhaustively detected.
- Linux desktop behavior and other Python versions have not been verified.

## Roadmap

1. **Implemented:** playable Python/Pygame local two-player application.
2. **Implemented together (Phases 2–3):** independent C++ UCI engine, material evaluation, Minimax, switchable alpha-beta, Human vs Engine, and search comparisons.
4. **Implemented:** iterative deepening, move ordering, switchable PST evaluation, transposition tables, quiescence, Principal Variation Search, configurable time-controlled gameplay, aspiration windows, null-move pruning, LMR, and modular advanced classical evaluation.
5. Tune evaluation weights and consider further optimizations only after broader testing.
6. **Implemented:** matched performance benchmarks and color-balanced engine smoke games; broader strength testing remains future work.

Later phases require an explicit request. The engine performs its own search and evaluation without delegating them to another engine.

## Engine details

See [engine/README.md](engine/README.md) for evaluation values, shared search behavior, UCI commands, build options, node definitions, cancellation, rules-library attribution, and standalone diagnostics.
