# StockBear Compact v2 NNUE — Search Performance Diagnosis

2026-10-15 · Completed diagnostic study · Production search, model weights and classical defaults preserved.

## 1. Executive findings and verified baseline

All **190 scheduled games** were played: 189 terminal results and one capped game. No cohort was extended. Classical was favored at 50ms and 200ms on this book; the 500ms and 1000ms results remain exploratory.

The clearest measured disadvantage is **whole-search throughput**: NNUE achieved 66–72% of classical NPS in timed fixed-position tests and completed about 0.33–0.46 fewer nominal plies. This is a plausible contributor to the match gap, not a measured causal allocation of Elo. Equal-node and equal-depth reference analysis **did not establish a general NNUE move-quality deficit**. Five single-switch ablations found no large, consistent evaluator-specific pruning failure.

The matched first-ten-pair score changed from **45.0% at 50ms to 47.5% at 1000ms**: +2.5 percentage points, with a paired 95% bootstrap interval of **−30.0 to +32.5 points**. Longer thinking time did not produce a statistically supported improvement in this sample. The middle controls were nonmonotonic.

Copying alone is not established as the bottleneck. A warm 256-byte lane copy took a median 1.74ns, while move-derived state preparation took 44.53ns. A naive lazy scheme that caches only evaluated ancestors would require **2.50×** the current row-update work in the measured traces. Any lazy prototype needs intermediate-state reuse.

The study used the same preserved executable for both players, changing only `Evaluator`; Hash=16MB, scalar float32, incremental NNUE and all production search defaults. It used **Compact v2 32/16**, not v1 or Small v2:

- Model SHA256: `788b865a15dbdeeb3e03b7493f8155fd19d6c73b9b0873453ad16fba51a65aa7`.
- Match executable SHA256: `d55439565b86d950eaac43fbfb29e6614c18e7f8192e3c6fb7f489452dec6c9a`.
- Opening-book SHA256: `6ae0319c30bf2226ff9ce1b0909feac8bdc1bef0e7bebc27b27c34474593a2b3`.
- Baseline tag: `nnue-v2-diagnosis-baseline-1b08943`.
- Hardware: 13th Gen Intel(R) Core(TM) i5-13420H, 12 logical CPUs, Windows, Python 3.11.8, Zig 0.13 C++17 `-O2 -ffp-contract=off`. One active search at a time; no affinity/frequency lock. No simultaneous heavy benchmarks during matches.

## 2. Full tournament results, separately by control

W/D/L/U are from NNUE's perspective. Score and Elo point estimates condition on completed games. Intervals keep both colors together and resample opening pairs 20,000 times, seed 20261017. For the capped cohort they also allow its unknown result to score anywhere from 0 to 1; those are approximate bootstrap/censoring sensitivity intervals, not guaranteed coverage under arbitrary missingness.

| ms/move | Scheduled | W | D | L | U | Completed-game score | Relative Elo | Paired 95% Elo interval |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 50 | 80 | 17 | 24 | 39 | 0 | 36.25% | -98 | [-152, -44] |
| 200 | 60 | 13 | 17 | 30 | 0 | 35.83% | -101 | [-176, -29] |
| 500 (exploratory) | 30 | 9 | 10 | 10 | 1 | 48.28% | -12 | [-95, +83] |
| 1000 (exploratory) | 20 | 9 | 1 | 10 | 0 | 47.50% | -17 | [-191, +168] |

At 500ms the full 30-game score is only identified as **46.7–50.0%**, rather than an assumed draw. Opening-family cluster bootstrap score intervals were 30.0–43.1%, 26.6–46.7%, 35.7–57.1% and 25.0–72.5% respectively; the 500ms family interval uses complete pairs. Conservative bounded-pair intervals and complete-case estimates are also in the summary JSON. Related opening variants and limited samples restrict generalization; these are conditional match Elo estimates.

All work columns below are **NNUE / classical**. NPS is total searched nodes divided by total engine-reported search time. Move wall time also includes protocol overhead. Means cover all searched moves, including the capped game; depth is the last completed iteration, not selective depth.

| ms | Mean depth | Median depth | Mean nodes/move | Aggregate NPS | Mean actual ms/move |
| --- | --- | --- | --- | --- | --- |
| 50 | 6.15 / 6.61 | 6 / 7 | 101k / 146k | 2.11M / 3.07M | 49.4 / 49.1 |
| 200 | 7.51 / 7.93 | 8 / 8 | 417k / 603k | 2.18M / 3.17M | 192.7 / 192.1 |
| 500 | 8.02 / 8.45 | 8 / 9 | 904k / 1286k | 1.90M / 2.72M | 476.7 / 475.4 |
| 1000 | 8.00 / 8.44 | 8 / 9 | 1635k / 2304k | 1.79M / 2.53M | 916.3 / 912.3 |

| ms | Checkmate | Threefold | Fifty-move | Unfinished cap |
| --- | --- | --- | --- | --- |
| 50 | 56 | 23 | 1 | 0 |
| 200 | 43 | 17 | 0 | 0 |
| 500 | 19 | 10 | 0 | 1 |
| 1000 | 19 | 1 | 0 | 0 |

There were no other terminations, zero-depth fallbacks or moves exceeding 150% of requested wall time. Early proven mates can finish before their allotted time. Recorded game wall time totaled **71.5 minutes**; the two-game pilot underestimated later game lengths. All 19,158 opening/played plies were independently replayed against JSON and PGN.

The book has 40 evaluator-neutral positions from 20 opening families, with two seeded legal quiet continuations each. No evaluator or outcome filter was used. Prefixes were exactly 40/30/15/10 pairs; each pair reversed colors. Games used claimable draws and a uniform cap of 240 searched plies, with no evaluation adjudication. One cap was 3.3% of the 500ms cohort and 0.53% overall, so the primary cap stayed fixed. Offline Stockfish rated the capped final position +290cp for White at 300k nodes, with halfmove clock 35; this neither proves a win nor changes its unfinished result.

## 3. Time-control trend on the same ten opening pairs

This table uses pairs 1–10 at **every** control. It does not compare the full 80-game cohort against the full 20-game cohort as matched samples.

| ms/move | W–D–L–U | All-20-game score / bounds | Paired 95% sensitivity interval |
| --- | --- | --- | --- |
| 50 | 6–6–8–0 | 45.0% | [30.0%, 60.0%] |
| 200 | 3–5–12–0 | 27.5% | [12.5%, 42.5%] |
| 500 | 7–8–4–1 | 55.0–60.0% (unknown outcome) | [45.0%, 72.5%] |
| 1000 | 9–1–10–0 | 47.5% | [25.0%, 72.5%] |

Joint resampling keeps each opening's four-control results together. The all-ten 1000ms-minus-50ms endpoint was +2.5 points, interval −30.0 to +32.5. The log-time slope was bounded at +6.69 to +8.14 score points per tenfold time increase because of the single unknown result; its bootstrap/censoring envelope was **−14.87 to +26.74**. Both uncertainty ranges include zero. No sustained upward trend or indefinite Elo extrapolation is supported.

For transparency, the nine pairs completed at all four controls give a supplementary endpoint of +8.33 points, interval −27.78 to +38.89, paired sign-flip p=0.765625. Excluding the capped pair changes the estimate; it is not the primary all-ten analysis. Time controls ran serially, so common openings do not remove possible hardware drift.

[Five matched trend plots: PNG](docs/nnue-v2-diagnosis/matched-trends.png) · [SVG](docs/nnue-v2-diagnosis/matched-trends.svg). Capped scores have ranges rather than imputed point estimates. Game NPS and depth reflect different played positions; fixed-FEN tests below isolate position composition better.

## 4. Throughput, depth and fixed-work comparisons

The legal 24-position suite has two fixtures per requested category: openings, quiet middle, tactics, king attacks, imbalances, pawn/piece endings, passers, promotions, zugzwang, defense and planning. These are selected examples, not a random population; categories overlap and some fixtures have material advantages. Three serial trials alternated evaluator order. There were **1,296 searches** at 50/200/1000ms, 25k/100k/400k nodes and nominal depths 3/4/5.

NPS ratios below use per-FEN median trials and their geometric mean; two short mate fixtures and sub-10ms measurements are excluded from NPS aggregates only.

| Equal time (ms) | NNUE/classical NPS | Mean depth difference | Mean nodes NNUE/classical |
| --- | --- | --- | --- |
| 50 | 66.2% | -0.46 | 85k / 133k |
| 200 | 70.6% | -0.33 | 381k / 525k |
| 1000 | 72.2% | -0.38 | 1894k / 2648k |

At 100k and 400k nodes the NPS ratios were 69.5% and 70.1%; mean wall times were 58.4/42.0ms and 222.2/157.7ms. Mean completed-depth difference at those node budgets was only +0.04 plies. Thus NNUE's lower rate does not imply proportionately lower productivity per node.

At nominal depth 5, mean nodes were 19,134/24,702 and mean wall time 15.97/15.96ms. Many depth-3/4 searches were too short for meaningful millisecond NPS comparisons. Equal nodes and equal nominal depth still produce different selective trees, quiescence work and horizons; neither makes search quality equivalent.

## 5. Independent move quality

Local **Stockfish 19** analyzed each fixture root at 300k nodes, Threads=1, Hash=64MB, full strength, no tablebases and fresh hash. Every distinct candidate—including Stockfish's root choice—then received a separate 300k-node child search with identical settings, preserving the original root side's score perspective. This comprised 24 roots and 69 distinct child analyses. Mate scores remain separate.

CPL uses the reference move's **child** score minus the candidate child's score, clipped at zero; raw negative losses remain recorded as finite-budget inconsistencies. Root and child searches have different contexts and are not silently equated. The primary paired CP contrast below directly subtracts the two candidate child scores. Positive values favor classical; negative values favor NNUE. Twenty-one positions have finite scores for this contrast; the three mate-reference positions are handled separately. Quality uses the first trial, not three pseudo-independent samples.

| Budget | Same move | Paired CP positions | Classical−NNUE child cp | Illustrative paired 95% interval | Reference prefers NNUE/classical (all 24) |
| --- | --- | --- | --- | --- | --- |
| time 50 | 10/24 | 21 | -7.1 | [-17.5, +1.2] | 5 / 6 |
| time 200 | 12/24 | 21 | -5.2 | [-12.8, +0.9] | 5 / 5 |
| time 1000 | 13/24 | 21 | -1.4 | [-10.1, +6.0] | 3 / 6 |
| nodes 25000 | 12/24 | 21 | -6.0 | [-15.8, +2.0] | 5 / 4 |
| nodes 100000 | 11/24 | 21 | -4.0 | [-12.3, +2.4] | 4 / 6 |
| nodes 400000 | 13/24 | 21 | -5.5 | [-13.0, +0.4] | 5 / 4 |
| depth 3 | 11/24 | 21 | +13.1 | [-5.2, +38.4] | 3 / 8 |
| depth 4 | 11/24 | 21 | -0.4 | [-11.7, +10.1] | 4 / 7 |
| depth 5 | 11/24 | 21 | -6.0 | [-15.9, +2.0] | 5 / 6 |

At 100k nodes, mean CPL was 2.90cp for NNUE and 8.14cp for classical on the 21 finite-reference cases; best-move agreement with the reference was 17/24 versus 14/24. At 400k nodes mean CPL was 1.76/4.67cp. There was one ≥100cp NNUE loss at depth 3, resolved by depth 4; no ≥300cp losses appeared. Neither evaluator lost a reference winning-mate indication in these fixtures. Probability-transformed losses and negative-loss counts are preserved in the machine-readable summary; the transform is descriptive, not a calibrated game-win probability.

Supplementary sampling selected 12 actual-game positions—one per phase/control from the first ten pairs—using the minimum seeded hash key, legal/material criteria and no scores/outcomes. Full move histories were retained. Both evaluators searched each at 100k/400k nodes; 12 more reference roots and 28 distinct child analyses used the same SF budget.

| Equal nodes | Finite CP positions / 12 | Classical−NNUE child cp | Illustrative paired interval | Reference prefers NNUE/classical |
| --- | --- | --- | --- | --- |
| 100000 | 10 | +23.5 | [-4.8, +61.4] | 2 / 4 |
| 400000 | 10 | -6.0 | [-23.6, +13.7] | 4 / 2 |

This sample is mixed and dependent, not evidence of equivalence or an Elo estimate. Together, the tests do **not** establish that NNUE generally chooses worse moves at equal nodes/depth. A global evaluation-quality explanation remains unproven, rather than ruled out. Stockfish is independent of StockBear's search but was also the NNUE teacher; its bounded analysis is not perfect ground truth.

As a separate static-score check, NNUE's mean absolute error against searched SF root scores was 237cp versus classical's 289cp on 21 finite cases. Different horizons confound those numbers, so they do not justify rescaling either evaluator. Training targets blend 90% teacher probability and 10% game result in sigmoid space, rather than minimizing raw CP error.

## 6. Single-feature search-heuristic interactions

**1,152 release searches** tested production and five individual switches, both evaluators, 200ms and 100k nodes, two trials. Other production options and thresholds stayed fixed. Disabled-feature counters were checked to be zero. No combined-off configuration or extra strength tournament was run.

CP columns are mean CPL change versus the corresponding production baseline, **200ms / 100k nodes**; positive is worse. NPS ratios use the median of two trials on 22 eligible FENs. Move changes and depth changes use the first 200ms trial. Full PV, node, stability and uncertainty records remain available.

| Disabled feature | NNUE ΔCPL cp | Classical ΔCPL cp | 200ms NPS NNUE/classical (% own baseline) | 200ms depth Δ NNUE/classical | 200ms changed moves NNUE/classical |
| --- | --- | --- | --- | --- | --- |
| no_lmr | -0.05 / +0.52 | +0.14 / +1.43 | 101.2% / 103.7% | -0.33 / -0.33 | 4 / 1 |
| no_null | +0.10 / +0.19 | +0.00 / -3.33 | 80.5% / 85.1% | -0.12 / +0.00 | 3 / 0 |
| no_futility | -0.10 / +0.00 | +0.00 / +0.00 | 92.4% / 94.2% | -0.12 / +0.00 | 2 / 0 |
| no_reverse_futility | -0.43 / +0.19 | +0.00 / +3.14 | 97.0% / 97.1% | -0.38 / -0.04 | 4 / 0 |
| no_aspiration | +2.48 / +1.95 | +0.00 / -3.33 | 96.3% / 99.8% | +0.04 / +0.08 | 4 / 0 |

No ablation showed a large, consistent NNUE quality recovery. Removing null moves reduced timed NPS to 80.5% of NNUE production without a quality improvement. Removing LMR lost roughly a third of a ply for both evaluators. Aspiration removal slightly worsened NNUE CPL in this small sample. The small futility/RFP changes do not justify production threshold changes. Switching a heuristic changes the tree, so increased NPS or reduced nodes alone is not playing-strength evidence.

Inspection found no razoring, SEE/delta quiescence pruning, static-evaluation move ordering or TT static-evaluation cache to ablate. SEE orders moves; TT entries contain search bounds. Quiescence's existing stand-pat and safety limits remain part of the search, without inventing a separate unsupported pruning switch.

## 7. Accumulator overhead and the lazy-materialization hypothesis

Release, counter-only and exclusive-clock builds ran three rotated trials on every FEN at 100k nodes and 200ms: **432 searches**. All fixed-node moves, PVs, scores, nodes and search counters matched exactly. The following counts pool 72 counter-build 100k-node searches, including the mate fixtures.

| Measured logical work | Value |
| --- | --- |
| Prepared/copy events per visited node | 0.9990 |
| Visited nodes requiring evaluation | 79.5% |
| Prepared frames never evaluated directly | 20.4% |
| Prepared frames with no own/descendant evaluation | 5.1% |
| Quiescence share of node visits | 72.9% |
| Unused first-use quiescence frames | 7.8% |
| Null-edge updates / all updates | 0.3% |
| Mean changed rows/update, one perspective | 2.292 |
| Root refreshes / visited nodes | 72 / 7,200,000 |
| Mean pending edges / rows at first evaluation | 3.41 / 7.19 |

There were 7,193,118 preparations/copies, 5,740,554 head calls and 16,483,179 changed rows in one-perspective accounting. Extra head calls beyond evaluated visits were only 15,012. Null updates were usually zero-delta, but only 0.29% of all updates. Refreshing roots is negligible at this workload.

A frame occupies **664 bytes**, and the fixed 65-frame stack 43,160 bytes. The active float lanes plus copied feature metadata carry **408 bytes/update**, not a whole 664-byte frame. Pooled logical copy payload was 2.935GB (5.870GB counting source reads and destination writes); weight-row reads were 4.220GB and accumulator row read/write operations 8.439GB. These are source-level byte estimates, **not measured DRAM traffic, cache misses or bandwidth**.

Five repeated warm native microbenchmarks per first category fixture (60 samples, 100k calls each) gave:

| Operation | Median ns/call | Observed range |
| --- | --- | --- |
| copy | 1.74 | 1.74–2.41 |
| move_update | 44.53 | 34.66–113.85 |
| refresh | 120.07 | 24.51–341.54 |
| head | 48.29 | 44.59–61.56 |
| classical | 99.21 | 47.71–159.11 |

The copy microbenchmark covers float lanes only; metadata and real search cache behavior differ. The head measures float side-to-move inference; final integer sign/clamp/rounding is outside that micro result. Classical micro evaluation is uncached, unlike production pawn-cache use.

For the identical 7.2M-node workload, wall times were 4.261s release, 4.408s counters and 9.300s clocks: +3.5% and +118.3% overhead. Clock-build exclusive shares were update/bookkeeping 20.16%, copy 8.10%, head 12.69% and other search 24.46%. Tiny scopes are strongly distorted by timing overhead; copy's 8.10% is **not** its release runtime share. Fresh TT construction precedes the scoped profile.

**Lazy assessment:** 20.4% of frames lack their own head call, but most still feed evaluated descendants. Only 5.1% are unused leaves. Caching only evaluated ancestors would reduce preparation/copy targets to 5,722,632, yet replay 41,163,714 rows versus 16,483,179 eagerly—**2.50× row work**. Pending chains reached 20 edges. These uncancelled, order-preserving trace sums are an analytical model, not an implemented benchmark. A useful prototype must retain intermediate states on reused paths; skipping all unused frames is not a free 20% gain. The allocated stack does not automatically shrink. No lazy implementation was added.

## 8. Search stability, tactics and recurring diagnostic behavior

Every completed iteration's PV, score and counters is stored in the raw records; `search-stability.json` adds increasing-budget sequences. At 400k nodes, mean best-move changes during deepening were **1.71 NNUE / 1.00 classical** across 24 fixtures. Score swings or PV changes alone are not tactical failures.

| Theme | Independently checked observation | Interpretation |
| --- | --- | --- |
| Shallow passed-pawn priority | `outside_passer`: depth-3 NNUE `g3f4` versus classical `c5c6`; SF child scores +732/+950cp. NNUE changes to `c5c6` at depth 4. | A real 218cp shallow preference gap; both choices retain a large advantage. Not a persistent passer blindness. |
| Score oscillation and aspiration work | `locked_center` NNUE scores by depths 1–7: 165, 337, 112, 278, 166, 270, 203cp; 19 retries and 49 PVS re-searches by 400k nodes. Classical had 2/19. Both always chose `e5f6`. | Recurring score instability can add work without harming the root move. It does not establish a king-safety defect. |
| Drawish pawn/zugzwang calibration | `white_blocked` and its opposite-color companion had SF scores 0 for both candidates, while 400k-node NNUE reported ±300cp and classical ±211cp. The pair is related, not two independent discoveries. | Both models overstate the advantage relative to this reference; NNUE more strongly here. SF did not rate either legal king choice worse. |
| Mixed king-attack/defense decisions | In `attack_complex`, depth-5 NNUE's `d4c5` was +717cp versus classical's +651cp. In `defend_complex`, low-budget NNUE was 16cp worse, but at 1000ms it was 40cp better. | No consistent one-way king-safety failure was demonstrated. |
| Long conversion / material imbalance | The single 500ms capped queen-versus-rook-and-bishop position retained a +290cp SF estimate for White after 240 searched plies. | A useful future conversion case, not proof of a win, draw or specific evaluator bug. |

The suite exposed a shallow passer error and score-calibration/stability issues, but no recurring severe tactical collapse. Both evaluators retained the tested winning-mate indications. Examples where the reference preferred NNUE are included deliberately; classical's move is not treated as the oracle.

## 9. Root-cause assessment

| Hypothesis | Evidence | Conclusion and confidence |
| --- | --- | --- |
| Lower throughput | Timed NPS 66–72% of classical; game throughput about 69–71%; fewer completed plies at equal time. | Strongly measured disadvantage and plausible contributor. Its share of the Elo gap is not identified. |
| Less depth | Equal-time gap roughly 0.33–0.46 plies; equal-node depth roughly neutral. | Throughput affects reached depth, but nominal depth/productivity varies with the tree. |
| Generally worse evaluation | Equal-work SF results were mixed or slightly favored NNUE, with broad paired intervals; one shallow passer error. | Global inferiority was not established. These small, selected samples can miss important game failures. |
| Pruning mismatch | Five individual ablations produced small CPL effects, no large rescue and some substantial throughput/depth costs. | No demonstrated catastrophic interaction; thresholds remain a hypothesis for a broader held-out study. |
| Accumulator copying / maintenance | Cheap isolated copies, material preparation cost, 20.4% no-own-eval frames but 5.1% wholly unused leaves. | Maintenance is a plausible speed target; memcpy alone and naive lazy replay are not established solutions. |
| Representation / capacity | The trained dual-perspective piece-square/state contract passed parity; no king-relative or architecture ablation occurred. | No evidence isolates representation as the cause. Increasing capacity may further reduce throughput. |
| Longer-time recovery | Same-ten endpoint +2.5 points, interval −30 to +32.5; nonmonotonic middle controls. | No supported catch-up trend; 500ms/1000ms remain exploratory. |

The strongest defensible answer is **a measurable search-rate disadvantage with unresolved game-specific evaluation/policy effects**, rather than a proven universally bad network or a broken accumulator. Equal-node tests do not reproduce an entire game's error accumulation, and this investigation cannot assign causal percentages to speed, model quality and policy.

## 10. Ranked next steps

| Rank | Next investigation | Expected benefit | Confidence | Complexity / principal risk |
| --- | --- | --- | --- | --- |
| 1 | Profile whole-search paths and real state-preparation traces before more head/SIMD work. | Potential throughput improvement; no quantified Elo promise. | High that a rate gap exists; medium on recoverable cost. | Medium; require release measurements and exact parity. |
| 2 | Expand an outcome-blind offline corpus of actual losing/conversion/drawish positions; validate teacher targets and calibration. | Better evidence for a targeted next training run. | Medium; current samples do not establish global NNUE inferiority. | Medium; grouped holdout and phase diversity, avoid tuning on this report's examples. |
| 3 | Prototype deferral only with intermediate-cache reuse and explicit TT/terminal boundaries. | A small preparation saving is plausible; naive replay may regress badly. | Medium for the opportunity, low for net speed gain. | Medium–high; preserve root refresh, fixed White/Black sums, null/draw context, delta arithmetic order and child isolation. |
| 4 | Evaluate NNUE-specific pruning thresholds on a fresh held-out position corpus, then validate a promising candidate separately. | Uncertain; current single-switch effects are small. | Low–medium. | Medium; selective correctness and overfitting risks. No production switch is recommended off now. |
| 5 | Defer king-relative features or a larger model until a controlled feature/quality/throughput comparison supports them. | Unknown; no consistent king-safety failure was found here. | Low. | High; retraining, a new feature contract and possible NPS loss. Preserve v2 as the reference. |
| 6 | If a concrete future candidate warrants it, predeclare another paired validation budget. | Greater decision confidence, not an optimization itself. | High about current uncertainty. | Runtime cost; no games were automatically added to this study. |

### Verification, artifacts and reproduction

- **1144 passed in 104.95s (0:01:44)**, using a fresh ordinary v1 build for the legacy suite's model-specific expectations; every diagnostic/performance experiment used Compact v2.
- 96 depth/node cases across five Compact builds matched moves, scores, PVs, nodes, selective depth and search counters. The uninstrumented rebuilt `.text` section was byte-identical to the preserved executable: `2fcdef4e1aa35e8807b6cb05dbfe752625760e535f241c644e9eaeaa23b70d1e`.
- Counter and UBSan builds each matched all 22,165 held-out/random/extreme outputs exactly; each passed 128 trained goldens (maximum 0.000202cp difference), 31,876 real/sibling transitions and 26,908 null transitions, plus the synthetic counter oracle.
- Cancellation, terminal/draw handling, evaluator switching and fresh TT checks passed. An initial harness assertion expected `None` instead of the valid falsy null-move representation of UCI `0000`; correcting that assertion required no engine change or experiment rerun.
- Automated Pygame/UCI worker checks passed across all time presets, undo/new stale-result rejection and minimum layout. A real Windows launch played a validated Compact v2 move and produced the visually inspected [desktop frame](docs/nnue-v2-diagnosis/gui-desktop.png); automated checks are separately labeled [GUI verification](docs/nnue-v2-diagnosis/gui-verification.json).

The [study guide](docs/nnue-v2-diagnosis/README.md) documents prepare, pilot, resume, fresh output roots and local prerequisites. To inspect/resume this frozen schedule and run the serial follow-up:

```powershell
.\.venv\Scripts\python.exe -m tools.run_nnue_diagnosis_matches
.\.venv\Scripts\python.exe -m tools.run_nnue_diagnosis_pipeline --skip-builds
```

Completed raw experiments are retained, not replayed by these commands. A fresh reproduction must use new `STOCKBEAR_DIAGNOSIS_ROOT` and `STOCKBEAR_DIAGNOSIS_ARTIFACTS` paths plus a matching `STOCKBEAR_DIAGNOSIS_ENGINE`, as described in the guide. Held-out SQLite data, Stockfish and plotting dependencies are local prerequisites; no model or training pipeline was changed.

Evidence: [match plan](docs/nnue-v2-diagnosis/match-plan.json), [full JSON/CSV summary](docs/nnue-v2-diagnosis/tournament-summary.json), [CSV](docs/nnue-v2-diagnosis/tournament-summary.csv), [record audit](docs/nnue-v2-diagnosis/record-audit.json), [controlled searches](docs/nnue-v2-diagnosis/controlled-searches.json), [reference moves](docs/nnue-v2-diagnosis/stockfish-quality.json), [paired position summary](docs/nnue-v2-diagnosis/position-summary.json), [game sample](docs/nnue-v2-diagnosis/tournament-position-quality.json), [ablations](docs/nnue-v2-diagnosis/ablations.json), [ablation throughput](docs/nnue-v2-diagnosis/ablation-throughput.json), [accumulators](docs/nnue-v2-diagnosis/accumulator-profile.json), [stability](docs/nnue-v2-diagnosis/search-stability.json), [native correctness](docs/nnue-v2-diagnosis/correctness.json), [verification](docs/nnue-v2-diagnosis/verification-summary.json), and [output manifest](docs/nnue-v2-diagnosis/output-manifest.json). Per-control JSON/PGN files use `50ms`, `200ms`, `500ms` and `1000ms` basenames.

All earlier reports remain separate. The four raw match summaries preserve a legacy prose reference to an own-evaluator filter; the authoritative frozen book/source/hash prove that no such filter was used here. Future runs now label their book context correctly while keeping old records verifiable.
