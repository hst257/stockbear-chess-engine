# Compact v2 whole-search throughput study

Baseline revision: `a2fb045`. Earlier diagnosis, model/training files, and all
earlier measurements are preserved. No files are deleted by this study.

The model is Compact v2 32/16 float32. Its SHA256 must remain
`788b865a15dbdeeb3e03b7493f8155fd19d6c73b9b0873453ad16fba51a65aa7`.
Classical remains the default. No search policy, ordering, table, time-management,
feature, activation, score or training changes are allowed.

## Measurement order

1. Preserve source, rebuild untouched engine/microbenchmark, verify executable
   code-section equality with the previous release, and run existing regressions.
2. Profile the frozen 24-FEN suite at 100k/400k/1M nodes, two rotated trials,
   using release, counters and intrusive exclusive clocks. Rank costs before edits.
3. Test each NNUE-only candidate independently against the preserved baseline.
   Require exact deterministic trees before considering timing. Retain legacy
   paths for A/B builds. No fast-math, quantization, SIMD or weight changes.
4. Final comparisons: five serial, alternating/rotated trials on 24 FENs at
   100k/400k/1M nodes and 50/200/1000ms. Hash16, one thread, fresh search tables.
   Exclude short mate fixtures/early node termination and sub-10ms observations
   from aggregate throughput, while preserving every raw record.
5. Re-run full regressions, native model and transition oracles, cancellation,
   classical deterministic parity and available sanitizers before deployment.
6. Exactly 60 games at **500ms/move**, first 30 pairs of the earlier frozen
   evaluator-neutral opening book, reversed colors. Optimized NNUE vs frozen
   baseline NNUE is the primary validation. The first pair is the smoke test and
   remains in the 60-game total. No automatic expansion or extra tournaments.
   Claimable draws; 240 searched-ply cap; capped games remain unfinished.
   Pair-resampled uncertainty; no definitive Elo claim from a small match.

Release wall time and engine-reported time are distinct. Counter-only and scope
clock runs are separate; their timing overhead is measured, not attributed to
production cost. Windows WPR CPU sampling was attempted, but the OS refused to
enable the profiling policy (`0xc5585011`). Hardware cache/branch counters are
unavailable; source-level traffic estimates are not DRAM measurements. Differential
release experiments and exact work counters are the primary alternative.

## Reproduction

Use the existing `.venv` and pinned Zig 0.13. Builds and native executables may
require the desktop environment's approved execution context. Only one CPU-heavy
experiment runs at a time. Generated executables, build sidecars, logs and baseline
source snapshots live in `artifacts/nnue-v2-throughput/`; frozen raw JSON/CSV,
protocols and final verification live here. Python commands use repository modules:

```powershell
.\.venv\Scripts\python.exe -m tools.nnue_throughput baseline
.\.venv\Scripts\python.exe -m tools.nnue_throughput compare --label <build> --repeats 5 --budgets 100000 400000 1000000
.\.venv\Scripts\python.exe -m tools.nnue_throughput compare --label <build> --repeats 5 --budgets 50 200 1000 --time
.\.venv\Scripts\python.exe -m tools.analyze_nnue_throughput docs/nnue-v2-throughput/benchmark-<build>.json
.\.venv\Scripts\python.exe -m tools.run_nnue_throughput_final --strategy compact --matches
StockBear_NNUE_training\.venv\Scripts\python.exe -m tools.report_nnue_throughput --plots
```

Completed baseline stages are retained. Comparisons checkpoint complete searches;
resume with the same label, model, executable and parameters. Build labels are
immutable: use a fresh label for each changed candidate.

The baseline command was executed **before** optimization, at the frozen tag.
For a cold reproduction, build the original source from that tag in a separate
checkout first; preserve both its executable and micro target under `baseline/`.
Rebuilding current source with `--nnue-update legacy` restores update behavior,
but is not a claim of byte-identical original machine code. Existing baseline
labels are never overwritten. The serial final pipeline skips completed stages;
its status/logs live under the artifact root. Do not run it concurrently with
another engine benchmark. The match checkpoint is retained after completion.

`--nnue-update compact` is the accepted build default. `legacy`, `merge`,
`deferred`, `fused` and `compact-small` remain explicit A/B experiment options.
The ordinary UCI evaluator default remains classical. Launch the measured v2
build explicitly when checking the desktop application:

```powershell
.\.venv\Scripts\python.exe -m app.main --mode engine --evaluator nnue --engine artifacts/nnue-v2-throughput/final/engine.exe
```
