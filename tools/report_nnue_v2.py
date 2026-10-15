"""Render the final report only after every predeclared tournament is complete."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path("docs/nnue-v2")


def read(name):
    return json.loads((ROOT / name).read_text())


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"] +
                     ["| " + " | ".join(str(v) for v in row) + " |" for row in rows])


def ratio(data, a, b):
    values = [p["summary"][a]["time"]["nps"]["median"] / p["summary"][b]["time"]["nps"]["median"]
              for p in data["positions"] if p["category"] != "king_attack"]
    return math.prod(values) ** (1 / len(values))


def head(data, label):
    return statistics.median(p["summary"][label]["micro"]["head_ns"]["median"] for p in data["positions"])


def rating(value, lower=False):
    return ("−∞" if lower else "+∞") if value is None else f"{value:+.0f}"


def main():
    destination = Path("NNUE_V2_OPTIMIZATION_RESULTS.md")
    if destination.exists():
        raise ValueError("Final report already exists; edit it explicitly rather than overwriting")
    baseline, final = read("baseline.json"), read("final-performance.json")
    validation, verification = read("final-validation.json"), read("verification.json")
    plan = read("match-plan.json")
    matches = []
    for item in plan["schedule"]:
        data = json.loads(Path(item["output"]).read_text())
        assert len(data["games"]) == item["games"] and data["opening_book_sha256"] == plan["opening_book_sha256"]
        matches.append((item, data))
    assert sum(len(data["games"]) for _, data in matches) == plan["planned_games"]
    binary_rows, binary_record = [], {}
    for model in ("compact", "small"):
        sizes = []
        for mode in ("original", "scalar"):
            record = final["configurations"][mode + "-" + model]
            binary = Path(record["executable"])
            assert hashlib.sha256(binary.read_bytes()).hexdigest() == record["sha256"]
            sizes.append(binary.stat().st_size)
        binary_rows.append([model, Path(f"engine/networks/v2/stockbear-v2-{model}.sbnnue").stat().st_size, *sizes])
        binary_record[model] = {"original_bytes": sizes[0], "retained_bytes": sizes[1],
                                "nps_speedup": ratio(final, "scalar-" + model, "original-" + model)}
    a_rows = []
    for label in ("classical", "v1", "compact", "small"):
        values = []
        for p in baseline["positions"]:
            if p["category"] in ("opening", "quiet_middlegame", "tactical", "pawn_endgame"):
                s = p["summary"][label]["time"]
                values.append(f"{s['nps']['median']/1e6:.2f}M / {s['depth']['median']:g}")
        a_rows.append([label, *values])
    p_rows = []
    for name in ("profile-original.json", "profile-final.json"):
        for model, record in read(name)["models"].items():
            totals = Counter()
            for sample in record["samples"]:
                totals.update({k: c["ns"] for k, c in sample["profile"]["categories"].items()})
            total = sum(totals.values())
            p_rows.append([name.removesuffix(".json"), model, *[f"{100*totals[k]/total:.1f}%" for k in
                ("nnue_head", "nnue_features", "nnue_update", "search_other")]])
    c_rows = []
    for stage, before, after in (("delta", "original", "delta"), ("scalar", "delta", "scalar"), ("simd", "scalar", "simd")):
        data = read(stage + ".json")
        c_rows.append([stage, *[f"{100*(ratio(data, after+'-'+m, before+'-'+m)-1):+.1f}%" for m in ("compact", "small")]])
    numerical = []
    phase_errors = []
    for model in ("compact", "small"):
        for mode in ("scalar", "quant"):
            r = validation["configurations"][mode + "-" + model]
            err = r["all"]
            numerical.append([model, mode, f"{r['golden']['max_cp']:.6f}", f"{err['mae_cp']:.4f}",
                              f"{err['rmse_cp']:.4f}", f"{err['max_cp']:.4f}", err["sign_disagreements"]])
            if mode == "quant":
                for category, values in r["by_category"].items():
                    if category.startswith("heldout_"):
                        phase_errors.append([model, category.removeprefix("heldout_"), values["n"],
                            f"{values['mae_cp']:.4f}", f"{values['rmse_cp']:.4f}", f"{values['max_cp']:.4f}", values["sign_disagreements"]])
    perf = []
    for model in ("compact", "small"):
        for mode in ("original", "scalar", "quant"):
            label = mode + "-" + model
            ns = head(final, label)
            perf.append([model, mode, f"{ns:.2f}", f"{1e3/ns:.2f}M", f"{ratio(final,label,'original-'+model):.3f}×",
                         final["positions"][0]["samples"][label]["micro"][0]["accumulator_bytes"]])
    search_rows = []
    for p in final["positions"]:
        search_rows.append([p["category"], *[f"{p['summary'][label]['time']['nps']['median']/1e6:.2f}M / {p['summary'][label]['time']['depth']['median']:g}"
            for label in ("classical", "scalar-compact", "scalar-small")]])
    game_rows, termination_rows = [], []
    for item, data in matches:
        if item["name"].startswith("smoke"):
            continue
        s = data["summary"]
        rate = s["rating_difference_estimate"]
        if rate is None:
            point = "−∞" if s["score_percent"] == 0 else "+∞" if s["score_percent"] == 100 else "undefined"
        else:
            point = f"{rate:+.0f}"
        game_rows.append([item["name"], item["movetime"], f"{s['wins']}/{s['draws']}/{s['losses']}", s["unfinished"],
                          f"{s['score_percent']:.1f}%", point,
                          f"[{rating(s['paired_rating_95_bound'][0], True)}, {rating(s['paired_rating_95_bound'][1])}]"])
        term = Counter(g["termination"] for g in data["games"])
        termination_rows.append([item["name"], "; ".join(f"{k}: {v}" for k,v in sorted(term.items()))])
    depth_rows = []
    for item, data in matches:
        if item["name"].startswith("smoke"):
            continue
        row = [item["name"]]
        for candidate in (True, False):
            searches = [s for g in data["games"] for s in g["searches"] if s["candidate"] == candidate]
            depth = statistics.mean(s["depth"] for s in searches)
            nps = sum(s["nodes"] for s in searches) / max(1e-9, sum(s["seconds"] for s in searches))
            row.append(f"{depth:.2f} / {nps/1e6:.2f}M")
        depth_rows.append(row)
    # Paired bounds are conditional on complete pairs; do not silently count caps as draws.
    conclusions = []
    for item, data in matches:
        if item["name"].startswith("smoke"):
            continue
        s = data["summary"]
        low, high = s["paired_score_95_bound"]
        if low > .5:
            finding = "nominal paired bound favors the candidate"
        elif high < .5:
            finding = "nominal paired bound favors the opponent"
        else:
            finding = "paired uncertainty includes equal strength"
        conclusions.append(f"- **{item['name']}:** {finding}; {s['complete_pairs']} complete pairs, {s['unfinished']} capped games.")
    intro = """# StockBear NNUE v2 optimization results

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
"""
    text = intro + "\n" + table(["Evaluator", "Opening", "Quiet middle", "Tactical", "Pawn ending"], a_rows)
    text += """

Exact executable/model hashes, build flags, FENs, moves, depths, actual nodes,
times and variability: [baseline JSON](docs/nnue-v2/baseline.json). A forced-mate
king-attack fixture completes early; its millisecond-granularity NPS is retained
in raw records but excluded from aggregate speed ratios. Equal node budgets
are search-work comparisons, not playing-strength evidence.

## B. Profiling findings

Internal `steady_clock` exclusive scopes covered three 300ms searches on five
categories per model. These percentages include clock-instrumentation overhead;
they are **not** release CPU-cycle proportions or release NPS comparisons.
""" + "\n" + table(["Build", "Model", "Head", "Full features", "Copy/update", "Other search"], p_rows)
    text += """

The original head, including clipping, dense arithmetic and weight access, was
the largest named cost. Feature extraction/sorting and accumulator bookkeeping
were also material. Replacing the head layout removed its long scalar dependency
chains; the remaining state-update share is now a useful next target. Copy,
board-derived update and rebuild latency are separately measured in the raw
microbenchmarks. Heap allocation is absent inside the normal inference/update
loops; search-level allocation counts include stacks and PV/reporting work.

WPR was installed; WPA/Visual Studio profiler were unavailable. No hardware
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
""" + "\n" + table(["Stage", "Compact", "Small"], c_rows)
    text += """

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
""" + "\n" + table(["Model", "Kernel", "Golden max cp", "MAE cp", "RMSE cp", "Max cp", "Sign differences"], numerical)
    text += """

Held-out quantization error by phase:

""" + table(["Model", "Phase", "Positions", "MAE cp", "RMSE cp", "Max cp", "Sign differences"], phase_errors) + """

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
"""
    proof_rows = [[m, *[f"{verification['quantization_proofs'][m][k]:,}" for k in
                       ("accumulator_abs_bound", "head_abs_bound", "output_abs_bound")]] for m in ("compact", "small")]
    text += "\n" + table(["Model", "Accumulator (74 rows)", "Dense", "Output"], proof_rows)
    text += f"""

Every value is below signed int32 capacity. The transient proof allows two full
37-feature sets during sorted changes. Earlier build sidecars report the final
37-row bound; [verification.json](docs/nnue-v2/verification.json) records the
stronger transient re-audit. Integer scalar/SIMD outputs matched exactly on the
full corpus before the SIMD prototype was removed.

Regression evidence:

- Full suite: **{verification['tests']['full_suite']}**; final shared-opening
  harness: **{verification['tests']['shared_opening_harness']}**.
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
""" + "\n" + table(["Model", "Kernel", "Head ns", "Raw eval/s", "NPS vs original", "Frame bytes"], perf)
    text += "\n\n200ms search **median NPS / completed depth**:\n\n" + table(["Category", "Classical", "Compact float", "Small float"], search_rows)
    text += f"""

Combined recovered NPS: **{100*(ratio(final,'scalar-compact','original-compact')-1):.1f}% Compact**,
**{100*(ratio(final,'scalar-small','original-small')-1):.1f}% Small**. Their throughput is
respectively {100*ratio(final,'scalar-compact','classical'):.1f}% and
{100*ratio(final,'scalar-small','classical'):.1f}% of the classical baseline in this suite.
Different evaluators produce different trees; these are practical throughput
observations, not proof that node quality is equivalent.

Full-process working sets during sampled 500ms searches were about 17.7–17.9MiB
for NNUE; TT/process overhead dominates. See [memory samples](docs/nnue-v2/memory.json).
Original models are 105,518 bytes (Compact) and 218,029 (Small). Derived integer
constants are 52,260 and 108,612 bytes but coexist with float/reference weights,
so the retained binary does **not** halve its deployment footprint. Exact binary
sizes/hashes/builds can be checked with the record paths and build sidecars.

""" + table(["Model", "Export bytes", "Original executable bytes", "Retained executable bytes"], binary_rows) + """

Quantized Compact was mixed by position; Small was consistently slower than
float. Float is preferred for both. Explicit SIMD failed to give a useful
end-to-end improvement over the compiler-vectorized portable implementation.
Repeated raw timings and all fixed-node/time results are in
[final-performance.json](docs/nnue-v2/final-performance.json).

## F. Playing-strength results

The [fixed plan](docs/nnue-v2/match-plan.json) ran **{plan['planned_games']} games**:
six smoke games at 25ms, 300 primary games at 50ms and 60 longer games at 200ms.
All used optimized scalar float, identical production search defaults, one
thread, Hash=16MB, paired openings/reversed colors, seed 20261016 and the same
[50-opening book](docs/nnue-v2/openings.json). No evaluator-based opening filter
or outcome-based stopping was used. Each match records exact binaries, models,
options, limits and every move; checkpoints support recovery.

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
""" + "\n" + table(["Match", "ms", "W/D/L", "Capped", "Score", "Relative Elo", "Paired 95% bound"], game_rows)
    text += "\n\nAverage completed depth / pooled nodes per engine-reported second:\n\n" + table(["Match", "Candidate depth / NPS", "Opponent depth / NPS"], depth_rows)
    text += "\n\nGame termination reasons:\n\n" + table(["Match", "Reasons"], termination_rows)
    text += "\n\n" + "\n".join(conclusions)
    text += """

All JSON/PGNs were independently replayed, outcome/claim/cap logic checked,
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
  (143.53 vs 143.93). These close metrics do not select a chess-strength winner.
- **Playing strength:** use the measured WDL and paired bounds above. Where a
  bound includes equal strength, the sample does not establish a winner.
  Short-control point estimates must not be promoted to definitive Elo gains;
  the smaller 200ms cohorts are especially uncertain.
- **Quantization:** small numerical error, no dependable benefit over optimized
  float; keep it experimental and opt-in. Original float remains preferred.
- **SIMD:** explicit prototypes passed correctness but did not justify their
  complexity. Keep the portable ordered-neuron loop and normal compiler
  vectorization. All validated prototype evidence remains available.
- **Classical competitiveness:** NNUE remains slower in this position suite;
  playing competitiveness is answered by the completed controlled matches,
  with their caps and uncertainty, rather than speed or teacher loss alone.
  Classical stays the product default as requested.
- **Next investigation (hypotheses):** reduce measured state-bookkeeping cost,
  consider lazy accumulator materialization at actual evaluation nodes, and
  test broader opening suites/longer controls. Further training changes should
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
"""
    head_to_head = [(i, d) for i, d in matches if i["name"] in ("primary-compact-small", "long-compact-small")]
    findings = " ".join(f"Compact scored {d['summary']['score_percent']:.1f}% against Small at {i['movetime']}ms/move ({d['summary']['wins']}/{d['summary']['draws']}/{d['summary']['losses']}, {d['summary']['unfinished']} capped)." for i,d in head_to_head)
    text = text.replace("- **Playing strength:** use the measured WDL and paired bounds above.", "- **Playing strength:** " + findings + " Use the measured paired bounds above.")
    classical_findings = " ".join(f"{i['name'].split('-')[1].title()} scored {d['summary']['score_percent']:.1f}% against classical at {i['movetime']}ms/move." for i,d in matches if i['name'].startswith(('primary-', 'long-')) and i['name'].endswith('-classical'))
    text = text.replace("  playing competitiveness is answered by the completed controlled matches,", "  " + classical_findings + " Playing competitiveness is answered by these matches,")
    (ROOT / "final-summary.json").write_text(json.dumps({"binaries": binary_record,
        "scheduled_games_completed": plan["planned_games"],
        "report_source_checkpoint": "0d37b15"}, indent=2) + "\n")
    destination.write_text(text, encoding="utf-8")
    print("Wrote", destination)


if __name__ == "__main__":
    main()
