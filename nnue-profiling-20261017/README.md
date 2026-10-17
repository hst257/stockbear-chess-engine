# NNUE 64/32 profiling investigation

Profiling only: no kernel optimization, architecture or weight changes, search
changes, training, tournaments, or sealed-test access. Original source files,
models, active executables, and prior experiments remain unchanged. All new
builds and instrumentation live under this directory.

The user confirmed **NitroSense Quiet/Eco**. AC power was detected. Keep these
settings unchanged; results apply to this condition, not a Balanced-mode claim.
Windows currently reports the OEM **Acer** power plan. No power or antivirus
settings will be changed.

The frozen target is the expanded-data selected **64/32** export and checkpoint.
Classical is a same-binary evaluator control. Measurements compare identical
positions, histories, production search settings, one logical P-core affinity,
16 MiB hash, scalar float32, and exact fixed-node/depth limits where applicable.
Cold process starts and warmed searches are reported separately.

Release timings are authoritative. Counter/timer builds require fixed-work
decision parity and explicit observer-overhead measurements. Logical byte/work
counters are not hardware cache misses. Native sampling is bounded and limited
to isolated benchmark processes. Existing quantized code may be inspected;
no model is newly quantized and no integer kernel is implemented.

Raw JSON/CSV, source snapshots, build logs, traces, and reproduction scripts
are retained here. The root reports will be `NNUE_PROFILING_REPORT.md` and
`NNUE_OPTIMIZATION_ROADMAP.md`. This phase ends with a proposed first step,
which requires the user's explicit approval before implementation.

## Results and evidence

- [Profiling report](../NNUE_PROFILING_REPORT.md) and [implementation proposal](../NNUE_OPTIMIZATION_ROADMAP.md).
- `baseline.json`: 360 warm / 24 cold searches, iterations, actual counters and legal PVs.
- `instrumented.json`: 108 fixed-work searches; release/counters/clocks decision parity.
- `micro.json`, `components.json`, `varying-head.json`: seven-pass batched timings.
- `native-samples.json`, `native-symbols.json`: own-child RIP trace and local-PDB attribution.
- `binary-inspection.json`: exact preserved-release head/delta function byte checks.
- `summary.json`, `baseline-per-position.csv`, `component-clock-times.csv`,
  `batched-component-times.csv`: derived tables. The latter records timed call
  counts/totals; warmup and parity checks are outside those timed batches.
- `classical-timers.json`: biased clock control; not a production time share.
- `environment-*.json`, `cpu-*.json`, `build-*.json`: recorded conditions/configurations.
- `validation.json`, `preservation-*.json`, `manifest.json`: integrity assertions and inventory.

`components-initial-harness.json` retains the discarded caller-visible-buffer
microbenchmark. Its dense numbers are not used in final summaries. See the report.
WPR failed with Windows policy error `0xc5585011`; failure/status logs are retained.
No ETL was produced. The native trace is the bounded custom RIP sample instead.

The original profile is frozen. Do not overwrite it for a new experiment.
The `artifacts/` directory is ignored by the repository's existing rules and is
retained locally, including binaries, PDB, copied source, generated headers,
assembly and compiler logs. Raw JSON/CSV, scripts, metadata and reports are committed.

## Recompute summaries without running engines

From `Z:\Code\Chess` in PowerShell:

```powershell
.\.venv\Scripts\python.exe nnue-profiling-20261017\analyze.py
.\.venv\Scripts\python.exe nnue-profiling-20261017\validate_results.py
```

These read existing results, update derived tables/inventory and check protected
files. The second command also resolves no new positions and starts no engines.
Local byte hashes can differ after Git line-ending conversion; use manifest
LF-normalized hashes for text. Protected binary/model hashes are exact bytes.

## Reproduce bounded measurements in a fresh workspace

Prerequisites: the existing project virtual environment, `python-chess`, installed
`ziglang==0.13.0`, original local model/tournament artifacts and unchanged engine
source. No large profiler install is necessary. Do not reuse this plan after a
source/model change without freezing a new baseline and protection inventory.

```powershell
Set-Location Z:\Code\Chess
New-Item -ItemType Directory -Path nnue-profiling-repeat
Copy-Item nnue-profiling-20261017\*.py,nnue-profiling-20261017\components.cpp nnue-profiling-repeat\
.\.venv\Scripts\python.exe -u nnue-profiling-repeat\run_profile.py prepare
.\.venv\Scripts\python.exe -u nnue-profiling-repeat\run_profile.py baseline
.\.venv\Scripts\python.exe -u nnue-profiling-repeat\run_profile.py instrumented
.\.venv\Scripts\python.exe -u nnue-profiling-repeat\run_profile.py micro
.\.venv\Scripts\python.exe -u nnue-profiling-repeat\prepare_native.py
.\.venv\Scripts\python.exe -u nnue-profiling-repeat\run_components.py
.\.venv\Scripts\python.exe -u nnue-profiling-repeat\sample_native.py
.\.venv\Scripts\python.exe -u nnue-profiling-repeat\inspect_binary.py
.\.venv\Scripts\python.exe -u nnue-profiling-repeat\additional_checks.py
.\.venv\Scripts\python.exe nnue-profiling-repeat\analyze.py
```

Run these serially; keep the same user-selected profile and AC power. Expect a
bounded several-minute suite, no games or training. Fresh-directory `prepare`
refuses to overwrite an existing frozen configuration. Baseline/instrumented
searches checkpoint between positions; no background monitor is installed.
The result validator intentionally contains this completed run's exact counts;
review those before applying it to another experiment. Native samples vary, so
do not expect the repeated sampler to produce exactly 4,074 instruction pointers.

The sampler only suspends the active thread of its own engine process, resumes
it immediately, and records exclusive instruction pointers with randomized
2–4-ms spacing. Matching local PDB files are resolved by Windows DbgHelp with
symbol-server downloads disabled. No privileged ETW or hardware-counter access
is required; no cache/branch-miss/cycle claims are made.
