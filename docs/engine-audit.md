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

The final release passes 926 automated tests. Undefined-behavior instrumentation
also passes 27,509 randomized move/null-move restoration transitions, cached versus
uncached evaluation with varied options, and bounded recursive fast/full search
comparisons. This is runtime evidence, not a proof of freedom from every bug.
