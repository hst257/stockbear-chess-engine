"""Render the frozen investigation's tables and evidence-based interpretation."""
from __future__ import annotations

import json
import math
from pathlib import Path

from tools.analyze_nnue_diagnosis import elo
from tools.nnue_diagnosis import ROOT, sha


def read(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def table(headers: list[str], rows: list[list]) -> str:
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"] +
                     ["| " + " | ".join(str(v) for v in row) + " |" for row in rows])


def percent(value: float) -> str:
    return f"{100 * value:.1f}%"


def rating(value: float | None, low: bool = False) -> str:
    return f"{value:+.0f}" if value is not None else "−∞" if low else "+∞"


def main() -> None:
    output = Path("NNUE_V2_SEARCH_DIAGNOSIS.md")
    if output.exists():
        raise ValueError("Report exists; edit it explicitly or choose a fresh study")
    identity = ROOT / "report-inputs.json"
    if not identity.exists():
        raise ValueError("This narrative describes the frozen study; new runs need a fresh interpretation and input manifest")
    for name, digest in json.loads(identity.read_text(encoding="utf-8"))["sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError(f"Frozen report input changed: {name}; reassess the interpretation before rendering")
    plan, tournament, throughput = read("match-plan.json"), read("tournament-summary.json"), read("throughput-summary.json")
    quality, profile = read("position-summary.json"), read("accumulator-profile.json")
    game_quality, correct, verification = read("tournament-position-quality.json"), read("correctness.json"), read("verification-summary.json")
    audit, ablation_nps = read("record-audit.json"), read("ablation-throughput.json")
    assert sum(r["games"] for r in tournament["full"].values()) == 190
    assert correct["release_machine_code_identical"]
    prefix = "docs/nnue-v2-diagnosis/"
    outcomes, work, terminations, matched = [], [], [], []
    for ms, row in tournament["full"].items():
        label = ms + (" (exploratory)" if row["exploratory"] else "")
        lo, hi = row["paired_censoring_bootstrap_95_envelope"]
        outcomes.append([label, row["games"], row["wins"], row["draws"], row["losses"], row["unfinished"], f"{100*row['score']:.2f}%",
                         rating(row["relative_elo"]), f"[{rating(elo(lo), True)}, {rating(elo(hi))}]"])
        n, c = row["nnue"], row["classical"]
        work.append([ms, f"{n['mean_completed_depth']:.2f} / {c['mean_completed_depth']:.2f}",
                     f"{n['median_completed_depth']:g} / {c['median_completed_depth']:g}",
                     f"{n['mean_nodes']/1000:.0f}k / {c['mean_nodes']/1000:.0f}k",
                     f"{n['aggregate_nps']/1e6:.2f}M / {c['aggregate_nps']/1e6:.2f}M",
                     f"{n['mean_wall_seconds']*1000:.1f} / {c['mean_wall_seconds']*1000:.1f}"])
        counts = row["termination_counts"]
        terminations.append([ms, counts.get("checkmate", 0), counts.get("threefold_repetition", 0), counts.get("fifty_moves", 0), row["unfinished"]])
    for ms, row in tournament["matched_first_ten"].items():
        lo, hi = row["unfinished_worst_best_score"]
        score = percent(row["score"]) if not row["unfinished"] else f"{100*lo:.1f}–{100*hi:.1f}% (unknown outcome)"
        ci = row["paired_censoring_bootstrap_95_envelope"]
        matched.append([ms, f"{row['wins']}–{row['draws']}–{row['losses']}–{row['unfinished']}", score,
                        f"[{100*ci[0]:.1f}%, {100*ci[1]:.1f}%]"])
    speed = [[r["budget"], percent(r["geometric_mean_nps_ratio"]), f"{r['mean_depth_difference']:+.2f}",
              f"{r['nnue_mean_nodes']/1000:.0f}k / {r['classical_mean_nodes']/1000:.0f}k"]
             for r in throughput["summary"] if r["mode"] == "time"]
    decisions = []
    for r in quality["evaluator_comparisons"]:
        if r["experiment"] != "controlled":
            continue
        ci = r["direct_paired_position_bootstrap_95"]
        decisions.append([f"{r['mode']} {r['budget']}", f"{r['same_move']}/24", r["direct_cp_positions"],
                          f"{r['mean_direct_classical_minus_nnue_child_cp']:+.1f}", f"[{ci[0]:+.1f}, {ci[1]:+.1f}]",
                          f"{r['reference_prefers_nnue']} / {r['reference_prefers_classical']}"])
    effects = {(r["configuration"], r["evaluator"], r["mode"]): r for r in quality["ablation_effects"]}
    nps = {(r["configuration"], r["evaluator"], r["mode"]): r["geometric_mean_nps_ratio_to_production"] for r in ablation_nps["summary"]}
    ablations = []
    for name in ("no_lmr", "no_null", "no_futility", "no_reverse_futility", "no_aspiration"):
        a, b = effects[name, "nnue", "time"], effects[name, "nnue", "nodes"]
        c, d = effects[name, "classical", "time"], effects[name, "classical", "nodes"]
        ablations.append([name, f"{a['mean_loss_cp_change']:+.2f} / {b['mean_loss_cp_change']:+.2f}",
                          f"{c['mean_loss_cp_change']:+.2f} / {d['mean_loss_cp_change']:+.2f}",
                          f"{100*nps[name,'nnue','time']:.1f}% / {100*nps[name,'classical','time']:.1f}%",
                          f"{a['mean_depth_change']:+.2f} / {c['mean_depth_change']:+.2f}",
                          f"{a['move_changes']} / {c['move_changes']}"])
    counts = profile["aggregate_fixed_nodes"]["counters"]["counts"]
    replay = counts["pending_rows"] / counts["delta_rows"]
    release_wall = profile["aggregate_fixed_nodes"]["release"]["wall_seconds"]
    counter_wall = profile["aggregate_fixed_nodes"]["counters"]["wall_seconds"]
    clock_wall = profile["aggregate_fixed_nodes"]["clock_profile"]["wall_seconds"]
    metrics = [
        ["Prepared/copy events per visited node", f"{counts['updates']/counts['visits']:.4f}"],
        ["Visited nodes requiring evaluation", percent(counts["evaluated_visits"]/counts["visits"])],
        ["Prepared frames never evaluated directly", percent(counts["unused_updates"]/counts["updates"])],
        ["Prepared frames with no own/descendant evaluation", percent(counts["unused_leaf_updates"]/counts["updates"])],
        ["Quiescence share of node visits", percent(counts["qvisits"]/counts["visits"])],
        ["Unused first-use quiescence frames", percent(counts["unused_q_updates"]/counts["q_updates"])],
        ["Null-edge updates / all updates", percent(counts["null_updates"]/counts["updates"])],
        ["Mean changed rows/update, one perspective", f"{counts['delta_rows']/counts['updates']:.3f}"],
        ["Root refreshes / visited nodes", f"{counts['refreshes']} / {counts['visits']:,}"],
        ["Mean pending edges / rows at first evaluation", f"{counts['pending_edges']/counts['evaluated_frames']:.2f} / {counts['pending_rows']/counts['evaluated_frames']:.2f}"],
    ]
    micro = [[name.removesuffix("_ns"), f"{r['median']:.2f}", f"{r['min']:.2f}–{r['max']:.2f}"] for name, r in profile["micro_summary_ns"].items()]
    game_rows = [[r["nodes"], r["cp_comparable"], f"{r['mean_direct_classical_minus_nnue_child_cp']:+.1f}",
                  f"[{r['paired_position_bootstrap_95'][0]:+.1f}, {r['paired_position_bootstrap_95'][1]:+.1f}]",
                  f"{r['reference_prefers_nnue']} / {r['reference_prefers_classical']}"] for r in game_quality["summary"]]
    text = f"""# StockBear Compact v2 NNUE — Search Performance Diagnosis

2026-10-15 · Completed diagnostic study · Production search, model weights and classical defaults preserved.

## 1. Executive findings and verified baseline

All **190 scheduled games** were played: 189 terminal results and one capped game. No cohort was extended. Classical was favored at 50ms and 200ms on this book; the 500ms and 1000ms results remain exploratory.

The clearest measured disadvantage is **whole-search throughput**: NNUE achieved 66–72% of classical NPS in timed fixed-position tests and completed about 0.33–0.46 fewer nominal plies. This is a plausible contributor to the match gap, not a measured causal allocation of Elo. Equal-node and equal-depth reference analysis **did not establish a general NNUE move-quality deficit**. Five single-switch ablations found no large, consistent evaluator-specific pruning failure.

The matched first-ten-pair score changed from **45.0% at 50ms to 47.5% at 1000ms**: +2.5 percentage points, with a paired 95% bootstrap interval of **−30.0 to +32.5 points**. Longer thinking time did not produce a statistically supported improvement in this sample. The middle controls were nonmonotonic.

Copying alone is not established as the bottleneck. A warm 256-byte lane copy took a median 1.74ns, while move-derived state preparation took 44.53ns. A naive lazy scheme that caches only evaluated ancestors would require **{replay:.2f}×** the current row-update work in the measured traces. Any lazy prototype needs intermediate-state reuse.

The study used the same preserved executable for both players, changing only `Evaluator`; Hash=16MB, scalar float32, incremental NNUE and all production search defaults. It used **Compact v2 32/16**, not v1 or Small v2:

- Model SHA256: `{plan['model_sha256']}`.
- Match executable SHA256: `{plan['engine_sha256']}`.
- Opening-book SHA256: `{plan['opening_book_sha256']}`.
- Baseline tag: `nnue-v2-diagnosis-baseline-1b08943`.
- Hardware: {profile['cpu']['brand']}, 12 logical CPUs, Windows, Python 3.11.8, Zig 0.13 C++17 `-O2 -ffp-contract=off`. One active search at a time; no affinity/frequency lock. No simultaneous heavy benchmarks during matches.

## 2. Full tournament results, separately by control

W/D/L/U are from NNUE's perspective. Score and Elo point estimates condition on completed games. Intervals keep both colors together and resample opening pairs 20,000 times, seed 20261017. For the capped cohort they also allow its unknown result to score anywhere from 0 to 1; those are approximate bootstrap/censoring sensitivity intervals, not guaranteed coverage under arbitrary missingness.

{table(['ms/move','Scheduled','W','D','L','U','Completed-game score','Relative Elo','Paired 95% Elo interval'], outcomes)}

At 500ms the full 30-game score is only identified as **46.7–50.0%**, rather than an assumed draw. Opening-family cluster bootstrap score intervals were 30.0–43.1%, 26.6–46.7%, 35.7–57.1% and 25.0–72.5% respectively; the 500ms family interval uses complete pairs. Conservative bounded-pair intervals and complete-case estimates are also in the summary JSON. Related opening variants and limited samples restrict generalization; these are conditional match Elo estimates.

All work columns below are **NNUE / classical**. NPS is total searched nodes divided by total engine-reported search time. Move wall time also includes protocol overhead. Means cover all searched moves, including the capped game; depth is the last completed iteration, not selective depth.

{table(['ms','Mean depth','Median depth','Mean nodes/move','Aggregate NPS','Mean actual ms/move'], work)}

{table(['ms','Checkmate','Threefold','Fifty-move','Unfinished cap'], terminations)}

There were no other terminations, zero-depth fallbacks or moves exceeding 150% of requested wall time. Early proven mates can finish before their allotted time. Recorded game wall time totaled **71.5 minutes**; the two-game pilot underestimated later game lengths. All 19,158 opening/played plies were independently replayed against JSON and PGN.

The book has 40 evaluator-neutral positions from 20 opening families, with two seeded legal quiet continuations each. No evaluator or outcome filter was used. Prefixes were exactly 40/30/15/10 pairs; each pair reversed colors. Games used claimable draws and a uniform cap of 240 searched plies, with no evaluation adjudication. One cap was 3.3% of the 500ms cohort and 0.53% overall, so the primary cap stayed fixed. Offline Stockfish rated the capped final position +290cp for White at 300k nodes, with halfmove clock 35; this neither proves a win nor changes its unfinished result.

## 3. Time-control trend on the same ten opening pairs

This table uses pairs 1–10 at **every** control. It does not compare the full 80-game cohort against the full 20-game cohort as matched samples.

{table(['ms/move','W–D–L–U','All-20-game score / bounds','Paired 95% sensitivity interval'], matched)}

Joint resampling keeps each opening's four-control results together. The all-ten 1000ms-minus-50ms endpoint was +2.5 points, interval −30.0 to +32.5. The log-time slope was bounded at +6.69 to +8.14 score points per tenfold time increase because of the single unknown result; its bootstrap/censoring envelope was **−14.87 to +26.74**. Both uncertainty ranges include zero. No sustained upward trend or indefinite Elo extrapolation is supported.

For transparency, the nine pairs completed at all four controls give a supplementary endpoint of +8.33 points, interval −27.78 to +38.89, paired sign-flip p=0.765625. Excluding the capped pair changes the estimate; it is not the primary all-ten analysis. Time controls ran serially, so common openings do not remove possible hardware drift.

[Five matched trend plots: PNG]({prefix}matched-trends.png) · [SVG]({prefix}matched-trends.svg). Capped scores have ranges rather than imputed point estimates. Game NPS and depth reflect different played positions; fixed-FEN tests below isolate position composition better.

## 4. Throughput, depth and fixed-work comparisons

The legal 24-position suite has two fixtures per requested category: openings, quiet middle, tactics, king attacks, imbalances, pawn/piece endings, passers, promotions, zugzwang, defense and planning. These are selected examples, not a random population; categories overlap and some fixtures have material advantages. Three serial trials alternated evaluator order. There were **1,296 searches** at 50/200/1000ms, 25k/100k/400k nodes and nominal depths 3/4/5.

NPS ratios below use per-FEN median trials and their geometric mean; two short mate fixtures and sub-10ms measurements are excluded from NPS aggregates only.

{table(['Equal time (ms)','NNUE/classical NPS','Mean depth difference','Mean nodes NNUE/classical'], speed)}

At 100k and 400k nodes the NPS ratios were 69.5% and 70.1%; mean wall times were 58.4/42.0ms and 222.2/157.7ms. Mean completed-depth difference at those node budgets was only +0.04 plies. Thus NNUE's lower rate does not imply proportionately lower productivity per node.

At nominal depth 5, mean nodes were 19,134/24,702 and mean wall time 15.97/15.96ms. Many depth-3/4 searches were too short for meaningful millisecond NPS comparisons. Equal nodes and equal nominal depth still produce different selective trees, quiescence work and horizons; neither makes search quality equivalent.

## 5. Independent move quality

Local **Stockfish 19** analyzed each fixture root at 300k nodes, Threads=1, Hash=64MB, full strength, no tablebases and fresh hash. Every distinct candidate—including Stockfish's root choice—then received a separate 300k-node child search with identical settings, preserving the original root side's score perspective. This comprised 24 roots and 69 distinct child analyses. Mate scores remain separate.

CPL uses the reference move's **child** score minus the candidate child's score, clipped at zero; raw negative losses remain recorded as finite-budget inconsistencies. Root and child searches have different contexts and are not silently equated. The primary paired CP contrast below directly subtracts the two candidate child scores. Positive values favor classical; negative values favor NNUE. Twenty-one positions have finite scores for this contrast; the three mate-reference positions are handled separately. Quality uses the first trial, not three pseudo-independent samples.

{table(['Budget','Same move','Paired CP positions','Classical−NNUE child cp','Illustrative paired 95% interval','Reference prefers NNUE/classical (all 24)'], decisions)}

At 100k nodes, mean CPL was 2.90cp for NNUE and 8.14cp for classical on the 21 finite-reference cases; best-move agreement with the reference was 17/24 versus 14/24. At 400k nodes mean CPL was 1.76/4.67cp. There was one ≥100cp NNUE loss at depth 3, resolved by depth 4; no ≥300cp losses appeared. Neither evaluator lost a reference winning-mate indication in these fixtures. Probability-transformed losses and negative-loss counts are preserved in the machine-readable summary; the transform is descriptive, not a calibrated game-win probability.

Supplementary sampling selected 12 actual-game positions—one per phase/control from the first ten pairs—using the minimum seeded hash key, legal/material criteria and no scores/outcomes. Full move histories were retained. Both evaluators searched each at 100k/400k nodes; 12 more reference roots and 28 distinct child analyses used the same SF budget.

{table(['Equal nodes','Finite CP positions / 12','Classical−NNUE child cp','Illustrative paired interval','Reference prefers NNUE/classical'], game_rows)}

This sample is mixed and dependent, not evidence of equivalence or an Elo estimate. Together, the tests do **not** establish that NNUE generally chooses worse moves at equal nodes/depth. A global evaluation-quality explanation remains unproven, rather than ruled out. Stockfish is independent of StockBear's search but was also the NNUE teacher; its bounded analysis is not perfect ground truth.

As a separate static-score check, NNUE's mean absolute error against searched SF root scores was 237cp versus classical's 289cp on 21 finite cases. Different horizons confound those numbers, so they do not justify rescaling either evaluator. Training targets blend 90% teacher probability and 10% game result in sigmoid space, rather than minimizing raw CP error.

## 6. Single-feature search-heuristic interactions

**1,152 release searches** tested production and five individual switches, both evaluators, 200ms and 100k nodes, two trials. Other production options and thresholds stayed fixed. Disabled-feature counters were checked to be zero. No combined-off configuration or extra strength tournament was run.

CP columns are mean CPL change versus the corresponding production baseline, **200ms / 100k nodes**; positive is worse. NPS ratios use the median of two trials on 22 eligible FENs. Move changes and depth changes use the first 200ms trial. Full PV, node, stability and uncertainty records remain available.

{table(['Disabled feature','NNUE ΔCPL cp','Classical ΔCPL cp','200ms NPS NNUE/classical (% own baseline)','200ms depth Δ NNUE/classical','200ms changed moves NNUE/classical'], ablations)}

No ablation showed a large, consistent NNUE quality recovery. Removing null moves reduced timed NPS to 80.5% of NNUE production without a quality improvement. Removing LMR lost roughly a third of a ply for both evaluators. Aspiration removal slightly worsened NNUE CPL in this small sample. The small futility/RFP changes do not justify production threshold changes. Switching a heuristic changes the tree, so increased NPS or reduced nodes alone is not playing-strength evidence.

Inspection found no razoring, SEE/delta quiescence pruning, static-evaluation move ordering or TT static-evaluation cache to ablate. SEE orders moves; TT entries contain search bounds. Quiescence's existing stand-pat and safety limits remain part of the search, without inventing a separate unsupported pruning switch.

## 7. Accumulator overhead and the lazy-materialization hypothesis

Release, counter-only and exclusive-clock builds ran three rotated trials on every FEN at 100k nodes and 200ms: **432 searches**. All fixed-node moves, PVs, scores, nodes and search counters matched exactly. The following counts pool 72 counter-build 100k-node searches, including the mate fixtures.

{table(['Measured logical work','Value'], metrics)}

There were {counts['updates']:,} preparations/copies, {counts['evaluation_calls']:,} head calls and {counts['delta_rows']:,} changed rows in one-perspective accounting. Extra head calls beyond evaluated visits were only {counts['evaluation_calls']-counts['evaluated_visits']:,}. Null updates were usually zero-delta, but only 0.29% of all updates. Refreshing roots is negligible at this workload.

A frame occupies **664 bytes**, and the fixed 65-frame stack 43,160 bytes. The active float lanes plus copied feature metadata carry **408 bytes/update**, not a whole 664-byte frame. Pooled logical copy payload was 2.935GB (5.870GB counting source reads and destination writes); weight-row reads were 4.220GB and accumulator row read/write operations 8.439GB. These are source-level byte estimates, **not measured DRAM traffic, cache misses or bandwidth**.

Five repeated warm native microbenchmarks per first category fixture (60 samples, 100k calls each) gave:

{table(['Operation','Median ns/call','Observed range'], micro)}

The copy microbenchmark covers float lanes only; metadata and real search cache behavior differ. The head measures float side-to-move inference; final integer sign/clamp/rounding is outside that micro result. Classical micro evaluation is uncached, unlike production pawn-cache use.

For the identical 7.2M-node workload, wall times were {release_wall:.3f}s release, {counter_wall:.3f}s counters and {clock_wall:.3f}s clocks: +{100*(counter_wall/release_wall-1):.1f}% and +{100*(clock_wall/release_wall-1):.1f}% overhead. Clock-build exclusive shares were update/bookkeeping 20.16%, copy 8.10%, head 12.69% and other search 24.46%. Tiny scopes are strongly distorted by timing overhead; copy's 8.10% is **not** its release runtime share. Fresh TT construction precedes the scoped profile.

**Lazy assessment:** 20.4% of frames lack their own head call, but most still feed evaluated descendants. Only 5.1% are unused leaves. Caching only evaluated ancestors would reduce preparation/copy targets to {counts['evaluated_frames']:,}, yet replay {counts['pending_rows']:,} rows versus {counts['delta_rows']:,} eagerly—**{replay:.2f}× row work**. Pending chains reached 20 edges. These uncancelled, order-preserving trace sums are an analytical model, not an implemented benchmark. A useful prototype must retain intermediate states on reused paths; skipping all unused frames is not a free 20% gain. The allocated stack does not automatically shrink. No lazy implementation was added.

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

- **{verification['pytest']}**, using a fresh ordinary v1 build for the legacy suite's model-specific expectations; every diagnostic/performance experiment used Compact v2.
- 96 depth/node cases across five Compact builds matched moves, scores, PVs, nodes, selective depth and search counters. The uninstrumented rebuilt `.text` section was byte-identical to the preserved executable: `{correct['release_text_sha256']['preserved_release']}`.
- Counter and UBSan builds each matched all 22,165 held-out/random/extreme outputs exactly; each passed 128 trained goldens (maximum 0.000202cp difference), 31,876 real/sibling transitions and 26,908 null transitions, plus the synthetic counter oracle.
- Cancellation, terminal/draw handling, evaluator switching and fresh TT checks passed. An initial harness assertion expected `None` instead of the valid falsy null-move representation of UCI `0000`; correcting that assertion required no engine change or experiment rerun.
- Automated Pygame/UCI worker checks passed across all time presets, undo/new stale-result rejection and minimum layout. A real Windows launch played a validated Compact v2 move and produced the visually inspected [desktop frame]({prefix}gui-desktop.png); automated checks are separately labeled [GUI verification]({prefix}gui-verification.json).

The [study guide]({prefix}README.md) documents prepare, pilot, resume, fresh output roots and local prerequisites. To inspect/resume this frozen schedule and run the serial follow-up:

```powershell
.\\.venv\\Scripts\\python.exe -m tools.run_nnue_diagnosis_matches
.\\.venv\\Scripts\\python.exe -m tools.run_nnue_diagnosis_pipeline --skip-builds
```

Completed raw experiments are retained, not replayed by these commands. A fresh reproduction must use new `STOCKBEAR_DIAGNOSIS_ROOT` and `STOCKBEAR_DIAGNOSIS_ARTIFACTS` paths plus a matching `STOCKBEAR_DIAGNOSIS_ENGINE`, as described in the guide. Held-out SQLite data, Stockfish and plotting dependencies are local prerequisites; no model or training pipeline was changed.

Evidence: [match plan]({prefix}match-plan.json), [full JSON/CSV summary]({prefix}tournament-summary.json), [CSV]({prefix}tournament-summary.csv), [record audit]({prefix}record-audit.json), [controlled searches]({prefix}controlled-searches.json), [reference moves]({prefix}stockfish-quality.json), [paired position summary]({prefix}position-summary.json), [game sample]({prefix}tournament-position-quality.json), [ablations]({prefix}ablations.json), [ablation throughput]({prefix}ablation-throughput.json), [accumulators]({prefix}accumulator-profile.json), [stability]({prefix}search-stability.json), [native correctness]({prefix}correctness.json), [verification]({prefix}verification-summary.json), and [output manifest]({prefix}output-manifest.json). Per-control JSON/PGN files use `50ms`, `200ms`, `500ms` and `1000ms` basenames.

All earlier reports remain separate. The four raw match summaries preserve a legacy prose reference to an own-evaluator filter; the authoritative frozen book/source/hash prove that no such filter was used here. Future runs now label their book context correctly while keeping old records verifiable.
"""
    output.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {output}: {len(text.split())} words")


if __name__ == "__main__":
    main()
