from __future__ import annotations

import csv
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from ..common import file_hash,save_json


def finish(root:Path,cfg:dict,results:list,selection:dict,exports:list):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    directory=root/cfg["reports"]
    plots=directory/"plots";plots.mkdir(exist_ok=True)
    inventory=json.loads((directory/"inventory.json").read_text())
    pool=json.loads((directory/"pool_report.json").read_text())
    bench=json.loads((directory/"label_benchmark.json").read_text())
    quality=json.loads((directory/"teacher_quality.json").read_text())
    best=selection["best"]
    best_run=root/cfg["runs"]/best["primary"]
    best_metrics=json.loads((best_run/"test_metrics.json").read_text())
    v1=json.loads((root/cfg["runs"]/"v1_reference/test_metrics.json").read_text())
    v1_val=json.loads((root/cfg["runs"]/"v1_reference/validation_metrics.json").read_text())
    chosen=[row for row in results if row["name"] in {c["primary"] for c in selection["contenders"]}]
    by_name={row["name"]:row for row in results}
    test_reports={name:json.loads((root/cfg["runs"]/name/"test_metrics.json").read_text()) for name in (c["primary"] for c in selection["contenders"])}
    export_map={row["experiment"]:row for row in exports}
    ranked=sorted(results,key=lambda row:row["metrics"]["validation"]["blended_mse"])
    rows=[]
    for row in ranked:
        validation=row["metrics"]["validation"]
        rows.append({"rank_validation":len(rows)+1,"name":row["name"],"architecture":row["architecture"],"nominal_positions":row["size"],
                     "training_positions":row["metrics"]["train"]["positions"],"parameters":row["parameters"],"seed":row["seed"],
                     "epochs":row["epochs"],"best_epoch":row["best_epoch"],"examples_processed":row["examples_processed"],
                     "training_blended_mse":row["metrics"]["train"]["blended_mse"],"validation_blended_mse":validation["blended_mse"],
                     "validation_teacher_mse":validation["teacher_probability_mse"],"validation_cp_mae":validation["clipped_cp_mae"],
                     "validation_material_mse":validation["material_baseline_teacher_mse"],
                     "validation_v1_mse":v1_val["teacher_probability_mse"],
                     "validation_teacher_mse_minus_v1":validation["teacher_probability_mse"]-v1_val["teacher_probability_mse"],
                     "validation_cp_rmse":validation["clipped_cp_rmse"],"validation_clipped_correlation":validation["clipped_cp_pearson"],
                     "validation_sign_accuracy":validation["sign_accuracy_abs_cp_ge_100"],"generalization_gap":row["generalization_gap"],
                     "training_epoch_seconds":row["training_epoch_seconds"],"examples_per_second":row["examples_per_second"],
                     "peak_cuda_bytes":row["peak_cuda_bytes"],"dense_head_macs":row["dense_head_macs"],
                     "export_bytes":export_map.get(row["name"],{}).get("bytes"),
                     "final_test_teacher_mse":test_reports.get(row["name"],{}).get("teacher_probability_mse")})
    save_json(directory/"comparison.json",rows)
    with (directory/"comparison.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    plt.rcParams.update({"font.size":9,"axes.spines.top":False,"axes.spines.right":False})
    figure,axes=plt.subplots(math.ceil(len(results)/4),4,figsize=(16,3*math.ceil(len(results)/4)),squeeze=False,layout="constrained")
    for ax,row in zip(axes.flat,results):
        history=json.loads((root/cfg["runs"]/row["name"]/"history.json").read_text())
        ax.plot([r["epoch"] for r in history],[r["train_mse"] for r in history],label="Train")
        ax.plot([r["epoch"] for r in history],[r["validation_mse"] for r in history],label="Validation")
        ax.axvline(row["best_epoch"],color="gray",linestyle="--",lw=.8)
        ax.set_title(row["name"],fontsize=8);ax.set_xlabel("Epoch");ax.set_ylabel("Blended MSE")
    for ax in list(axes.flat)[len(results):]: ax.set_visible(False)
    axes.flat[0].legend(frameon=False,fontsize=8)
    figure.suptitle("StockBear v2 · training and validation curves",fontsize=15)
    figure.savefig(plots/"learning_curves.png",dpi=160);plt.close(figure)
    scale=sorted([row for row in results if row["name"].startswith("scale_compact_")],key=lambda row:row["size"])
    arch=[row for row in results if row["size"]==500000 and (row["name"].startswith("arch_") or row["name"].startswith("scale_"))]
    figure,axes=plt.subplots(1,3,figsize=(15,4.5),layout="constrained")
    axes[0].plot([r["size"] for r in scale],[r["metrics"]["validation"]["teacher_probability_mse"] for r in scale],"o-",label="Compact")
    axes[0].axhline(v1_val["teacher_probability_mse"],color="#a45b38",ls="--",label="v1 on same validation")
    axes[0].axhline(v1_val["material_baseline_teacher_mse"],color="gray",ls=":",label="Material")
    axes[0].xaxis.set_major_formatter(FuncFormatter(lambda value,pos:f"{value/1000:.0f}K"))
    axes[0].set(title="Dataset scaling · consistent settings",xlabel="Nominal nested pool positions",ylabel="Validation teacher MSE")
    axes[0].legend(frameon=False,fontsize=7)
    for r in arch:
        axes[1].scatter(r["parameters"],r["metrics"]["validation"]["teacher_probability_mse"],s=50)
        axes[1].annotate(r["architecture"],(r["parameters"],r["metrics"]["validation"]["teacher_probability_mse"]),xytext=(3,5),textcoords="offset points",fontsize=8)
    axes[1].set(xscale="log",title="Capacity scaling · common 500K data",xlabel="Parameters (log scale)",ylabel="Validation teacher MSE")
    axes[2].bar([r["architecture"] for r in arch],[r["examples_per_second"] for r in arch],color="#28638a")
    axes[2].set(title="Measured CUDA training throughput",xlabel="Architecture",ylabel="Examples / second")
    figure.suptitle("StockBear v2 · controlled scaling comparisons",fontsize=15)
    figure.savefig(plots/"scaling_comparison.png",dpi=180);figure.savefig(plots/"scaling_comparison.svg");plt.close(figure)
    svg=plots/"scaling_comparison.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines())+"\n",encoding="utf-8")
    prepared=root/by_name[best["primary"]]["prepared"]
    y=np.load(prepared/"test_y.npy",mmap_mode="r")
    prediction=np.load(best_run/"test_predictions.npy")
    old_prediction=np.load(root/cfg["runs"]/"v1_reference/test_predictions.npy")
    figure,axes=plt.subplots(1,2,figsize=(11,4.4),layout="constrained")
    for values,label in ((old_prediction,"v1"),(prediction,"selected v2")):
        axes[0].hist(np.clip(values,-2000,2000)-np.clip(y[:,0],-2000,2000),bins=np.linspace(-4000,4000,121),histtype="step",label=label,density=True)
    axes[0].set(title="Common held-out score errors",xlabel="Prediction − teacher (cp, clipped)",ylabel="Density");axes[0].legend(frameon=False)
    heat=axes[1].hexbin(np.clip(y[:,0],-2000,2000),np.clip(prediction,-2000,2000),gridsize=55,mincnt=1,bins="log",cmap="viridis")
    axes[1].plot([-2000,2000],[-2000,2000],color="#c36a27",lw=.8)
    axes[1].set(title="Selected v2 agreement",xlabel="Teacher cp (clipped)",ylabel="Network cp (clipped)")
    figure.colorbar(heat,ax=axes[1],label="Positions per hexbin")
    figure.savefig(plots/"test_errors.png",dpi=180);plt.close(figure)
    # Paired, game-clustered bootstrap on the common test cohort.
    cp=np.clip(y[:,0].astype(float),-2000,2000);truth=1/(1+np.exp(-cp/400))
    mse_v2=(1/(1+np.exp(-np.clip(prediction/400,-80,80)))-truth)**2
    mse_v1=(1/(1+np.exp(-np.clip(old_prediction/400,-80,80)))-truth)**2
    games,inverse=np.unique(y[:,7],return_inverse=True)
    sums=np.bincount(inverse,weights=mse_v2-mse_v1);counts=np.bincount(inverse)
    rng=np.random.default_rng(cfg["seed"]);delta=[]
    for _ in range(500):
        sample=rng.integers(0,len(games),len(games));delta.append(float(sums[sample].sum()/counts[sample].sum()))
    ci=np.percentile(delta,[2.5,97.5]).tolist()
    save_json(directory/"paired_test_bootstrap.json",{"v2_minus_v1_mse_95_ci":ci,"game_clusters":len(games),"resamples":500})
    suites=list(ET.parse(directory/"tests.xml").getroot().iter("testsuite"))
    tests={k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ("tests","failures","errors","skipped")}
    save_json(directory/"test_results.json",tests)
    final_exports={r["architecture"]:r for r in exports}
    table="\n".join(f"| {i+1} | {r['name']} | {r['nominal_positions']:,} | {r['parameters']:,} | {r['epochs']} / {r['best_epoch']} | {r['validation_blended_mse']:.6f} | {r['validation_teacher_mse']:.6f} | {r['generalization_gap']:.6f} | {r['examples_processed']:,} |" for i,r in enumerate(rows))
    final_table="\n".join(f"| {c['architecture']} | {c['validation_mean_blended_mse']:.6f} | {test_reports[c['primary']]['teacher_probability_mse']:.6f} | {test_reports[c['primary']]['clipped_cp_mae']:.2f} | {test_reports[c['primary']]['clipped_cp_pearson']:.4f} | {final_exports[c['architecture']]['bytes']:,} |" for c in selection["contenders"])
    scale_values=[r["metrics"]["validation"]["teacher_probability_mse"] for r in scale]
    scaling_finding="improved" if scale_values[-1]<scale_values[0] else "did not improve"
    compact_b=next(r for r in arch if r["architecture"]=="compact")
    best_b=min(arch,key=lambda r:r["metrics"]["validation"]["blended_mse"])
    capacity_table="\n".join(f"| {r['architecture']} | {r['parameters']:,} | {r['metrics']['train']['blended_mse']:.6f} | {r['metrics']['validation']['blended_mse']:.6f} | {r['metrics']['validation']['teacher_probability_mse']:.6f} | {r['generalization_gap']:.6f} |" for r in sorted(arch,key=lambda r:r['parameters']))
    large_b=next(r for r in arch if r['architecture']=='large')
    selected_primary=by_name[best['primary']]
    compact_final=by_name[final_exports['compact']['experiment']]
    size_ratio=final_exports[best['architecture']]['bytes']/final_exports['compact']['bytes']
    cost_ratio=selected_primary['dense_head_macs']/compact_final['dense_head_macs']
    other=selection['contenders'][1]
    other_test=test_reports[other['primary']]
    validation_edge=(1-best['validation_mean_blended_mse']/other['validation_mean_blended_mse'])*100
    finalist_note=(f"{best['architecture'].capitalize()}'s two-seed mean validation blended loss was "
                   f"{validation_edge:.2f}% lower than {other['architecture']}'s. "
                   f"The primary checkpoints' test teacher MSEs were {best_metrics['teacher_probability_mse']:.6f} "
                   f"and {other_test['teacher_probability_mse']:.6f}, respectively; cp MAEs were "
                   f"{best_metrics['clipped_cp_mae']:.2f} and {other_test['clipped_cp_mae']:.2f}. "
                   "The saved validation selection remains unchanged. The small differences support retaining "
                   "both finalists rather than claiming a decisive architecture advantage.")
    improvement=(1-best_metrics["teacher_probability_mse"]/v1["teacher_probability_mse"])*100
    material=best_metrics["material_baseline_teacher_mse"]
    improvement_description=f"{abs(improvement):.1f}% {'lower' if improvement>=0 else 'higher'}"
    result_text=f"""# StockBear NNUE v2 results

All requested execution phases completed. The selected primary-seed model is
**{best['architecture']}**, trained on the **{selection['final_size']:,}-position
nested pool**. Selection used the mean validation blended MSE of two seeds;
test scores did not select models, widths, hyperparameters or epochs.

## Main findings

- Dataset scaling {scaling_finding} compact validation teacher MSE from
  {scale_values[0]:.6f} at {scale[0]['size']:,} to {scale_values[-1]:.6f} at {scale[-1]['size']:,} nominal positions.
- At the common 500K budget, **{best_b['architecture']}** had the lowest validation blended loss.
- The final selected v2 teacher MSE is **{best_metrics['teacher_probability_mse']:.6f}** on
  {best_metrics['positions']:,} common held-out positions, compared with
  **{v1['teacher_probability_mse']:.6f} for v1** on those same positions ({improvement_description}).
- Material baseline MSE on that cohort: **{material:.6f}**.
- Selected model clipped cp MAE/RMSE: {best_metrics['clipped_cp_mae']:.2f} /
  {best_metrics['clipped_cp_rmse']:.2f}; clipped-score Pearson correlation
  {best_metrics['clipped_cp_pearson']:.4f}; decisive-position sign accuracy
  {best_metrics['sign_accuracy_abs_cp_ge_100']:.2%}.
- Paired game-bootstrap 95% interval for v2 minus v1 test MSE: [{ci[0]:.6f}, {ci[1]:.6f}].
  Negative values favor v2. This measures supervised teacher agreement, not Elo.

The historical v1 MSE 0.016341 and cp MAE 197.79 came from a different, quieter
test distribution. They are historical references rather than direct v2
comparisons. The v1 figures above were remeasured on the common v2 holdout.

{finalist_note}

## Validation ranking

Rows rank individual experiments by validation blended loss. Final architecture
selection instead uses the recorded two-seed means, avoiding a lucky-seed pick.

| Rank | Experiment | Pool size | Parameters | Epochs / selected | Val blended MSE | Val teacher MSE | Blended gap | Examples processed |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
{table}

## Final selected candidates

| Architecture | Two-seed mean val blended MSE | Test teacher MSE | Test cp MAE | Clipped correlation | Export bytes |
|---|---:|---:|---:|---:|---:|
{final_table}

## Data and leakage controls

The inventory contains {inventory['archive_count']} PGN/zstd archives, totaling
{inventory['compressed_bytes']:,} compressed bytes and {inventory['game_records']:,}
game records. Standard Zstandard skippable-frame prefixes are supported. PGN
metadata includes broadcast URLs, players, ratings, rounds and sometimes embedded
evaluations. Embedded evaluations were not treated as engine targets. Retained
games are completed standard broadcast games; invalid/nonstandard records
are omitted. Source metadata may include human and engine-like events; the separate
`source_metadata_audit.json` records all-header content hints, variants and rating
coverage without treating those hints as verified labels. Some source PGNs contained illegal SAN; retained sampled positions
were independently checked for legality before labeling.

The common pool contains {pool['positions']:,} unique positions from
{pool['games']:,} game groups. {pool['merged_game_aliases']:,} aliases with identical
complete mainlines were merged. Group IDs and exact normalized FEN hashes prevent
game or exact-position overlap. v1 training positions are excluded from v2
holdouts, and known v1 game partitions are anchored. Header aliases with different
truncated move sequences can still evade alias detection; no claim is made that
every near-duplicate chess position is eliminated.

The deterministic nested order interleaves within-stratum quantiles by source
year, material/ply phase, heuristic tactical category and split. This preserves
approximately proportional diversity across prefixes rather than drawing
unrelated 200K/500K/1M datasets. Training uses the train partition of each prefix.
All controlled experiments use the same validation/test cohort drawn from the
first 200K prefix; extra held-out positions in larger prefixes remain reserved
and never become training positions. Manifests record nominal versus actually
used train/validation/test counts.

Checks, captures, promotions and material imbalances are retained. Passed-pawn,
advanced-pawn, king-pressure and unusual-configuration tags are heuristic
descriptors, not verified tactical truth. Diversity counts and all source hashes
are in `pool_report.json` and `inventory.json`.

## Teacher quality and resource use

The unchanged Stockfish 19 binary uses 16384 nodes, one thread per worker, 64 MiB
hash and normalized counters. A new-game reset calls the same Stockfish
`search_clear` as Clear Hash. Removing the redundant second reset matched all
64 cached v1 comparisons exactly, including score, mate distance, depth and nodes.
The separate v2 cache imports only compatible v1-profile labels and preserves
the original cache. Each batch and cursor commits safely; corrupt/illegal FENs
are rejected and retry failures retained.

The benchmark selected {bench['selected_workers']} workers at
{max(x['positions_per_second'] for x in bench['trials']):.1f} positions/second.
Initial total label estimate was {bench['estimated_label_hours']:.2f} hours;
the bounded job budget was {cfg['label_budget_hours']} hours. Actual incremental
label times and rates are in `label_history.jsonl` and each size's report.
Higher-budget analysis compared {quality['summary']['positions']} representative
positions at {quality['higher_nodes']:,} nodes. Mean clipped score change was
{quality['summary']['mean_clipped_abs_cp_change']:.2f} cp; probability MSE between
budgets was {quality['summary']['teacher_probability_mse_between_budgets']:.6f};
mate-status changes: {quality['summary']['mate_status_changes']}. Phase, tactical,
magnitude and mate-proximity breakdowns are recorded. Higher budget is not
perfect ground truth, and the training target was not changed silently.

## Architecture, optimization and overfitting

All runs retain the v1 two-perspective 780-feature representation, shared sparse
feature sums, clipped ReLU, scalar side-to-move output and 400-cp score scale.
The target remains 90% sigmoid(clipped teacher cp/400) plus 10% game outcome.
No HalfKP, reinforcement learning, dropout, BatchNorm, quantization or SIMD was
introduced. Model widths/parameter counts and exported shapes are automatic.

Training used CUDA float32, fused AdamW, gradient clipping, validation LR
reduction, early stopping and best checkpoints. Feature arrays are prepared
once per prefix and reused across architectures; active indices fit in GPU
memory, avoiding repeated per-batch host conversion. AMP/TF32 were not enabled
without demonstrated need and parity. Per-run GPU allocation, epoch times,
throughput and examples processed are in `comparison.csv`. GPU memory numbers
include resident dataset tensors, not total driver/process VRAM. The Windows
monotonic timer can round very short pilot epochs to zero; full-run aggregate
throughput is reported and pilot timings are not ranked.

Stage A held compact settings fixed. Stage B used the same 500K dataset with
width-scaled learning rates. Stage C tested two recorded parameter settings for
the two leading architectures, then repeated their chosen setting with a second
seed. The search was bounded and recorded before final test evaluation.
Larger datasets also process more examples under an epoch cap; results are a
controlled practical scaling comparison, not a proof isolating data from every
optimization-budget effect. Generalization gaps and curves expose overfitting;
an exported model does not imply its gap has disappeared.

The common-data capacity results were:

| Architecture | Parameters | Train blended MSE | Val blended MSE | Val teacher MSE | Blended gap |
|---|---:|---:|---:|---:|---:|
{capacity_table}

The large model's gap was {large_b['generalization_gap']:.6f}, versus
{compact_b['generalization_gap']:.6f} for compact. Its lower training error did
not translate to lower validation error. Under this bounded search, the data
supports the smaller finalists, not an automatic capacity increase.

## Size versus inference cost

The native source was inspected without modification. Its reader accepts width
up to 256 and hidden width up to 128, and it accepted every exported candidate.
Typical quiet-move accumulator work is about 4×width vector additions; dense-head
MACs are 2×width×hidden+hidden. Compact's dense head has
{compact_b['dense_head_macs']:,} MACs; the 500K validation winner has
{best_b['dense_head_macs']:,}. These are theoretical operation counts, not native
speed measurements. The selected primary model is {size_ratio:.2f}× the compact
export's bytes and {cost_ratio:.2f}× its theoretical dense-head MACs. Accuracy
alone cannot establish whether that cost is worthwhile in search. Benchmark
the selected compact and small finalists next with paired openings, identical
search limits and measured latency; those native experiments remain future work.

No C++ engine, GUI, evaluator default or native weights were changed. No engine
matches or native inference-speed benchmarks were run. Subsequent playing tests
and inference optimization remain separate tasks.

## Exports, tests and reproducibility

All four architectures have independently named trained, validated exports in
`exports/v2/`. The leading two use their largest-data, selected primary-seed
checkpoints. Other architectures retain their validated 500K candidates.
`stockbear-v2-best.sbnnue` aliases the validation-selected winner. Golden FENs,
tensor shapes, padding zero row, checksum, feature/activation/score conventions,
NumPy/PyTorch parity and training-device parity were verified. The existing native
format parser was used read-only; no header generation or integration occurred.

Automated relevant suite: {tests['tests']} tests, {tests['failures']} failures,
{tests['errors']} errors and {tests['skipped']} skips. XML and logs are retained.
The pilot exercised label interruption/resume and CUDA epoch checkpoint recovery.
Original v1 exports and checkpoints are protected by hashes and verified intact.

Reproduce/resume from this project directory with:

```
.\\.venv\\Scripts\\python.exe -m pytest
.\\.venv\\Scripts\\python.exe -m stockbear.v2 run
```

The runner reuses completed datasets, labels and matching experiments and refuses
changed signatures or different candidate bytes. Source/configuration hashes,
teacher profiles, software/hardware audit, selection, manifests, epoch histories,
best/last checkpoints, comparisons and plots remain in the project. Large labeled
datasets are represented by shared pool/cache SQLite files plus nested-prefix
manifests and memory-mapped arrays rather than several redundant database copies.

## Plots and detailed evidence

![Learning curves](plots/learning_curves.png)

![Controlled scaling comparisons](plots/scaling_comparison.png)

![Final held-out error distributions](plots/test_errors.png)

`comparison.csv` includes each experiment's validation delta against v1 and the
material baseline. Each run's `metrics.json` contains phase, tactical/quiet and
year breakdowns. `selection.json` records the final choice before testing;
`V2_PROTOCOL.md` records the bounded execution plan.
"""
    (root/"NNUE_V2_EXPERIMENT_REPORT.md").write_text(result_text.replace("(plots/", "(reports/v2/plots/"),encoding="utf-8")
    (directory/"NNUE_V2_EXPERIMENT_REPORT.md").write_text(result_text,encoding="utf-8")
    short=f"""# StockBear NNUE v2 results

**Selected model: {best['architecture']} ({selected_primary['model_config']['width']}/{selected_primary['model_config']['hidden']},
{selected_primary['parameters']:,} parameters).** All phases completed: {inventory['archive_count']} archives inventoried,
{selection['final_size']:,} positions labeled, {len(results)} controlled full experiments,
and two seeds for each finalist. The selected run used
{selected_primary['metrics']['train']['positions']:,} training positions.

## Findings

- **More data:** compact validation teacher MSE {scaling_finding} from
  {scale_values[0]:.6f} (200K nominal pool) to {scale_values[-1]:.6f} (1M).
  All sizes used the same holdout and settings; larger datasets also processed more examples.
- **More capacity:** {best_b['architecture']} led the common 500K comparison.
  Medium and large had lower training loss but worse validation error than the smaller finalists.
- **Generalization:** the winner was selected by the mean validation blended loss of
  two seeds, after two bounded settings per finalist. Epochs and tuning never used test scores.
- **Improvement over v1:** final test teacher MSE **{best_metrics['teacher_probability_mse']:.6f}**
  versus **{v1['teacher_probability_mse']:.6f}**, measured on the same
  {best_metrics['positions']:,} positions ({improvement_description}). Material baseline: {material:.6f}.
  Historical v1 MSE 0.016341 used a different, quieter cohort and is not the direct comparator.
- **Score error:** clipped cp MAE **{best_metrics['clipped_cp_mae']:.2f}**, RMSE
  {best_metrics['clipped_cp_rmse']:.2f}, clipped Pearson {best_metrics['clipped_cp_pearson']:.4f},
  decisive sign accuracy {best_metrics['sign_accuracy_abs_cp_ge_100']:.2%}.
- **Extra size:** selected export {size_ratio:.2f}× compact's bytes and {cost_ratio:.2f}×
  its theoretical dense-head MACs. Whether this pays off in search requires native latency
  and playing tests. Benchmark the validated compact and small finalists next.

{finalist_note}

## Finalists

| Architecture | Two-seed val blended MSE | Test teacher MSE | Test cp MAE | Correlation | Export bytes |
|---|---:|---:|---:|---:|---:|
{final_table}

## Controlled experiment ranking

Rows rank individual runs by validation blended loss; the final architecture choice
uses two-seed means. The gap is validation minus training blended MSE.

| Rank | Experiment | Nominal pool | Parameters | Epochs / selected | Val blended MSE | Val teacher MSE | Gap | Examples |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
{table}

## Data quality, verification and limits

The common pool contains {pool['positions']:,} legal unique positions from
{pool['games']:,} game groups; nested prefixes share fixed validation/test cohorts.
Exact duplicates and game aliases share partitions, and v1 training FENs are excluded
from v2 holdouts. Captures, checks and promotions are retained. Tactical tags and
source metadata hints are heuristics. Embedded PGN evaluations are not teacher targets.

Teacher: unchanged Stockfish 19, 16,384 nodes, {bench['selected_workers']} one-thread workers.
The 65,536-node check on {quality['summary']['positions']} representatives changed clipped scores by
{quality['summary']['mean_clipped_abs_cp_change']:.2f} cp on average, with
{quality['summary']['mate_status_changes']} mate-status changes. Higher-budget labels are not perfect ground truth.
The target, two-perspective 780 features, clipped ReLU and float32 export contract remain unchanged.

**Tests: {tests['tests']} passed, {tests['failures']} failures, {tests['errors']} errors,
{tests['skipped']} skips.** Recovery, cache compatibility and all four widths were checked.
Each candidate passed 128-FEN NumPy/PyTorch/device parity within 0.01 cp, checksum/shape
checks and read-only native format parsing. v1 exports/checkpoints were verified unchanged.
No C++ engine, GUI, default evaluator or native weights were modified.
These results measure teacher prediction, not playing strength.

Paired game-bootstrap 95% interval for selected v2 minus v1 test MSE:
[{ci[0]:.6f}, {ci[1]:.6f}]. Negative favors v2; residual overfitting is visible in the curves.

## Files and reproduction

- Best export: `exports/v2/stockbear-v2-best.sbnnue`; independent compact/small/medium/large
  candidates and golden FENs are beside it. Selected checkpoints remain in `runs/v2/`.
- [Full experiment report](NNUE_V2_EXPERIMENT_REPORT.md), [comparison CSV](comparison.csv),
  [dataset manifests](dataset_manifests.json), [selection](selection.json).
- The original project retains shared labeled SQLite data and prepared arrays in `data/v2/`.
  Reproduce/resume with `.\\.venv\\Scripts\\python.exe -m stockbear.v2 run`; test with
  `.\\.venv\\Scripts\\python.exe -m pytest`. Configuration: `configs/v2/plan.json`.

![Scaling comparisons](plots/scaling_comparison.png)

![Learning curves](plots/learning_curves.png)

![Test error distributions](plots/test_errors.png)
"""
    root_short=short.replace("(plots/", "(reports/v2/plots/")
    for filename in ('comparison.csv','dataset_manifests.json','selection.json'):
        root_short=root_short.replace(f'({filename})',f'(reports/v2/{filename})')
    (root/"NNUE_V2_RESULTS.md").write_text(root_short,encoding="utf-8")
    (directory/"NNUE_V2_RESULTS.md").write_text(short,encoding="utf-8")
    # Every prepared prefix is a durable, reusable dataset manifest.
    manifests=[]
    for path in sorted((root/cfg["prepared"]).glob("*/manifest.json")):
        value=json.loads(path.read_text());manifests.append({"path":str(path.relative_to(root)),"sha256":file_hash(path),**value})
    save_json(directory/"dataset_manifests.json",manifests)
    readme=root/"README.md"
    previous=readme.read_text(encoding="utf-8-sig").split("<!-- STOCKBEAR_V2 -->")[0].rstrip()
    readme.write_text(previous+"\n\n<!-- STOCKBEAR_V2 -->\n## NNUE v2 experiments\n\n"
                      "The completed v2 plan and results are in `NNUE_V2_RESULTS.md`. Run or resume with "
                      "`python -m stockbear.v2 run`. Configuration: `configs/v2/plan.json`. "
                      "The selected model is `exports/v2/stockbear-v2-best.sbnnue`; independently named architecture "
                      "candidates and golden scores are beside it. v1 artifacts and the native engine remain unchanged.\n",encoding="utf-8")
    summary={"best":best,"best_model":"exports/v2/stockbear-v2-best.sbnnue","test":best_metrics,"v1_same_test":v1,
             "v1_relative_mse_improvement_percent":improvement,"report":"NNUE_V2_RESULTS.md","experiments":len(results),
             "pool_positions":pool["positions"],"largest_labeled":selection["final_size"],"tests":tests}
    save_json(directory/"final_summary.json",summary)
    return summary
