"""Reproduce the scaling report from recorded training/validation/native results."""
from __future__ import annotations

import json
import os
from .common import file_hash
from .labeling.storage import atomic_json
from .scaling_train import EXPERIMENT, ROOT


def learning_curves(models: dict) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(EXPERIMENT / "artifacts/plot-cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for (name, label), color in zip(
            (("baseline", "32/16"), ("medium", "64/32"), ("large", "128/32")),
            ("#3c678c", "#cf771e", "#36846b")):
        rows = models[name]["history"]
        epochs = [r["epoch"] for r in rows]
        axes[0].plot(epochs, [r["validation"]["blended_mse"] for r in rows], color=color, label=label + " validation")
        axes[0].plot(epochs, [r["train_mse"] for r in rows], color=color, linestyle="--", alpha=.7, label=label + " training")
        selected = models[name]["best_epoch"]
        axes[0].scatter([selected], [rows[selected - 1]["validation"]["blended_mse"]], color=color, zorder=3)
        axes[1].step(epochs, [r["learning_rate"] for r in rows], where="post", color=color, label=label)
    axes[0].set(title="Probability MSE (dots: selected checkpoints)", xlabel="Epoch", ylabel="MSE")
    axes[1].set(title="Learning rate after each epoch", xlabel="Epoch", ylabel="Learning rate", yscale="log")
    for ax in axes:
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    fig.savefig(EXPERIMENT / "learning-curves.svg", metadata={"Date": None})
    plt.close(fig)


def generate() -> None:
    preserved = json.loads((EXPERIMENT / "preservation-before.json").read_text(encoding="utf-8"))
    after = {name: file_hash(ROOT.parent / name) for name in preserved}
    changed = [name for name in preserved if after[name] != preserved[name]]
    atomic_json(EXPERIMENT / "preservation-after.json", {
        "protected_files": len(preserved), "unchanged": not changed, "changed": changed,
        "sha256": after, "test_arrays_opened_or_hashed": False,
        "scope": "Baseline checkpoints/history, previous checkpoints, native sources/networks/active binaries, legacy training sources"})
    if changed:
        raise RuntimeError(f"Protected artifacts changed: {changed}")
    comparison = json.loads((EXPERIMENT / "comparison.json").read_text(encoding="utf-8"))
    native = json.loads((EXPERIMENT / "native-benchmark.json").read_text(encoding="utf-8"))
    models = comparison["models"]
    learning_curves(models)
    names = ("baseline", "medium", "large")
    labels = {"baseline": "32/16", "medium": "64/32", "large": "128/32"}
    base = models["baseline"]["validation"]
    winner = min(names, key=lambda n: models[n]["validation"]["blended_mse"])
    improvement = 100 * (1 - models[winner]["validation"]["blended_mse"] / base["blended_mse"])
    teacher_improvement = 100 * (1 - models[winner]["validation"]["teacher_probability_mse"] / base["teacher_probability_mse"])
    scalar = {n: native[n]["kernels"]["scalar"]["median_ns"] for n in names}
    head_ratio = scalar[winner]["head_ns"] / scalar["baseline"]["head_ns"]
    update_ratio = scalar[winner]["move_update_ns"] / scalar["baseline"]["move_update_ns"]
    marginal = 100 * (1 - models["large"]["validation"]["blended_mse"] / models["medium"]["validation"]["blended_mse"])
    lines = ["# StockBear NNUE Scaling Experiment Report", "", "## Executive summary", "",
        f"The **{labels[winner]}** model has the lowest selected-checkpoint validation blended MSE: "
        f"**{models[winner]['validation']['blended_mse']:.9f}**, a **{improvement:.2f}% reduction** versus the expanded 32/16 baseline. "
        f"Its teacher-probability MSE improves **{teacher_improvement:.2f}%**. On isolated native microbenchmarks its float head costs "
        f"**{head_ratio:.2f}×** and its move-derived accumulator update **{update_ratio:.2f}×** the baseline. "
        "These are measured evaluation costs, not whole-search slowdowns. No games were played and no Elo improvement is claimed.", "",
        "The test split was never opened, hashed or evaluated by the experiment. Existing engine sources, active binaries, "
        "exported networks, old checkpoints and baseline history were preserved; see the preservation receipt.", "",
        "## Architecture and data contract", "",
        "All models share 780 dual-perspective features: 12 relative piece/color classes × 64 squares, four relative castling "
        "rights and eight legal-en-passant files. There are at most 37 active features per perspective, with padding index 780. "
        "A shared sparse embedding sum plus bias forms each unclipped accumulator. Training input orders side-to-move first; "
        "native state stores White then Black and reorders only in the head. Both activations clip to [0,1]; the linear output is centipawns/400.", "",
        "| Architecture | Exact parameters | Float tensor bytes | Dense multiply-adds/evaluation | Float accumulator bytes |",
        "|---|---:|---:|---:|---:|"]
    for n in names:
        a = models[n]["architecture"]
        w, h, p = a["width"], a["hidden"], a["parameters"]
        lines.append(f"| {labels[n]} | {p:,} | {4*p:,} | {2*w*h+h:,} | {8*w:,} |")
    lines += ["", "Parameter counts come from `model.parameters()`, including the registered zero padding row. "
        "Formula: `782W + 2WH + 2H + 1`. The head arithmetic grows about 3.97×/7.91×; refresh/add-subtract work "
        "grows 2×/4× with accumulator width. Native frames also retain optional integer state and feature metadata, so their "
        "full allocation exceeds the float-only column.", "", "## Training controls and reproducibility", "",
        "The prepared v2 fingerprint is `" + comparison["dataset_fingerprint"] + "`. Training uses 4,616,965 positions and "
        "validation uses the identical 573,685 positions for every model. The 578,136-position test split remains sealed. "
        "Only train/validation arrays and ordinal files are checksum-verified and memory-mapped. The prepared manifest is read as metadata.", "",
        "All runs use seed 20261016, epoch shuffle `default_rng(seed + epoch)`, batch 2048, AdamW (fused CUDA), "
        "initial LR 0.0015, weight decay 0.05, gradient clipping 1.0, at most 60 epochs, patience 8, "
        "ReduceLROnPlateau patience 2/factor 0.5/minimum LR 1e-5, and deterministic algorithms with TF32 disabled. "
        "Target: `0.9 * sigmoid(clip(stm_cp,-2000,2000)/400) + 0.1 * stm_outcome`; loss is probability MSE.", "",
        "Runtime: PyTorch 2.7.1+cu128, NumPy 2.2.6, NVIDIA GeForce RTX 4050 Laptop GPU. Each larger model passed a two-full-epoch "
        "pilot with falling training/validation loss, finite gradients and <1 GiB peak allocation. Pilots resumed into full runs "
        "without resetting optimizer, scheduler or RNG. No schedule adjustment was indicated by these health checks. "
        "This controls the experiment; it does not establish the optimal schedule for every architecture.", "",
        "`stockbear.scaling_train` reuses the original model, batches, target and metrics. The legacy expanded trainer and model "
        "files are unchanged, preserving old resume signatures. New checkpoints store architecture, configuration, data/code/runtime "
        "identity and optimizer/scheduler/RNG state. Writes publish complete epochs atomically. Partial epochs replay on resume. "
        "`best.pt`, `raw_best.pt`, `last.pt` and `final.pt` have separate roles; no previous checkpoint was overwritten.", "",
        "## Baseline checkpoint investigation", "",
        "Expanded baseline training completed after **54 epochs**, stopping at eight epochs without a threshold-sized improvement. "
        "`best.pt` is **epoch 46**, MSE **0.011816098605106847**. The selection condition is strictly "
        "`value < selected_best - 0.00001`; the same threshold resets early-stopping patience. "
        "Epoch 53 achieved **0.01180995912419805**, only **0.000006139480908798** better, so it did not replace `best.pt`. "
        "This is the implemented threshold policy, not a corrupted metric or checkpoint.", "",
        "Epoch-53 weights were not saved and cannot be recovered from the history. Of the available weights, "
        "`last.pt` at **epoch 54** is numerically best, MSE **0.011810467727504072**. The primary comparison uses epoch 46 "
        "to match the exact checkpoint rule across all models. Epoch 54 is included as a sensitivity check. The new runs also "
        "save literal minima separately, without changing the primary selection or patience policy. Neither baseline was retrained.", "",
        "## Training and validation results", "",
        "| Metric | 32/16 | 64/32 | 128/32 |", "|---|---:|---:|---:|"]
    metrics = [("Parameters", lambda n: f"{models[n]['architecture']['parameters']:,}"),
               ("Selected validation blended MSE", lambda n: f"{models[n]['validation']['blended_mse']:.9f}"),
               ("Teacher probability MSE", lambda n: f"{models[n]['validation']['teacher_probability_mse']:.9f}"),
               ("Clipped CP MAE", lambda n: f"{models[n]['validation']['clipped_cp_mae']:.3f}"),
               ("Clipped CP RMSE", lambda n: f"{models[n]['validation']['clipped_cp_rmse']:.3f}"),
               ("Balanced CP MAE", lambda n: f"{models[n]['validation']['balanced_cp_mae']:.3f}"),
               ("Sign accuracy", lambda n: f"{100*models[n]['validation']['sign_accuracy_abs_cp_ge_100']:.3f}%"),
               ("Recorded epoch time total", lambda n: f"{models[n]['training_seconds']/60:.2f} min"),
               ("Epochs completed / selected", lambda n: f"{models[n]['completed_epochs']} / {models[n]['best_epoch']}"),
               ("Raw minimum epoch / MSE", lambda n: f"{models[n]['raw_minimum_history_epoch']} / {models[n]['raw_minimum_history_mse']:.9f}"),
               ("Selected-weight training MSE", lambda n: f"{models[n]['selected_training_metrics']['blended_mse']:.9f}"),
               ("Validation minus training MSE", lambda n: f"{models[n]['generalization_gap']:.9f}"),
               ("Peak CUDA allocated", lambda n: "Not recorded" if n == "baseline" else f"{models[n]['training_complete']['peak_cuda_allocated_bytes']/2**20:.2f} MiB")]
    lines += ["| " + label + " | " + " | ".join(formatter(n) for n in names) + " |" for label, formatter in metrics]
    lines += ["", "Centipawn errors clip both predictions and teacher scores to ±2000. Balanced CP MAE uses "
        "positions with |raw teacher CP| ≤500; sign accuracy uses |raw teacher CP| ≥100 and a strict prediction >0. "
        "Teacher probability uses clipped teacher CP. All selected checkpoints were reloaded and their saved validation MSE "
        "reproduced within 1e-7. Training duration sums measured epoch times, including pilots and validation; it excludes "
        "startup, verification, checkpoint writes, pauses and this investigation. Background native compilation affected some "
        "medium epochs, so duration is descriptive, not a controlled training-speed benchmark.", "",
        "### Differences relative to the selected baseline", "",
        "Entries are signed candidate-minus-baseline differences, followed by relative percent. Lower is better except sign accuracy; "
        "its absolute difference is shown in percentage points.", "",
        "| Metric | 64/32 Δ (relative %) | 128/32 Δ (relative %) |", "|---|---:|---:|"]
    for metric in ("blended_mse", "teacher_probability_mse", "clipped_cp_mae", "clipped_cp_rmse", "balanced_cp_mae", "sign_accuracy_abs_cp_ge_100"):
        cells = []
        for n in ("medium", "large"):
            d = models[n]["differences_vs_baseline"][metric]
            absolute = f"{100*d['absolute']:+.4f} pp" if metric.startswith("sign") else f"{d['absolute']:+.9f}"
            cells.append(f"{absolute} ({d['percent']:+.3f}%)")
        lines.append("| " + metric + " | " + " | ".join(cells) + " |")
    lines += ["", "### Phase analysis", "", "Material/ply-based phase metadata is consistent across sources. The old-v1 "
        "validation subset (4,569 positions) had no stored phase and received the same rule at preparation. These labels "
        "are deterministic heuristics, not annotated phase ground truth. Metrics below are teacher-probability MSE / clipped CP MAE.", "",
        "| Phase (positions) | 32/16 | 64/32 | 128/32 |", "|---|---:|---:|---:|"]
    for phase in ("opening", "middlegame", "endgame"):
        count = models["baseline"]["by_phase"][phase]["positions"]
        lines.append(f"| {phase} ({count:,}) | " + " | ".join(
            f"{models[n]['by_phase'][phase]['teacher_probability_mse']:.7f} / {models[n]['by_phase'][phase]['clipped_cp_mae']:.2f}" for n in names) + " |")
    lines += ["", "### Generalization, uncertainty and diminishing returns", "",
        "Selected-weight train/validation gaps above distinguish generalization from training fit; epoch training loss also "
        "averages weights changing throughout the epoch and should not be treated as the selected model's exact training score. "
        "The learning curves show plateaus and the effect of LR reductions. These are development-set results after repeated "
        "checkpoint selection, not unbiased test estimates.", ""]
    for n in ("medium", "large"):
        ci = models[n]["paired_uncertainty"]
        low, high = ci["paired_game_bootstrap_95_percentile_interval"]
        lines.append(f"- {labels[n]} teacher-MSE difference: {ci['teacher_mse_difference']:+.9f}; paired game-bootstrap "
                     f"95% interval [{low:+.9f}, {high:+.9f}] over {ci['games']:,} validation game families (1,000 replicates).")
    lines += ["", "The selected-weight validation-minus-training gaps are " + ", ".join(
        f"{labels[n]}: {models[n]['generalization_gap']:.7f}" for n in names) + ". "
        "A wider gap shows additional capacity fitting training data more closely; lower selected validation error still "
        "demonstrates improved holdout teacher prediction for this seed. Late-epoch drift above the literal minimum is " + ", ".join(
        f"{labels[n]}: {models[n]['history'][-1]['validation']['blended_mse']-models[n]['raw_minimum_history_mse']:.8f}"
        for n in names) + ". This quantifies late plateau/overfit rather than judging from training loss alone.", "",
        "![Training and validation learning curves](StockBear_NNUE_training/scaling-experiment-20261016/learning-curves.svg)"]
    lines += ["", "These intervals resample matched game families; they do not include training-seed uncertainty, repeated model "
        "selection or source-distribution shift. Only one training seed was run per architecture. "
        f"The 128/32-versus-64/32 blended-MSE change is a {marginal:.2f}% reduction, for roughly twice the parameters and "
        "twice the dense head arithmetic. Do not infer an Elo return from this marginal teacher-fit gain.", "",
        "### Baseline sensitivity and literal-minimum checkpoints", "",
        "| Model / checkpoint | Epoch | Validation blended MSE |", "|---|---:|---:|"]
    for n in names:
        for filename, item in models[n]["auxiliary_checkpoints"].items():
            lines.append(f"| {labels[n]} / {filename} | {item['epoch']} | {item['validation']['blended_mse']:.9f} |")
    available_baseline = models["baseline"]["auxiliary_checkpoints"]["last.pt"]["validation"]["blended_mse"]
    lines += ["", "Against the numerically best available baseline weights (epoch 54), the selected "
              "candidate blended-MSE reductions are " + ", ".join(
                  f"{labels[n]}: {100*(1-models[n]['validation']['blended_mse']/available_baseline):.2f}%"
                  for n in ("medium", "large")) + ". The primary comparison is therefore not dependent on treating the "
              "threshold-selected baseline as its literal minimum."]
    lines += ["", "## Native inference compatibility and measured cost", "",
        "The model file format and header generator already support width ≤256 and hidden ≤128. "
        "`nnue_dimensions.hpp` and the embedded `WIDTH`/`HIDDEN` constants determine compile-time accumulator and head sizes; "
        "there is no fixed 32/16 requirement. All three models compile through the unchanged native evaluator. "
        "Changing an embedded architecture requires rebuilding a binary, not changing the search algorithm. "
        "The legacy export CLI assumes legacy test artifacts and is unsuitable here; the isolated exporter derives/validates "
        "legacy dimensions and writes the same float32 format without any test access.", "",
        "Native state keeps unclipped White/Black sums, copies parents into distinct child storage, and applies move deltas "
        "for ordinary moves, captures, promotions, castling and en passant; castling/EP state features are checked after the move. "
        "Roots refresh fully; null moves preserve piece sums and update state/perspective. "
        "For every architecture and kernel, the existing verification suite exercised 31,876 move transitions and 26,908 "
        "null moves, plus sibling/board restoration and clipping boundaries. Compact search updates matched the reference "
        "update bits. This verifies isolated accumulator behavior, not whole-search or UCI integration of new networks.", "",
        "Benchmarks used unchanged production inference with isolated `nnue-bench` binaries, Zig C++17 `-O2`, "
        "`-ffp-contract=off`, default compact update strategy, on the i5-13420H. Twelve validation positions (four per phase), "
        "five repeats and 20,000 calls per operation/repeat were used. Values are medians across 60 hot per-position samples. "
        "There was no concurrent training during final measurements. CPU scheduling/frequency and hot-cache effects remain; "
        "this is not a search NPS benchmark.", "",
        "| Float operation (ns) | 32/16 | 64/32 | 128/32 |", "|---|---:|---:|---:|"]
    for metric in ("feature_ns", "copy_ns", "move_update_ns", "refresh_ns", "head_ns"):
        lines.append("| " + metric + " | " + " | ".join(f"{scalar[n][metric]:.1f}" for n in names) + " |")
    lines += ["", "Move-update timings include state-feature handling and parent copying; the benchmark times the move-derived "
        "update, not a complete search node. The separately verified compact search path is not timed as a search workload. "
        "Full refresh is a root/fallback cost; it should not be charged at every node.", "",
        "### Export parity and optional integer inference", "",
        "| Architecture | Float max CP error | Quant max CP error | Quant head ns | Quant update ns | Native frame bytes |",
        "|---|---:|---:|---:|---:|---:|"]
    for n in names:
        s, q = native[n]["kernels"]["scalar"], native[n]["kernels"]["quant"]
        lines.append(f"| {labels[n]} | {s['max_cp_error_vs_torch']:.6f} | {q['max_cp_error_vs_torch']:.6f} | "
                     f"{q['median_ns']['head_ns']:.1f} | {q['median_ns']['move_update_ns']:.1f} | {s['samples'][0]['accumulator_bytes']:,} |")
    lines += ["", "Parity used the same 128 seeded validation FENs, including both sides to move; float tolerance 0.01 CP "
        "and experimental quantized tolerance 5 CP. The integer representation is derived separately with overflow bounds. "
        "Passing this small parity set does not establish full-distribution quantization quality or safe deployment.", "",
        "The current `auto` kernel resolves to the scalar float implementation. Its transposed head exposes independent "
        "neurons to compiler vectorization, but AVX2 availability does not mean a dedicated AVX2 kernel is selected. "
        "Widths 64/128 and hidden 32 suit SIMD lanes. Explicit SIMD and quantization could reduce bandwidth/arithmetic, "
        "but must preserve accumulation order/parity or document numerical changes; optional integer timings above are "
        "measurements, not guaranteed improvements. Search-level cache pressure, frame copying and evaluation frequency "
        "still determine the actual equal-time trade-off.", "",
        "## Recommendation and next stage", "",
        f"Advance **{labels[winner]}** as the best teacher-prediction candidate, retaining **64/32** and **32/16** as "
        "cost/quality controls. Its validation gain justifies isolated native search-strength testing, not replacement of the "
        "active evaluator. Compare unchanged-search binaries under equal time with paired openings, and measure total NPS, "
        "completed depth, evaluation/update frequency and memory traffic alongside game scores. Retain classical as default.", "",
        "Do not train 256/32 in this experiment. First determine whether the observed 128/32-versus-64/32 improvement "
        "survives a second training seed and whether its extra native cost is repaid in equal-time games. A larger model "
        "would double accumulator width/head arithmetic again; teacher MSE alone is insufficient justification for that expense.", "",
        "## Checkpoints, outputs and reproduction", "",
        "All new outputs are beneath `Z:\\Code\\Chess\\StockBear_NNUE_training\\scaling-experiment-20261016\\`. "
        "Only this explicitly requested report is written at the repository root. Checkpoints are local, ignored research "
        "artifacts; code/configuration/results/identities are versioned. Absolute selected-checkpoint paths:", ""]
    for n in names:
        lines += [f"- **{labels[n]} selected:** `{models[n]['checkpoint']}` (epoch {models[n]['best_epoch']}, SHA-256 `{models[n]['sha256']}`)."]
        if n != "baseline":
            run = (ROOT / models[n]["config"]["run"]).resolve()
            for filename in ("raw_best.pt", "last.pt", "final.pt", "history.json", "training.json"):
                lines.append(f"- **{labels[n]} {filename}:** `{run / filename}`.")
    lines += ["", "Full epoch metrics, paired uncertainty and auxiliary checkpoint results are in "
        "`comparison.json`; native samples, build flags and source hashes are in `native-benchmark.json`. "
        "`validation-goldens.json` records validation-only benchmark provenance. `baseline-audit.json`, "
        "`pilot-health.json`, `phase-provenance.json` and `preservation-after.json` retain the investigation evidence. "
        "Native exports/binaries and logs are under `artifacts/native/{baseline,medium,large}/`. "
        "The export `payload_sha256` and full file hashes are recorded. No tournament or label-generation process was launched.", "",
        "From the training root in PowerShell:", "", "```powershell",
        r"Set-Location Z:\Code\Chess\StockBear_NNUE_training",
        r".\.venv\Scripts\python.exe -m stockbear.scaling_train check --config scaling-experiment-20261016/medium.json",
        r"# Fresh reproduction requires a new artifacts run path in a copied configuration.",
        r".\.venv\Scripts\python.exe -m stockbear.scaling_train train --config scaling-experiment-20261016/medium.json --resume",
        r".\.venv\Scripts\python.exe -m stockbear.scaling_train train --config scaling-experiment-20261016/large.json --resume",
        r".\.venv\Scripts\python.exe -m stockbear.scaling_analysis compare",
        r".\.venv\Scripts\python.exe -m stockbear.scaling_analysis native",
        r".\.venv\Scripts\python.exe -m stockbear.scaling_report",
        "```", "",
        "A completed-run resume validates identity and restores the final state without additional epochs. "
        "Do not alter dimensions, hyperparameters or signed training sources in a resumable run. "
        "The native benchmark command overwrites only its own generated benchmark binaries/reports; different existing "
        "export bytes are refused. Old dataset preparation/training entry points remain available.", "",
        "Validation: 15 focused tests passed (three architectures, legacy/new load, shape/count rejection, mmap checksum/test isolation, "
        "exact CPU resume equivalence, metric definitions and isolated native-format export). Full native transition, null, "
        "compact-update and validation-FEN parity checks passed for every measured model/kernel. "
        "No desktop game check was needed because the application and active engine were not changed.", ""]
    output = ROOT.parent / "NNUE_SCALING_EXPERIMENT_REPORT.md"
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(output)


if __name__ == "__main__":
    generate()
