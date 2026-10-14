# Engine audit

## Architecture before changes

Baseline source is `b5023bd` (ChessLab/StockBear 0.10). The original executable
is preserved at `artifacts/audit/original-b5023bd.exe`; recorded SHA-256 identifies
it independently of later builds. The unchanged baseline passes 852 tests.

- Pinned Disservin 0.9.4 supplies bitboards, magic sliding attacks, precomputed
  pawn/knight/king attacks, legal move generation, reversible state records,
  incremental Zobrist keys and repetition history. Vendor sources remain intact.
- Shared White-maximizing/Black-minimizing Minimax optionally applies alpha-beta,
  PVS, aspiration windows, guarded null moves and verified LMR. Iterative passes
  publish only completed snapshots. Quiescence generates all legal moves then
  filters captures/promotions, retaining all evasions and terminal precedence.
- RAII move guards restore one mutable board. Only the search root is copied.
  Recursive principal variations use temporary heap vectors; stable sorting can
  allocate temporary storage. Both are candidates for measurement.
- Evaluation combines material, attributed PSTs and eleven MG/EG components.
  Attack maps are shared within a call, but pawn structure and material/PST are
  recomputed between nodes. No evaluation cache exists in the baseline.
- A fresh bounded, direct-mapped TT stores full 64-ply PVs, full position hash,
  reversible-history fingerprint, halfmove clock, score/bound/depth and root ply.
  Exact-depth reuse preserves the fixed-horizon contract. Entries are large
  because complete PVs survive unrelated table evictions.
- UCI main thread owns position/options. A joined worker owns copied position
  and immutable limits. Stop uses an atomic; output is mutex-protected. Python
  workers stream UCI off the Pygame thread; tokens/revisions reject stale moves.
- Time budgets use a monotonic deadline checked every 256 nodes and between
  iterations/retries. Gameplay defaults to 1 second, with legal fallback before
  the first completed pass and terminal/mate early exits.

Audit checklist, additional verification, findings and final decisions follow
after the frozen baseline and profiling stages. Missing heuristics are not bugs:
killer/history, SEE, mate-distance pruning, check extensions and SMP are absent
in the starting version. They require independent justification before addition.

## Frozen baseline and initial profile

All 26 canonical perft depth/position cells pass against the exact [published
CPW FENs and counts](https://chessprogramming.org/Perft_Results). The original
executable's immutable repeated depth/time records are in [baseline.json](audit/baseline.json).
Instrumentation is isolated in a second executable; its fixed-depth nodes,
scores, best moves and complete PVs match the original on all seven positions.
Its extra clock/counter overhead means instrumented NPS must not be compared
with release NPS. [profile-before.json](audit/profile-before.json) records both
exclusive category times and C++ new/new[] counts on the search thread.

The initial instrumented category shares are: evaluation and its subcomponents
46.2%, remaining search/recursion/allocator/reporting 23.6%, move generation
14.0%, make/unmake 7.6%, draw checks 3.1%, ordering 3.0%, TT 1.3%, policy guards
1.2%. These are instrumented wall-clock estimates, not OS CPU samples. Timing
instrumentation overhead affects short operations and residual search time.
The middlegame depth-6 search performs 320,647 evaluations and 255,751 counted
allocations; tactical depth 6 performs 479,780 evaluations and 319,987 allocations.
TT allocation occurs before the measured search region; progress reporting is
included. No claim is made that every allocation comes from recursive PVs.

Optimization priorities justified by these measurements: remove recursive PV
and sorting allocations; reuse pawn-only evaluation information with complete
keys; avoid full legal lists at static leaves and unnecessary quiet moves in
quiescence while preserving terminal precedence. TT layout/board rewrites rank
below these and are not justified by this profile.

## Allocation optimization

Recursive PVs now use bounded 64-move lines; only completed root lines allocate
into the public result vector. Stable insertion ordering preserves equal-score
move order without stable_sort scratch allocation. All seven depth-6 score,
node, best-move and complete-PV snapshots match the frozen original. Repeated
release medians improve opening/middlegame/tactical NPS by approximately
8.6%/9.6%/9.6%; sub-millisecond endings are too short for reliable NPS ratios.
Perft and the expanded tactical/restoration corpus pass. One diagnostic-parser
compatibility issue was found and fixed before retaining the change.

## Pawn cache design and correctness

The 1024-entry cache is private to one search and verifies both complete pawn
bitboards, not just an index or shortened hash. Entries contain pawn attack and
double-control maps, pawn-only structural scores, passer masks and *candidates*
for backward pawns. King shields, game phase, passed-pawn blockage, and backward
pawn forward-square occupancy are recomputed live. Category flags never affect
cached contents. Independent `PawnCache` UCI selection permits exact ablations.

A 100-position seeded differential compares every diagnostic component with the
preserved original, including PST/category variations: all match. Native random
walks compare cached/uncached scoring with both PST modes and rotating category
switches, exercising cache hits, misses and replacements. Search checks verify
identical nodes, Q nodes, score, move and PV with the cache enabled/disabled.

## Legal-generation optimization

The pinned library already has a short-circuit `anylegalmoves` API. Static
leaves now use it instead of constructing every legal move. Non-check Q nodes
first prove a legal move exists, then check draws and stand pat. Capture-only
lists are generated only if stand pat did not cut. Nodes in check, positions
with a pawn on its promotion rank, and ordering-disabled Q searches retain the
complete previous generation/filter path. This preserves quiet promotions,
underpromotions, en passant, evasions, stalemate/mate precedence and stable ties.
`FastMovegen` is independently switchable for exact semantic comparisons.

The full optimized suite now passes 909 tests. Fast generation on/off is checked
in 36 combinations of standard/special/terminal positions, Q selection, ordering
and pruning. Exhaustive or unordered tactical Q trees use a deterministic
50,000-node budget, testing completed snapshots and unscored legal fallback
rather than incorrectly demanding completion within a wall-clock watchdog.

## Features intentionally left unchanged

Killer/history/SEE/countermove/continuation ordering and additional selective
pruning remain missing. They can change selective search results and need their
own strength study; this audit first targets measured implementation overhead.
Mate-distance pruning and check extensions also remain absent. Existing legal
bitboards/magic attacks and in-place undo already meet the proposed architecture
optimizations. TT consumes only about 1.3% of the instrumented baseline; changing
its complete-PV/exact-depth contract or introducing clusters is not justified
before the larger measured costs are removed. No neural evaluation is added.

## Confirmed correctness fixes

1. **Promoted same-color bishops:** the pinned rules library's material shortcut
   stops at four occupied squares. With three same-color bishops versus a king,
   the original UCI engine returned `a1b1` and +1005 cp although python-chess
   correctly marked the position insufficient material. An engine-owned
   `terminal_rules.hpp` now handles arbitrary same-color bishop counts while
   preserving potentially mating B+N and two-knight material. Both colors are
   covered; upstream vendor code is unchanged.
2. **Imported halfmove overflow:** UCI validation accepted clocks through 65535,
   but the library stores an 8-bit counter. Thus 256 silently became zero and
   lost an available fifty-move draw. FEN import now saturates clocks above 100
   to 100 under the engine's documented always-claim policy. Appended quiet moves
   retain saturation; a pawn move/capture resets normally. Rebuilding history
   after saturation is safe for this policy: the current position already has a
   claim, and a later resetting move makes the older repetition history irrelevant.
   Checkmate/stalemate precedence remains intact. Direct users of the raw vendor
   Board must still respect its 8-bit clock representation.

The final release passes 929 automated tests. Undefined-behavior instrumentation
also passes 27,509 randomized move/null-move restoration transitions, 2,256 distinct pawn-key pairs forcing table-index collisions, cached versus
uncached evaluation with varied options, and bounded recursive fast/full search
comparisons. This is runtime evidence, not a proof of freedom from every bug.

## Search feature checklist

Statuses below describe the retained release. “Implemented and working” means
the stated contract was checked by inspection and tests, not that the heuristic
is theoretically optimal or every possible chess position has been proven.

| Feature | Status | Verification / boundary |
| --- | --- | --- |
| Minimax | Implemented and working | White maximizes, Black minimizes; independent material/tactical oracles and exhaustive comparisons. |
| Negamax | Missing | Minimax supplies the shared search; no duplicate Negamax path is needed. |
| Alpha-beta | Implemented and working | Exhaustive score comparisons with selective features disabled, both colors. |
| PVS | Implemented and working | Side-aware unit scouts and strict-interior full-window re-search; PVS/full-window/cache matrices. |
| Iterative deepening | Implemented and working | Ordered complete passes; direct-depth equivalence and interrupted snapshot tests. |
| Time-controlled deepening | Implemented and working | All five presets, completed depth/PV preservation, legal unscored fallback, responsive UCI. |
| Quiescence | Implemented and working | Captures, all promotions, every check evasion; independent tactical oracle, caps and terminal precedence. Quiet nonpromotion checks are not generated outside check. |
| Move ordering | Implemented and working | TT, original-path PV, promotions, MVV-LVA; stable ties preserved after insertion replacement. |
| TT | Implemented and working | Full position key, reversible-history fingerprint and clock; bounds/depth/ply rules, collisions and interruption tests. |
| Zobrist hashing | Implemented and working | Pinned incremental key compared with full recomputation for legal, null and undo transitions. |
| Aspiration windows | Implemented and working | Both failures, widening/full-window fallback and no partial publication; exact-score matrices. |
| Null-move pruning | Implemented and working | Non-PV/unit window, check/material/repetition/clock/mate guards, no nested synthetic history/TT reuse; observed cutoffs, zugzwang and sacrifice checks. Still a selective heuristic. |
| LMR | Implemented and working | Late quiet non-checking moves only; full-depth verification on improvement, outer PVS re-search and stop tests. Still selective. |
| Killer heuristic | Missing | Not added without an independent strength study. |
| History heuristic | Missing | Same decision; current ordering does not claim history-based learning. |
| SEE / countermove / continuation history | Missing | Candidates for future separate experiments. |
| Principal variation tracking | Implemented and working | Bounded recursive lines, complete TT PVs, path-correct hints, legal replay and saved complete snapshots. |
| Mate-distance pruning | Missing | Mate-distance scoring/TT normalization exist; no mate-distance window pruning. |
| Nominal check extensions | Missing | Q evasions continue in check; no separate main-search extension. |
| Futility / reverse futility / razoring | Missing | No new aggressive pruning was introduced. |
| Mate propagation | Implemented and working | Terminal mate before draws, shorter wins/longer losses, mate-in-one/two independent proofs. |
| TT mate normalization | Implemented and working | Root-ply conversion in both directions, native exact/lower/upper tests. |
| TT bound classification | Implemented and working | Original alpha/beta window, no interrupted stores, normalized scores, exact-depth/root-ply Q restrictions. |
| Repetition | Implemented and working | Real history and reversible fingerprint; threefold/undo/null-subtree separation. Prospective claim declaration remains a GUI responsibility. |
| Fifty-move handling | Implemented and working after fix | Current claims precede evaluation; large imported clocks saturate instead of wrapping, quiet continuations and resets covered. |
| Insufficient material | Implemented and working after fix | Same-color bishop sets generalized, including promotions; B+N/two-knight positions remain searchable. General dead-position solving is outside scope. |
| Fail-high / fail-low | Implemented and working | Aspiration retries and TT lower/upper classification tested with both score signs. |
| Interruption / restoration | Implemented and working | Atomic stop, budget exceptions and RAII restore; node-limited/full-state/random/null tests. |
| Last completed result | Implemented and working | Only finished root passes publish; partial retries/deeper passes cannot replace them. |

## Evaluation feature checklist

Every row is **implemented and working as a deterministic handcrafted
heuristic**. The [evaluation guide](advanced-evaluation.md) specifies all weights
and formulas. Playing value remains untuned; tests verify implementation rather
than claiming positional perfection.

| Component | Evidence and limitation |
| --- | --- |
| Material | Fixed piece values; diagnostic/search agreement and unchanged material-only baselines. |
| PST, all six pieces | Original attributed arrays; exact old values, rank-only Black mirror, phase/rounding tests. |
| MG/EG taper | Phase clamped 0–24, one advanced blend, symmetric rounding/scaling and reconciling components. Legacy per-king rounding retained separately. |
| Doubled / isolated pawns | Per-extra-file and missing-adjacent-file FEN checks in both orientations. |
| Backward pawns | Conservative candidate and unsafe forward square; occupancy remains live across pawn-cache hits. Not a complete weakness detector. |
| Connected pawns | Supported/same-rank neighbors, credited once per pawn; exact component tests. |
| Passed pawns | Enemy ahead on same/adjacent files, leading friendly pawn only, direction/advancement tests. |
| Protected / blocked passers | Pawn support bonus and live any-piece path blockage; cached context cannot reuse blocked status. No exact promotion race solver. |
| Bishop pair | Both square colors required; promoted same-color bishops do not earn it. |
| Mobility | Safe pseudo-attack unions; enemy pawn/king attacks excluded, moving piece not its own defender. Pinned pieces and exchange sequences remain approximate. |
| Rook activity | Actual-pawn open/semi-open files, conditional seventh rank, clear line behind passers. No connectivity term. |
| Knight outposts | Advanced, pawn-supported, no future adjacent enemy pawn challenge. Exchange availability not solved. |
| King safety / pawn shield | Color-correct near/far shelter, files, enemy zone attackers and remaining-material scaling; zero pawn-only safety penalty. No x-ray/check sequence solver. |
| Space / center | Small safe control/pawn-supported territory terms; no large generic placement bonus. |
| Endgame king activity | Enemy-pawn distance and local passer support; PST supplies generic centralization. Opposition/tempo and specialized endings absent. |

Material/PST are not counted twice and the king is not tapered twice. Connected
and protected-passer rewards intentionally stack under different components;
rook/passers and shelter/file exposure also describe correlated chess factors.
Their combined weights need tuning, but no arithmetic duplicate was found.
Static scores remain far from reserved mate values for the inspected material
ranges. A 100-position all-component differential matches the original exactly;
the performance work does not retune positional preferences.

## UCI, GUI and thread verification

`uci`, `isready`, `ucinewgame`, both position forms, depth/movetime/node searches,
`stop`, `quit`, valid/invalid `setoption`, unknown commands and input recovery are
tested against the actual executable. JSON diagnostics stay in `info string`;
profiling JSON appears only in explicitly instrumented builds. New counters
preserve existing diagnostic section contracts.

Main-thread position/options updates join the old worker before mutation. The
worker owns its board, limits, TT and pawn cache. Stop is atomic and output is
mutex-protected. Python workers do not touch Game/Pygame; frozen settings and
tokens/revisions isolate requests. No race was observed in stop/quit/restart
tests, but no ThreadSanitizer proof is claimed on this Windows run.

The actual app completed legal replies at 100/500/1000/3000/5000 ms, retained
responsive frames, discarded Undo/New stale requests, and compared both algorithms
without changing the board. [GUI records](audit/gui-verification.json) distinguish
dummy-driver measurements from the separate self-closing desktop launch. Both
default and minimum-size frames were inspected. No unrelated GUI layout changed.

## Optional multithreading and remaining limitations

Phase 7 was assessed and deliberately left single-threaded. Sharing the current
non-atomic multiword TT/PVs would race; coherent budgets, stop and completed
result ownership require design and measured scaling. The audit's safe
single-thread gains do not by themselves justify Lazy SMP. See the
[performance report](performance-report.md) for measured decisions, records,
compiler experiments, match methodology and future work.

This audit is broad regression/runtime evidence, not formal verification of the
entire vendor library or all legal chess positions. The engine assumes available
current-position claims are taken, has finite Q/search ceilings, and retains
selective NMP/LMR and untuned evaluation. Full dead-position recognition,
specialized endgame knowledge and reliable universal Elo remain outside the
verified contract.

## Completed match and artifact verification

All 200 original-versus-optimized games completed the harness: 82 optimized wins,
74 draws, 42 losses and 2 explicitly unfinished caps. Every PGN was independently
replayed (24,392 legal plies), results checked, and both binary hashes matched
against the frozen baseline/final paired benchmark. Point estimate +71 Elo has
a conservative paired 95% interval about −26 to +179: no conclusive Elo gain is
claimed. A Windows checkpoint I/O failure after game 178 was repaired with atomic
retrying writes, tested, and resumed without changing engine binaries/settings.
The [performance report](performance-report.md) includes the full methodology,
uncertainty, results, limitations and reproduction commands.
