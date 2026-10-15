# StockBear NNUE v2 optimization results

All requested phases were completed without retraining or changing search policy.
**Retained: move-derived updates and ordered portable float32 inference.** Scalar
quantization remains an explicit experiment. Neither explicit SIMD prototype
earned a production place. Classical remains the default evaluator; ordinary
builds preserve the original v1 network. Both v2 finalists have separate build
and GUI startup instructions in the [model guide](engine/networks/v2/README.md).

## A. Baseline comparison

Reference source: tag `nnue-v2-native-baseline-1b1794e`. Inspection covered
`engine/src/nnue.{hpp,cpp}`, `search.{hpp,cpp}`, `scoped_move.hpp`, UCI/GUI clients,
embedding/build scripts, the training feature/export reference and existing
tests/benchmark tools. Original v1/v2 exports and historical records were kept.
The v2 “best” export is byte-identical to Small.

Hardware: Intel Core i5-13420H, 12 logical CPUs, Windows, native single-thread
search, Zig 0.13.0 C++17, `-O2 -ffp-contract=off`, Hash=16MB. No affinity or fixed
clock was imposed. CPUID plus OSXSAVE/XGETBV verified AVX2 and FMA availability.
No GPU, Python evaluator, Stockfish search, fast-math or FMA contraction was used.

All four baselines used identical search defaults and budgets: 100,000 nodes
and 200ms, three rotated serial trials per each of ten FEN categories. Fresh
per-search TT storage prevents evaluator contamination. Microbenchmarks used
20,000 calls per trial and report samples, median, range and standard deviation.
Below: median **NPS / completed depth** at 200ms before optimization.

| Evaluator | Opening | Quiet middle | Tactical | Pawn ending |
| --- | --- | --- | --- | --- |
| classical | 2.85M / 9 | 2.63M / 7 | 2.74M / 6 | 6.05M / 11 |
| v1 | 1.20M / 8 | 1.28M / 7 | 1.19M / 6 | 2.66M / 10 |
| compact | 1.21M / 8 | 1.32M / 7 | 1.14M / 6 | 2.61M / 10 |
| small | 0.55M / 7 | 0.57M / 5 | 0.52M / 5 | 0.87M / 9 |

Exact executable/model hashes, build flags, FENs, moves, depths, actual nodes,
times and variability: [baseline JSON](docs/nnue-v2/baseline.json). A forced-mate
king-attack fixture completes early; its millisecond-granularity NPS is retained
in raw records but excluded from aggregate speed ratios. Equal node budgets
are search-work comparisons, not playing-strength evidence.

## B. Profiling findings

Internal `steady_clock` exclusive scopes covered three 300ms searches on five
categories per model. These percentages include clock-instrumentation overhead;
they are **not** release CPU-cycle proportions or release NPS comparisons.

| Build | Model | Head | Full features | Copy/update | Other search |
| --- | --- | --- | --- | --- | --- |
| profile-original | compact | 26.1% | 11.4% | 10.5% | 20.4% |
| profile-original | small | 58.2% | 6.8% | 6.6% | 10.9% |
| profile-final | compact | 15.6% | 0.0% | 17.3% | 26.6% |
| profile-final | small | 30.0% | 0.0% | 15.3% | 21.4% |

The original head, including clipping, dense arithmetic and weight access, was
the largest named cost. Feature extraction/sorting and accumulator bookkeeping
were also material. Replacing the head layout removed its long scalar dependency
chains; the remaining state-update share is now a useful next target. Copy,
board-derived update and rebuild latency are separately measured in the raw
microbenchmarks. Heap allocation is absent inside the normal inference/update
loops; search-level allocation counts include stacks and PV/reporting work.

WPR was on the command path; WPA/Visual Studio profiler were not found there
and were not used. No hardware
cache-miss, branch-misprediction or bandwidth counters were collected. Internal
timers cannot separate overlapping weight loads, arithmetic, activation and
cache/branch penalties, so no such attribution is claimed. Cache-friendly access
is a design explanation, not a measured cache-hit result.
See [original](docs/nnue-v2/profile-original.json) and
[final profiles](docs/nnue-v2/profile-final.json).

## C. Implemented optimizations

1. Capture piece changes before makeMove; check rights and **legal** EP afterward.
   Only changed rows are sorted. Both unclipped perspectives remain White/Black;
   roots refresh and child frames isolate siblings, nulls, re-search and stop.
   The original board-derived update/rebuild remains selectable. An edge audit
   added removal-before-insertion bookkeeping for full 37-feature positions;
   accumulator arithmetic still follows the original sorted row order.
2. Embed a second, contiguous 64-byte-aligned transpose of the hidden weights.
   Process independent neurons together while preserving each neuron's exact
   multiply/add sequence. Clipping, hidden output order and 400cp conversion are
   unchanged. This permits safe compiler vectorization without reassociation.
3. Size frames to the embedded width. Frames include both experimental integer
   and float storage: Compact **664 bytes**, Small **1,176**, versus the original
   2,200. Storage has a directly measured byte benefit; no isolated speed claim
   is assigned to that change.

Isolated stage changes below are geometric mean timed NPS changes over the nine
nonterminal categories. Each stage was validated before the next optimization.

| Stage | Compact | Small |
| --- | --- | --- |
| delta | +7.2% | +3.4% |
| scalar | +41.2% | +143.4% |
| simd | +0.1% | -1.9% |

Explicit AVX2 float had essentially no overall gain and slowed Small; AVX2 integer
had only minor gains over the slower integer prototype. Both passed parity but
were removed. Their frozen [float](docs/nnue-v2/simd.json) and
[integer measurements](docs/nnue-v2/quant.json) remain reproducible from Git.
All retained inference is portable; runtime does not require AVX2/FMA.

Only NNUE state preparation and per-worker kernel selection changed in search
integration. Alpha-beta, PVS, LMR, null pruning, aspiration, quiescence, TT
replacement, move ordering, evaluation weights and vendor rules are unchanged.

## D. Numerical correctness

Each finalist passed its 128 trained goldens, 20,152 original grouped held-out
FENs, 2,000 seeded random positions and 13 category/extreme fixtures. Float32
fresh scores were identical to the frozen native reference on all 22,165 FENs.
Golden errors reflect the original PyTorch/native float rounding difference.

| Model | Kernel | Golden max cp | MAE cp | RMSE cp | Max cp | Sign differences |
| --- | --- | --- | --- | --- | --- | --- |
| compact | scalar | 0.000202 | 0.0000 | 0.0000 | 0.0000 | 0 |
| compact | quant | 1.799981 | 0.3232 | 0.4231 | 2.2842 | 14 |
| small | scalar | 0.000199 | 0.0000 | 0.0000 | 0.0000 | 0 |
| small | quant | 1.319973 | 0.3018 | 0.4052 | 2.5598 | 9 |

Held-out quantization error by phase:

| Model | Phase | Positions | MAE cp | RMSE cp | Max cp | Sign differences |
| --- | --- | --- | --- | --- | --- | --- |
| compact | endgame | 5499 | 0.3403 | 0.4342 | 2.0696 | 2 |
| compact | middlegame | 11924 | 0.3387 | 0.4416 | 2.2842 | 7 |
| compact | opening | 2729 | 0.2070 | 0.2694 | 1.5543 | 3 |
| small | endgame | 5499 | 0.3243 | 0.4187 | 1.9098 | 0 |
| small | middlegame | 11924 | 0.3191 | 0.4250 | 2.5598 | 4 |
| small | opening | 2729 | 0.1609 | 0.2190 | 1.2308 | 3 |

Quantization uses int16 weights/activations, int32 unclipped accumulators and
int32 dots. Every finalist scale is 4096, with nearest rounding/ties away from
zero and activation saturation to [0,4096]. The embedder reduces scales for
other weights if necessary, proves final and transient bounds before enabling
the optional path, and preserves valid float exports if quantization is unsafe.
Original `.sbnnue` format/files are unchanged; only derived embedded constants
are added. Full details: [integer contract](docs/nnue-v2/README.md#integer-experiment).
Sign changes occur only near zero, within the reported maximum score error.
Accuracy gates were MAE<1cp and max<5cp; passing them does not prove equal Elo.

Worst absolute transient accumulator / dense-head / output bounds:

| Model | Accumulator (74 rows) | Dense | Output |
| --- | --- | --- | --- |
| compact | 247,103 | 238,645,611 | 167,827,512 |
| small | 234,018 | 460,231,467 | 190,774,394 |

Every value is below signed int32 capacity. The transient proof allows two full
37-feature sets during sorted changes. Earlier build sidecars report the final
37-row bound; [verification.json](docs/nnue-v2/verification.json) records the
stronger transient re-audit. Integer scalar/SIMD outputs matched exactly on the
full corpus before the SIMD prototype was removed.
Archived SIMD prototypes also passed forced portable-dispatch checks on both
models and all 22,165 positions: [fallback evidence](docs/nnue-v2/prototype-fallback.json).

Regression evidence:

- Full suite: **1135 passed in 88.97s (0:01:28)**; final shared-opening
  harness: **5 passed in 1.46s**. A final focused run of the new tools, native
  audit, kernel switching and match harness passed **20 tests in 11.51s**.
- UBSan: **235,136 real/sibling/null transitions** across both models and kernels;
  float max lane error 0.00000155, integer lanes exact. Checks include full
  37-feature positions, pinned/legal EP, rights, castling and underpromotion.
- Both finalists preserved original moves, scores, nodes and PV at fixed depth
  and fixed nodes on all ten categories. Incremental/rebuild, terminal/draw,
  mixed kernels, TT/evaluator isolation and cancellation passed. See
  [release](docs/nnue-v2/search-verification.json) and
  [sanitized search checks](docs/nnue-v2/sanitized-search.json).
- Classical fixed-depth trees were unchanged; timed differences varied by
  position with no consistent gain/loss in the [control](docs/nnue-v2/classical-regression.json).
- Both models passed real Pygame/UCI workers at all five presets, stale undo/new
  replies and Minimax/alpha-beta comparison. Real Windows launches played d4;
  [Compact](docs/nnue-v2/screenshots/desktop-compact.png) and
  [Small](docs/nnue-v2/screenshots/desktop-small.png) frames were visually inspected.
  Automated GUI checks use SDL dummy; desktop checks were startup/render smoke
  runs, not a claim of manual mouse testing. Dependency checks passed.

## E. Performance results

Median head latency across categories (three trials/category); raw evaluations
per second exclude feature/accumulator/search work. NPS ratios are geometric
means of the nine nonterminal fixed-time position medians.

| Model | Kernel | Head ns | Head calls/s | NPS vs original | Frame bytes |
| --- | --- | --- | --- | --- | --- |
| compact | original | 320.80 | 3.12M | 1.000× | 2200 |
| compact | scalar | 48.65 | 20.55M | 1.445× | 664 |
| compact | quant | 85.40 | 11.71M | 1.446× | 664 |
| small | original | 1347.88 | 0.74M | 1.000× | 2200 |
| small | scalar | 119.82 | 8.35M | 2.493× | 1176 |
| small | quant | 333.76 | 3.00M | 1.961× | 1176 |

A separate confirmation includes the actual integer White-score endpoint, including NNUE POV conversion, mate-band clamp and rounding. It still uses a cached accumulator, rather than a full refresh:

| Evaluator | White-score ns | Complete cached eval/s |
| --- | --- | --- |
| classical | 110.86 | 9.02M |
| v1 | 323.55 | 3.09M |
| original-compact | 327.98 | 3.05M |
| scalar-compact | 55.71 | 17.95M |
| quant-compact | 94.23 | 10.61M |
| original-small | 1373.26 | 0.73M |
| scalar-small | 125.25 | 7.98M |
| quant-small | 339.78 | 2.94M |

See [white-evaluation.json](docs/nnue-v2/white-evaluation.json) for all repeated trials. These later measurements are not subtracted from the earlier head timings to infer component costs.


200ms search **median NPS / completed depth**:

| Category | Classical | Compact float | Small float |
| --- | --- | --- | --- |
| opening | 2.85M / 9 | 1.93M / 8 | 1.47M / 8 |
| quiet_middlegame | 2.66M / 7 | 2.10M / 7 | 1.47M / 7 |
| tactical | 2.73M / 6 | 1.59M / 6 | 1.12M / 6 |
| king_attack | 0.16M / 2 | 0.33M / 2 | 0.16M / 2 |
| pawn_endgame | 5.91M / 11 | 3.83M / 11 | 2.62M / 10 |
| piece_endgame | 3.76M / 9 | 2.83M / 8 | 1.64M / 8 |
| imbalance | 4.48M / 8 | 2.79M / 7 | 1.77M / 7 |
| castling_rights | 5.32M / 9 | 2.92M / 9 | 1.77M / 8 |
| promotion | 4.77M / 10 | 3.11M / 10 | 1.94M / 9 |
| en_passant | 4.95M / 10 | 2.98M / 9 | 1.84M / 9 |

Combined recovered NPS: **44.5% Compact**,
**149.3% Small**. Their throughput is
respectively 64.8% and
42.5% of the classical baseline in this suite.
Different evaluators produce different trees; these are practical throughput
observations, not proof that node quality is equivalent.

Full-process working sets during sampled 500ms searches were about 17.7–17.9MiB
for NNUE; TT/process overhead dominates. See [memory samples](docs/nnue-v2/memory.json).
Original models are 105,518 bytes (Compact) and 218,029 (Small). Derived integer
constants are 52,260 and 108,612 bytes but coexist with float/reference weights,
so the retained binary does **not** halve its deployment footprint. Exact binary
sizes/hashes/builds can be checked with the record paths and build sidecars.

| Model | Export bytes | Original executable bytes | Retained executable bytes |
| --- | --- | --- | --- |
| compact | 105518 | 841728 | 911360 |
| small | 218029 | 953344 | 1092608 |

Quantized Compact was mixed by position; Small was consistently slower than
float. Float is preferred for both. Explicit SIMD failed to give a useful
end-to-end improvement over the compiler-vectorized portable implementation.
Repeated raw timings and all fixed-node/time results are in
[final-performance.json](docs/nnue-v2/final-performance.json).

## F. Playing-strength results

The [fixed plan](docs/nnue-v2/match-plan.json) ran **366 games**:
six smoke games at 25ms, 300 primary games at 50ms and 60 longer games at 200ms.
All used optimized scalar float, identical production search defaults, one
thread, Hash=16MB, paired openings/reversed colors, seed 20261016 and the same
[50-opening book](docs/nnue-v2/openings.json). No evaluator-based opening filter
or outcome-based stopping was used. Each match records exact binaries, models,
options, limits and every move; checkpoints support recovery.
The 200ms cohorts use the first ten book pairs, whereas the primary cohorts use
all fifty; cross-control score differences are not a clean thinking-time effect.

Candidate is the first name: Compact/Small versus classical, or Compact versus
Small. Draw rules use python-chess `claim_draw=True`; no evaluation adjudication.
A cap of 240 additional plies is **unfinished**, never a draw. Reported scores
exclude unfinished games; paired intervals exclude incomplete pairs. Caps can
bias conditional scores and are reported explicitly.

Intervals are conservative nominal 95% Hoeffding bounds on independent bounded
opening-pair scores, transformed by logistic relative Elo. Four opening families
are not a universal independent chess sample. Endpoints can be unbounded;
these are estimates against this opponent/protocol, not a calibrated rating.
The raw summary helper's legacy opening-filter caveat is generic; the recorded
`opening_book_sha256`/`opening_filter` fields identify the actual shared protocol.

| Match | ms | W/D/L | Capped | Score | Relative Elo | Paired 95% bound |
| --- | --- | --- | --- | --- | --- | --- |
| primary-compact-classical | 50 | 14/28/57 | 1 | 28.3% | -162 | [-409, -18] |
| primary-small-classical | 50 | 16/26/58 | 0 | 29.0% | -156 | [-386, -12] |
| primary-compact-small | 50 | 49/24/27 | 0 | 61.0% | +78 | [-58, +243] |
| long-compact-classical | 200 | 6/5/9 | 0 | 42.5% | -53 | [−∞, +307] |
| long-small-classical | 200 | 6/4/10 | 0 | 40.0% | -70 | [−∞, +275] |
| long-compact-small | 200 | 8/6/6 | 0 | 55.0% | +35 | [-345, +671] |

Average completed depth / pooled nodes per engine-reported second:

| Match | Candidate depth / NPS | Opponent depth / NPS |
| --- | --- | --- |
| primary-compact-classical | 5.63 / 1.12M | 6.03 / 1.72M |
| primary-small-classical | 5.26 / 0.78M | 6.01 / 1.84M |
| primary-compact-small | 6.00 / 1.62M | 5.62 / 1.04M |
| long-compact-classical | 7.32 / 1.50M | 7.69 / 2.20M |
| long-small-classical | 6.51 / 0.80M | 7.36 / 1.92M |
| long-compact-small | 7.26 / 1.54M | 6.81 / 0.97M |

These averages follow different game trajectories. Use the fixed-position
benchmarks for throughput comparisons between evaluators.

Game termination reasons:

| Match | Reasons |
| --- | --- |
| primary-compact-classical | checkmate: 71; insufficient_material: 1; ply cap (unfinished): 1; threefold_repetition: 27 |
| primary-small-classical | checkmate: 74; threefold_repetition: 26 |
| primary-compact-small | checkmate: 76; threefold_repetition: 24 |
| long-compact-classical | checkmate: 15; threefold_repetition: 5 |
| long-small-classical | checkmate: 16; insufficient_material: 1; threefold_repetition: 3 |
| long-compact-small | checkmate: 14; threefold_repetition: 6 |

- **primary-compact-classical:** nominal paired bound favors the opponent; 49 complete pairs, 1 capped games.
- **primary-small-classical:** nominal paired bound favors the opponent; 50 complete pairs, 0 capped games.
- **primary-compact-small:** paired uncertainty includes equal strength; 50 complete pairs, 0 capped games.
- **long-compact-classical:** paired uncertainty includes equal strength; 10 complete pairs, 0 capped games.
- **long-small-classical:** paired uncertainty includes equal strength; 10 complete pairs, 0 capped games.
- **long-compact-small:** paired uncertainty includes equal strength; 10 complete pairs, 0 capped games.

All JSON/PGNs were independently replayed (**36,987 legal plies**), outcome/claim/cap logic checked,
paired colors/openings verified and summaries recomputed; see
[replay verification](docs/nnue-v2/match-verification.json). Smoke results are
validation only. Same-model optimized-versus-original matches were not run:
original and optimized fixed-node/depth trees matched exactly, providing the
numerical check. The speed-to-strength benefit was not separately quantified.
Quantization was not promoted or used in tournaments, so no quantized Elo claim
is made. Historical v1 25/100ms results used other conditions and are not direct
v2 Elo comparators.

## G. Final recommendation

- **Faster model:** Compact. Its optimized raw head and full-search throughput
  beat Small. Keep both exports, but use Compact/`scalar` for latency-sensitive
  NNUE experiments; `auto` chooses the same kernel.
- **Teacher accuracy:** Compact has slightly lower primary test teacher MSE
  (0.011022 vs 0.011128). Small won the original two-seed validation selection
  (blended MSE 0.013153 vs 0.013253) and has slightly lower test cp MAE
  (143.53 vs 143.93). MSE here is in the training sigmoid-score space, not
  squared centipawns. See the [training report](StockBear_NNUE_training/reports/v2/NNUE_V2_RESULTS.md).
  These close metrics do not select a chess-strength winner.
- **Playing strength:** Compact scored 61.0% against Small at 50ms/move (49/24/27, 0 capped). Compact scored 55.0% against Small at 200ms/move (8/6/6, 0 capped). Use the measured paired bounds above. Where a
  bound includes equal strength, the sample does not establish a winner.
  Short-control point estimates must not be promoted to definitive Elo gains;
  the smaller 200ms cohorts are especially uncertain.
- **Quantization:** small numerical error, no dependable benefit over optimized
  float; keep it experimental and opt-in. Original float remains preferred.
- **SIMD:** explicit prototypes passed correctness but did not justify their
  complexity. Keep the portable ordered-neuron loop and normal compiler
  vectorization. All validated prototype evidence remains available.
- **Classical competitiveness:** NNUE remains slower in this position suite;
  Compact scored 28.3% against classical at 50ms/move. Small scored 29.0% against classical at 50ms/move. Compact scored 42.5% against classical at 200ms/move. Small scored 40.0% against classical at 200ms/move. Playing competitiveness is answered by these matches,
  with their caps and uncertainty, rather than speed or teacher loss alone.
  Classical stays the product default as requested.
- **Next investigation (hypotheses):** reduce measured state-bookkeeping cost,
  consider lazy accumulator materialization at actual evaluation nodes, and
  test broader opening suites/longer controls. Compare existing selective-search
  switches off/on to diagnose evaluator/search interactions before changing
  search margins. Further training changes should
  follow strength evidence and preserve the grouped holdout contract. No such
  search, training or calibration changes were made here.

### Reproduction and checkpoints

See the [reproduction guide](docs/nnue-v2/README.md) for builds, kernels, complete
held-out checks, benchmarks and dataset requirements. Execute
`python -m tools.run_nnue_v2_matches` to resume/verify the frozen schedule;
it skips completed, verified records and never overwrites them. Choose a new
output directory/plan for a new experiment. `python -m tools.report_nnue_v2`
requires all scheduled games and refuses to overwrite this report.

| Checkpoint | Purpose |
| --- | --- |
| `1b1794e` / baseline tag | Original search/evaluators/trained exports |
| `01b38ca` | Original baselines and profiler |
| `07a663d` | Move-derived accumulator experiment |
| `0724f50` | Ordered portable float32 neurons |
| `ca19bd2` | Validated float AVX2 prototype |
| `78e22ac` | Integer scalar/AVX2 prototype and error measurements |
| `0d37b15` | Retained kernels, regression evidence, frozen match schedule |

Experiment records sometimes name the preceding Git HEAD while changes were
being validated. This checkpoint map, exact binary/model hashes and source hashes
in later build sidecars identify the tested state; a preceding HEAD field alone
must not be mistaken for a clean-source claim. Original model exports, historical
v1/audit records and pinned vendor files were preserved.
