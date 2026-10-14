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
