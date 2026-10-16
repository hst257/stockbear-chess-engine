"""Generate the final research report from frozen v3 measurements and matches."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics

from tools.analyze_nnue_diagnosis import cohort
from tools.nnue_diagnosis import sha

ROOT = Path("docs/nnue-v3")
TRAIN = Path("StockBear_NNUE_training/reports/v3")
REPORT = Path("NNUE_V3_KING_RELATIVE_REPORT.md")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def plot(a, b, heldout, benchmark):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams["svg.hashsalt"] = "stockbear-v3"
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), constrained_layout=True)
    for record, label in ((a, "A: full king squares"), (b, "B: 16 king buckets")):
        axes[0].plot([r["epoch"] for r in record["history"]], [r["validation_mse"] for r in record["history"]], "o-", markersize=3, label=label)
    axes[0].axhline(.013181713930761297, linestyle="--", color="gray", label="Frozen v2 validation")
    axes[0].set(title="Validation-only architecture selection", xlabel="Epoch", ylabel="Blended probability MSE")
    axes[0].legend(fontsize=8)
    timed = [r for r in benchmark["summary"] if r["mode"] == "time"]
    x = list(range(len(timed)))
    axes[1].plot(x, [r["v2_classical_nps"] for r in timed], "o-", label="Optimized v2")
    axes[1].plot(x, [r["v3_classical_nps"] for r in timed], "o-", label="Selected v3 B")
    axes[1].axhline(1, linestyle="--", color="gray", label="Classical")
    axes[1].set_xticks(x, [str(r["budget"]) for r in timed])
    axes[1].set(title="Timed whole-search throughput", xlabel="Milliseconds / move", ylabel="NPS / frozen classical", ylim=(0, max(1.1,max(r["v3_classical_nps"] for r in timed)*1.1)))
    axes[1].legend(fontsize=8)
    phases = ["opening", "middlegame", "endgame"]
    axes[2].bar([n-.18 for n in range(3)], [heldout["v2"]["by_phase"][p]["clipped_cp_mae"] for p in phases], width=.36, label="Optimized v2")
    axes[2].bar([n+.18 for n in range(3)], [heldout["v3"]["by_phase"][p]["clipped_cp_mae"] for p in phases], width=.36, label="Selected v3 B")
    axes[2].set_xticks(range(3), phases)
    axes[2].set(title="Final grouped held-out prediction", ylabel="Clipped teacher centipawn MAE")
    axes[2].legend(fontsize=8)
    fig.suptitle("StockBear v3: representation quality, throughput and their limits")
    fig.savefig(ROOT / "results.png", dpi=180)
    fig.savefig(ROOT / "results.svg", metadata={"Date": None})
    plt.close(fig)
    svg = ROOT / "results.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines())+"\n", encoding="utf-8", newline="\n")


def main() -> None:
    a, b = read(TRAIN / "training.json"), read(TRAIN / "training-b.json")
    selection, heldout = read(TRAIN / "selection.json"), read(TRAIN / "heldout.json")
    bench = read(ROOT / "benchmark-summary.json")
    native, sanitizer = read(ROOT / "heldout-native-parity.json"), read(ROOT / "ubsan-native-parity.json")
    preserved = read(ROOT / "release-search-parity.json")
    sanitized_search = read(ROOT / "ubsan-search-parity.json")
    assert len(preserved["preserved_searches"]) == 240
    assert len(sanitized_search["preserved_searches"]) == 96
    assert all(r["incremental_refresh_tree_identical"] for r in preserved["v3_searches"])
    desktop = read(ROOT / "desktop.json")
    assert desktop["visually_inspected"]
    runtime = read(ROOT / "application-runtime.json")
    assert runtime["same_embedded_model"] and len(runtime["searches"]) == 32
    memory = read(ROOT / "memory.json")
    assert all(r["samples"] > 0 for r in memory["configurations"].values())
    baseline = read(ROOT / "baseline.json")
    unchanged = []
    for path, expected in baseline["source_sha256"].items():
        if sha(Path(path)) == expected: unchanged.append(path)
    for required in ("engine/src/nnue.cpp", "engine/src/nnue.hpp", "engine/src/evaluation.cpp", "engine/src/evaluation.hpp",
                     "engine/src/search_policy.hpp", "engine/src/transposition.hpp"):
        assert required.replace("/", "\\") in unchanged or required in unchanged
    for path, expected in baseline["datasets"].items(): assert sha(Path(path)) == expected
    for path, expected in baseline["identities"].items():
        if path != "engine/build/chesslab-engine.exe": assert sha(Path(path)) == expected
    models = read(Path("engine/networks/v3/models.json"))
    for name, row in models.items(): assert sha(Path("engine/networks/v3") / name) == row["sha256"]
    matches = {}
    for opponent in ("v2", "classical"):
        path = ROOT / f"match-v3-{opponent}.json"
        if not path.exists(): continue
        raw = read(path)
        assert raw["requested_games"] == len(raw["games"]) == 20
        result = cohort(raw["games"])
        result["v3"] = result.pop("nnue")
        result["opponent"] = result.pop("classical")
        matches[opponent] = result
    assert "v2" in matches
    write = lambda path,value: Path(path).write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8",newline="\n")
    write(ROOT / "match-summary.json", matches)
    old10, old30 = read(ROOT / "baseline10.json"), read(ROOT / "baseline30.json")
    assert old10["movetime_ms"] == old30["movetime_ms"] == 500
    control_games = [dict(g, game=i+1, pair=i//2+1) for i,g in enumerate(old10["games"] + old30["games"][:10])]
    control = cohort(control_games)
    control["method"] = "First 10 original opening pairs, combining the initial 10 games and the first 10 of the additional-30 cohort. Reindexed copies for paired statistics; original records unchanged. Historical conditions differ."
    write(ROOT / "historical-matched-control.json", control)
    quality_raw = read(ROOT / "quality.json")["records"]
    category_diagnostics = {}
    for category in sorted({r["category"] for r in quality_raw}):
        selected = [r for r in quality_raw if r["category"] == category]
        category_diagnostics[category] = {}
        for label in ("classical", "v2", "v3"):
            disagreements, large_losses, mate_not_confirmed = [], [], []
            for row in selected:
                move = row["candidates"][label]["move"]
                if move != row["reference"]["move"]: disagreements.append(row["position"])
                child = row["children"][move]
                if row["reference"]["cp"] is not None and child["cp"] is not None and row["reference"]["cp"]-child["cp"] >= 150:
                    large_losses.append(row["position"])
                if row["reference"]["mate"] is not None and row["reference"]["mate"] > 0 and (child["mate"] is None or child["mate"] <= 0):
                    mate_not_confirmed.append(row["position"])
            category_diagnostics[category][label] = {"positions": len(selected), "move_disagreements": disagreements,
                "reference_cpl_ge150_heuristic": large_losses, "reference_winning_mate_not_confirmed_after_move": mate_not_confirmed}
    write(ROOT / "quality-by-category.json", {"categories": category_diagnostics,
        "caution": "Finite-budget root/child searches differ by one ply; absence of a confirmed mate is a diagnostic flag, not proof a forced mate was lost."})
    profile = read(ROOT / "profile.json")
    scopes = Counter()
    calls = Counter()
    for row in profile["records"]:
        scopes.update({key: value["ns"] for key,value in row["profile"]["categories"].items()})
        calls.update({key: value["calls"] for key,value in row["profile"]["categories"].items()})
    write(ROOT / "profile-summary.json", {"exclusive_ns": dict(scopes), "calls": dict(calls),
        "instrumented_wall_seconds": sum(r["wall_seconds"] for r in profile["records"]),
        "method": profile["method"]})
    plot(a,b,heldout,bench)
    match = matches["v2"]
    successful = match["paired_censoring_bootstrap_95_envelope"][0] > .5 and match["unfinished"] == 0
    verdict = "V3 shows promising bounded equal-time evidence, requiring independent confirmation" if successful else "V3 is implemented and verified, but is not established as an improvement over optimized v2"
    lines = ["# StockBear NNUE v3 — King-Relative Research Report", "", "## Executive summary", "",
        verdict + ". Optimized v2 remains the preferred NNUE. Classical remains the default; no v2 weights or implementation are replaced.", "",
        f"Validation selected **B: 16 king buckets, shared 32/16 float32 network**, {b['parameters']:,} parameters. Full 64-square candidate A overfit more severely. Both models, checkpoints and exact training sources are retained. Final held-out blended MSE is **{heldout['v3']['blended_mse']:.6f} v3 versus {heldout['v2']['blended_mse']:.6f} v2**; clipped teacher MAE is **{heldout['v3']['clipped_cp_mae']:.2f} versus {heldout['v2']['clipped_cp_mae']:.2f}cp**. Prediction quality did not improve.", "",
        f"The user amended playing validation before play to **20 games at 500ms/move**, ten reversed-color opening pairs, including the smoke pair. V3 vs v2: **{match['wins']} wins, {match['draws']} draws, {match['losses']} losses, {match['unfinished']} unfinished**, completed-game score **{match['score']*100:.1f}%**. This is a small exploratory match; uncertainty and the conditional classical gate appear below.", "",
        f"Verification: **{(ROOT/'final-tests.txt').read_text(encoding='utf-8').splitlines()[-1]}**; training package **40 passed**. Release preserved 240 classical/v2 searches exactly; UBSan preserved 96. All 48 v3 deterministic repeat/full-refresh cases matched. Native parity covers the complete 20,152-position grouped holdout.", "",
        "![Training, throughput and held-out results](docs/nnue-v3/results.png)", "", "## Architecture and native implementation", "",
        "Feature contract A conditions every non-king piece-square feature on the own king's oriented square: 64×10×64 = 40,960 sparse piece inputs. B maps the oriented king to a 2×2-square region, `(rank//2)*4 + file//2`, giving 16×10×64 = 10,240. Both append 12 independent v2-style castling/legal-EP inputs; totals are 40,972 and 10,252. Empty squares and kings are not ordinary piece rows. Friendly/enemy colors normalize per perspective; Black mirrors ranks with `square^56`. Active indices sort ascending. Head order carries side to move.", "",
        "At most 35 active indices per perspective are stored as uint16; training uses indexed EmbeddingBag sums, never dense input vectors. Both perspectives share a float32 32-wide table and bias. Their clipped [0,1] concatenation feeds a clipped 16-wide hidden layer and scalar side-to-move cp/400 output. No transfer learning, quantization, precision change, handcrafted blend, TF32 or fast-math was used.", "",
        "| Candidate | King contexts | Parameters including padding | Model file bytes | Best validation MSE |", "| --- | ---: | ---: | ---: | ---: |",
        f"| A full | 64 | {a['parameters']:,} | {models['stockbear-v3-a.sbnnue']['bytes']:,} | {a['validation']['blended_mse']:.6f} |",
        f"| B bucketed | 16 | {b['parameters']:,} | {models['stockbear-v3-b.sbnnue']['bytes']:,} | {b['validation']['blended_mse']:.6f} |", "",
        "The independent `nnue_v3.hpp/.cpp` path loads a versioned 72-byte header plus fixed-order float payload. Architecture/layout ID 6 fixes the six-tensor 32/16 clipped head; feature IDs 1/2 distinguish full/bucketed inputs. SHA256, exact size, dimensions, finite/range bounds and zero padding are checked before activation. Failed loading retains the old model and selection. Details: [format](docs/nnue-v3/MODEL_FORMAT.md) and [design](NNUE_V3_DESIGN.md).", "",
        f"Each native frame is **{native['transitions']['frame_bytes']} bytes**, or **{65*native['transitions']['frame_bytes']:,} bytes** for 65 search frames, plus one immutable shared model and a 4KB transposed head. Accumulators stay unclipped in fixed White/Black order. Capture move deltas before make; update ordinary pieces/state rows without full sorted piece-list metadata. Refresh only the perspective whose king context changes; within-bucket king moves retain sums but still update rights/EP. Castling also moves the rook; null moves alter legal EP/head order. Roots refresh and child storage remains private. No lazy redesign was introduced.", "",
        "UCI adds `Evaluator=nnue_v3` and `NNUEV3File`; `classical` remains default and `nnue` retains the chosen executable's embedded network. The v3 release build explicitly embeds frozen optimized Compact v2. The ordinary app executable retains its original embedded v1 model while gaining v3 support; use the study release for the exact three-way v2/v3/classical comparison. GUI selection cycles all three choices, marks v3 experimental and performs validation/UCI work off the GUI thread. No search/pruning/order/TT/time policy was changed.", "", "## Dataset and training", "",
        "Reused the existing 1.25M nominal labeled pool: **999,464 train / 19,930 validation / 20,152 test** examples. The smaller common holdout prefix is preserved exactly. V2 sparse rows losslessly provide king, piece and state information for v3 re-encoding. Each variant independently matched 12,288 parsed source FENs. Target and ordinal files are byte-identical, game groups are disjoint, original arrays retain their frozen hashes, and no Stockfish labels were regenerated.", "",
        "Teacher profile `ddc2b43b123677466a9a9f8478f67ffc028a6582266a73e36a3272bc85b30f92` uses the existing 16,384-node Stockfish teacher labels. Targets remain 90% sigmoid(clipped teacher cp/400) plus 10% side-to-move game outcome. Original grouping/deduplication is inherited rather than resampled. New caches, checkpoints and reports live under versioned v3 directories on the project drive.", "",
        "Fresh seed 20261016; float32 AdamW, learning rate .0015, decay .05, batch 2048, gradient clipping 1.0, validation plateau scheduler (patience 2, factor .5), early-stop patience 8, min-delta 1e-5, maximum 60 epochs. No incompatible v2 weights were loaded. CPU/native feature and forward gates preceded 20K-example, three-epoch GPU pilots. Only after finite gradients and safe resource measurements did full training start. One bounded fallback B was justified by A's validation overfitting; no larger model or hyperparameter sweep followed.", "",
        "| Candidate | Epochs / best epoch | Train MSE at selected checkpoint | Validation MSE | Peak allocated CUDA MiB | Recorded epoch seconds |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for label,r in (("A",a),("B",b)):
        lines.append(f"| {label} | {r['epochs']} / {r['best_epoch']} | {r['train']['blended_mse']:.6f} | {r['validation']['blended_mse']:.6f} | {r['peak_cuda_bytes']/1024**2:.1f} | {sum(h['seconds'] for h in r['history']):.2f} |")
    lines += ["", "CUDA allocated memory excludes driver/context and allocator reservation. Both full runs fit comfortably within the RTX 4050's 6GB. GPU resident sparse indices dominate memory; no dense 40K input batches were created. Recorded epoch times include validation but exclude checkpoint I/O and data preparation; they are not isolated hardware throughput. Native compilation overlapped part of candidate B's training, so training duration is descriptive, not a controlled speed comparison. No tournament ran during training.", "",
        "Checkpoint selection used validation only, before the single final test evaluation. Checkpoints retain optimizer/scheduler/RNG states; reports record strict dataset/config/runtime/source signatures. Exact pre-hardening A/B training sources are preserved alongside reports. Subsequent model-validator hardening changes no trained bytes. Source snapshots and runtime must match for exact resume; changed signatures are rejected.", "", "## Held-out quality and calibration", "",
        "| Metric | Optimized v2 | Selected v3 B |", "| --- | ---: | ---: |"]
    for label,key in (("Blended probability MSE","blended_mse"),("Teacher probability MSE","teacher_probability_mse"),("Teacher probability MAE","teacher_probability_mae"),("Clipped cp MAE","clipped_cp_mae"),("Clipped cp RMSE","clipped_cp_rmse"),("Outcome Brier score","outcome_brier")):
        lines.append(f"| {label} | {heldout['v2'][key]:.6f} | {heldout['v3'][key]:.6f} |")
    lines += ["", "[Held-out metrics](StockBear_NNUE_training/reports/v3/heldout.json) include calibration bins, phase, tactical/quiet heuristics and year breakdowns. [Additional strata](docs/nnue-v3/heldout-strata.json) cover pawn/rook endgames, material imbalance, king pressure, unusual promoted configurations, passers and drawish teacher scores. These overlapping heuristic labels are descriptions, not verified tactical classifications. Test data was not used for retuning. No additional candidate was selected from these test results.", "", "## Native correctness and preservation", "",
        f"- Complete grouped heldout: {native['positions']:,} exact cross-language feature lists; maximum native/PyTorch difference **{native['max_abs_cp_error']:.6g}cp**. GPU-training versus CPU reference maximum **{native['max_training_gpu_vs_cpu_cp_error']:.6g}cp**. The allowed tolerance is 0.02cp, not integer-score equality.",
        f"- Selected B transition oracle: **{native['transitions']['transitions']:,}** real/sibling transitions, **{native['transitions']['nulls']:,}** nulls and **{native['transitions']['king_refreshes']:,}** affected-context refreshes. Maximum refreshed/incremental lane error {native['transitions']['max_lane_error']:.6g}; output error {native['transitions']['max_cp_error']:.6g}cp. Ordinary moves, castling, EP/pinned EP, promotions, long walks, siblings and board restoration are included.",
        "- Both feature variants passed independent native prototypes. Trained A is retained and independently verified. Sixteen extreme/clipping-boundary head cases passed; eight malformed-model classes were rejected by Python and native readers, including checksum-valid nonfinite and unsafe-magnitude payloads.",
        "- Release: 24 FENs × two preserved evaluators × depths 4/6 and 100k/400k/1M nodes = **240 exact classical/v2 cases**, including moves, scores, PVs, visits, selective depths and counters. UBSan repeats **96** preserved cases. All **48** v3 fixed-work cases repeated exactly and matched full-refresh trees. Twelve cancellations and five terminal/draw-history cases pass per checked build. No v3-v2 tree equality is required or claimed.",
        "- The full regression suite and training-package suite pass. V2 native evaluator/header, model, classical evaluation/constants, search-policy and TT headers remain byte-identical to the frozen baseline. Shared search changes only dispatch/state ownership; new UCI choices intentionally extend the protocol. [Release evidence](docs/nnue-v3/release-search-parity.json), [UBSan evidence](docs/nnue-v3/ubsan-search-parity.json).",
        "- The ordinary app executable also preserves its original embedded model, classical default and all 32 checked classical/NNUE searches against its saved pre-v3 binary. [Application runtime evidence](docs/nnue-v3/application-runtime.json).",
        "- UBSan native feature/transition/head/model checks passed without a detected error. AddressSanitizer remains unavailable with the pinned Windows toolchain, whose duplicate libc++ ABI symbols/missing MinGW runtime were independently diagnosed in the prior throughput phase; no new ASan pass is claimed. [Toolchain evidence](docs/nnue-v2-throughput/asan-probes.json).",
        "- Automated GUI checks exercise all five time presets, comparisons and stale replies; the minimum frame was inspected. A real Windows SDL launch completed with a validated v3 move and a visibly correct frame. These are app-rendered frame checks, not manual interaction or OS screenshots. [GUI evidence](docs/nnue-v3/gui/gui-verification.json), [native frame](docs/nnue-v3/gui-native.png).", "", "## Whole-search throughput and profiling", "",
        "Zig 0.13, C++17, -O2 -ffp-contract=off; no LTO or fast-math. Intel i5-13420H, Windows, Python 3.11.8. Three rotated serial trials across 24 frozen FENs, Hash16, one worker, fresh search tables. Models have different trees; NPS ratios combine evaluation cost and evaluator-dependent search work. They are not pure implementation speedups. Time, nodes, completed depth, CPU accounting and iteration stability remain in raw records.", "",
        "| Limit | Eligible FENs | V2/classical NPS | V3/classical NPS | V3/v2 NPS | Selected-FEN interval | V3−v2 mean depth |", "| --- | ---: | ---: | ---: | ---: | --- | ---: |"]
    for r in bench["summary"]:
        lo,hi=r["v3_v2_selected_fen_bootstrap95"]
        lines.append(f"| {r['budget']:,} {'nodes' if r['mode']=='nodes' else 'ms'} | {r['eligible']} | {r['v2_classical_nps']:.3f} | {r['v3_classical_nps']:.3f} | {r['v3_v2_nps']:.3f} | [{lo:.3f}, {hi:.3f}] | {r['v3']['mean_depth']-r['v2']['mean_depth']:+.3f} |")
    lines += ["", "Absolute NPS below is the geometric mean of per-position three-trial median engine NPS over the same eligible FENs (millions of nodes/second). It uses the engine's search timer, while the raw records also retain host wall time.", "",
        "| Limit | Classical MNPS | V2 MNPS | V3 MNPS |", "| --- | ---: | ---: | ---: |"]
    for r in bench["summary"]:
        selected = [p for p in bench["per_position"] if p["eligible"] and (p["mode"],p["budget"]) == (r["mode"],r["budget"])]
        values = [math.exp(statistics.mean(math.log(p["medians"][label]["nps"]) for p in selected))/1e6 for label in ("classical","v2","v3")]
        lines.append(f"| {r['budget']:,} {'nodes' if r['mode']=='nodes' else 'ms'} | {values[0]:.3f} | {values[1]:.3f} | {values[2]:.3f} |")
    lines += ["", "A separate serial 500ms initial-position search sampled whole-process memory every 10ms. These one-run measurements include the complete engine, embedded weights and Hash16; they do not isolate model allocation or establish a memory distribution.", "",
        "| Evaluator | Sampled maximum working set MiB | Sampled maximum private MiB |", "| --- | ---: | ---: |"]
    for label,r in memory["configurations"].items():
        lines.append(f"| {label} | {r['max']['working_set_bytes']/1024**2:.2f} | {r['max']['private_bytes']/1024**2:.2f} |")
    lines += ["", "[Memory measurements](docs/nnue-v3/memory.json) were collected after the tournament, separately from release timing trials."]
    lines += ["", "Aggregate ratios are geometric means of per-position trial medians. Bootstrap intervals resample selected FENs, describing suite sensitivity, not general-population certainty. Mate fixtures, mate-scored/early terminations and sub-10ms runs are excluded only from common aggregate ratios; all raw searches remain saved. Per-position ratios, eligible flags and min/median/max distributions are in [JSON](docs/nnue-v3/benchmark-summary.json) and [CSV](docs/nnue-v3/benchmark-summary.csv). CPU percentages use one logical core as 100%; wall includes UCI/fresh-TT setup. Affinity/frequency were not locked.", "",
        "Intrusive clocks on the 24-FEN 400k-node v3 workload preserve every release tree. Largest exclusive scopes:", "",
        "| Scope | Instrumented seconds | Calls |", "| --- | ---: | ---: |"]
    for key,value in scopes.most_common():
        if key in dict(scopes.most_common(8)) or key.startswith("nnue_"):
            lines.append(f"| {key} | {value/1e9:.4f} | {calls[key]:,} |")
    lines += ["", "Refresh scopes include root and king-bucket refreshes; state extraction is separately scoped, while copy, row application and index bookkeeping remain combined under update. Delta construction outside those scopes falls in search bookkeeping. These instrumented timings cannot isolate physical cache misses, copy latency or instruction costs and are not production runtime percentages. Hardware cache/branch counters were not collected. The larger weight table and refreshes are plausible overheads, not proven causal allocations. No aggressive SIMD, quantization, lazy or search-policy optimization was adopted for a model that already trails v2 prediction quality. [Raw profile](docs/nnue-v3/profile.json).", "", "## Equal-node move-quality diagnosis", ""]
    quality=read(ROOT/"quality-summary.json")
    lines += ["The comparison uses 100k candidate nodes and separate 65,536-node Stockfish root/child reference searches on 24 frozen examples plus 24 new outcome-blind legal-walk FENs absent from the source pool. All candidates have identical search settings. Child scores are mapped to the root mover; negative raw root/child deltas are retained and CPL is clipped at zero. Mates remain separate. Terminal children can report zero nodes/depth because no further search is required; these are explicitly flagged. Stockfish also supplied training labels, so this reference is not an independent measure of playing strength.", "",
        "| Cohort | Evaluator | Root best-move agreement | Mean finite CPL | Negative raw deltas |", "| --- | --- | ---: | ---: | ---: |"]
    for name,rows in quality.items():
        for label,r in rows.items(): lines.append(f"| {name} | {label} | {r['best_move_agreement']}/{r['positions']} | {r['mean_cpl']:.2f} | {r['negative_raw_deltas']} |")
    lines += ["", "Raw records retain tactical/positional/endgame examples, move disagreements, mate cases and a reference-CPL≥150 heuristic miss count. [Category diagnostics](docs/nnue-v3/quality-by-category.json) list disagreements and mate-confirmation flags by category; a finite-budget failure to confirm a reference mate is not proof of a lost forced mate. This small fixed suite cannot establish population move quality. [Quality evidence](docs/nnue-v3/quality.json).", "", "## Bounded playing strength", ""]
    for opponent,r in matches.items():
        lo,hi=r["paired_censoring_bootstrap_95_envelope"]
        lines += [f"**V3 vs {opponent}:** {r['wins']}–{r['draws']}–{r['losses']} W–D–L, {r['unfinished']} unfinished, completed-game score {r['score']*100:.1f}%. Ten opening pairs; paired 95% bootstrap/censoring envelope **{lo*100:.1f}%–{hi*100:.1f}%**. Conditional Elo point estimate {r['relative_elo']:+.1f}, exploratory only. Unknown-outcome score bounds {r['unfinished_worst_best_score'][0]*100:.1f}%–{r['unfinished_worst_best_score'][1]*100:.1f}%.", "",
            f"The conservative bounded-pair Hoeffding 95% interval is **{r['paired_hoeffding_95'][0]*100:.1f}%–{r['paired_hoeffding_95'][1]*100:.1f}%** under nominal independent-pair assumptions. With only ten related opening pairs, the empirical bootstrap can understate uncertainty; its exclusion of 50% is not taken as a reliable general Elo finding.", "",
            f"Played-position aggregate NPS: v3 {r['v3']['aggregate_nps']/1e6:.3f}M, opponent {r['opponent']['aggregate_nps']/1e6:.3f}M; mean completed depths {r['v3']['mean_completed_depth']:.2f}/{r['opponent']['mean_completed_depth']:.2f}. These are different positions and trees; use fixed-FEN results for the cleaner throughput comparison.", ""]
    if "classical" not in matches:
        lines += ["The separately planned classical cohort was **not run**, because the predeclared ≥50% completed-game v3-v2 promise gate was not met. No extra tournament games were added to seek a favorable result. V3-versus-classical strength therefore remains unmeasured in this study.", ""]
    lines += ["Both colors use the same fixed neutral openings and 500ms/move settings. The smoke pair is part of the 20, not extra. Claimable draws are allowed; a 240 searched-ply cap is unfinished, never an adjudicated draw. Independent replay checks every move, result, pair/color and executable/external-model checksum. Only ten pairs, related openings and reused cohorts limit inference; no statistically reliable universal Elo conclusion is claimed.", "",
        "The prior v2/classical result remains **11 wins, 14 draws, 15 losses / 40 games (45%)**. These new cohorts use only its first ten opening pairs. Any reused-opening comparison must select the matching first 20 old games, not directly contrast the full 40-game control with a 20-game sample as matched observations. Original raw cohorts are preserved in `baseline10.*` and `baseline30.*`.", "",
        f"The matching historical 20-game control subset is **{control['wins']}–{control['draws']}–{control['losses']}** for v2, score {control['score']*100:.1f}%. [Subset analysis](docs/nnue-v3/historical-matched-control.json) keeps those pairs together; different historical machine conditions and reused openings prevent treating it as independent confirmation.", "", "## Conclusions and next steps", "",
        "1. **Teacher prediction:** king conditioning did not improve the held-out metrics under this bounded data/training setup. Bucketing improved A's generalization but did not catch v2.",
        "2. **Decision quality:** the equal-node reference and paired games provide limited direct evidence; neither model age nor lower training loss establishes superiority.",
        "3. **Throughput cost:** measured release NPS, context refresh work and memory cost are tabulated above. Different trees and intrusive timers prevent assigning the entire difference to one evaluator operation.",
        "4. **Equal-time objective:** use the recorded match uncertainty rather than the Elo point estimate. This experiment does not justify replacing the frozen v2 evaluator or changing classical defaults.",
        "5. **Further research:** additional regularization, smaller/better-conditioned representations or more diverse grouped data may be worth a separately planned experiment. This phase does not start another architecture sweep, relabeling campaign or confirmation tournament.", "", "## Identity and reproduction", "",
        "| Artifact | SHA256 |", "| --- | --- |",
        f"| Optimized v2 model | `{baseline['identities']['engine/networks/v2/stockbear-v2-compact.sbnnue']}` |",
        f"| V3 A | `{models['stockbear-v3-a.sbnnue']['sha256']}` |",
        f"| V3 B / selected alias | `{models['stockbear-v3-b.sbnnue']['sha256']}` |",
        f"| V3 release executable | `{preserved['candidate']['sha256']}` |", "",
        "[Protocol and commands](docs/nnue-v3/README.md) · [Model selection](StockBear_NNUE_training/reports/v3/selection.json) · [Raw benchmarks](docs/nnue-v3/benchmark.json) · [Match summary](docs/nnue-v3/match-summary.json) · [V3-v2 PGN](docs/nnue-v3/match-v3-v2.pgn) · [Native holdout parity](docs/nnue-v3/heldout-native-parity.json) · [Final audit](docs/nnue-v3/final-audit.json) · [Manifest](docs/nnue-v3/manifest.json).", "",
        "Native executables, build sidecars, compiler logs, source snapshots, checkpoints and preserved malformed-model probes remain local under the versioned artifact/training directories. Committed raw evidence, model files, source snapshots, build identities and generated figures support review. Original research and datasets remain intact.", ""]
    REPORT.write_text("\n".join(lines),encoding="utf-8",newline="\n")
    files=[p for p in ROOT.rglob("*") if p.is_file() and "-malformed" not in str(p.parent)
           and not p.name.endswith((".progress.json", ".tmp")) and p.name != "manifest.json"]
    files += [REPORT,Path("NNUE_V3_DESIGN.md"),*TRAIN.glob("*.json"),*Path("engine/networks/v3").glob("*.sbnnue")]
    files += list((TRAIN/"source-a").glob("*.py")) + list((TRAIN/"source-b").glob("*.py"))
    # New study text is canonical LF for byte hashes surviving Windows checkouts.
    for p in files:
        if p.suffix in (".json",".md",".pgn",".txt",".csv",".svg"):
            raw=p.read_bytes();canonical=raw.replace(b"\r\n",b"\n")
            if raw!=canonical:p.write_bytes(canonical)
    write(ROOT/"manifest.json",{"files":{p.as_posix():sha(p) for p in sorted(set(files))},
        "unchanged_sources":unchanged,"original_prepared_arrays_verified":True,
        "tools_lf_sha256": {p.as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
                            for p in sorted(Path('tools').glob('*nnue_v3*.py'))},
        "method":"Canonical LF new-study evidence, final report/design, model files and training reports. Scratch/checkpoint files excluded and retained locally."})
    print("Wrote",REPORT)


if __name__ == "__main__":
    main()
