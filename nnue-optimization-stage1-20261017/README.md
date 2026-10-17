# Float32 NNUE head experiment — Stage 1

Implement and test one optional branchless-input-clipping head for the frozen
64/32 model. Production source, active executables, weights, accumulators,
search heuristics and classical defaults stay unchanged. Experimental sources
and binaries live here; the original scalar kernel remains selectable.

Correctness gates precede timing: input special values, bitwise head outputs,
golden FENs, deterministic legal/special/null transitions and restoration,
fixed-depth/node exact search parity. Floating additions and output reduction
retain their original order; `-ffp-contract=off`, no fast-math or reassociation.

Benchmark budget: seven rotated paired micro repetitions for 1/32/128/512
frames and representative fixed FENs; seven rotated paired search repetitions
on the frozen 12-position suite at 200k and 1M nodes and 100/500/1000 ms.
At most ten paired repeats if necessary to resolve noise, with no automatic
unbounded extension. Stop after at most three narrowly scoped head variants.
No tournaments, training, test-dataset access or automatic engine promotion.

Maintain the last confirmed Quiet/Eco profile and AC power; do not change power
settings. Record load/power conditions and flag unavailable thermal telemetry.
Position-grouped paired intervals must exclude no gain before acceptance.

Raw results, source patches, scripts and reports are committed. Local binaries,
source/build snapshots, generated headers, PDB and assembly are retained under
the repository-ignored `artifacts/` directory, with a reproducible manifest.

## Implementation and fallback

`stage1_head.hpp` is the only new mathematical implementation. `variant.patch`
shows two changes applied exclusively to `artifacts/variant-source`: an optional
`clip` kernel/guard in `nnue.cpp`, and its UCI option advertisement in `main.cpp`.
All other source copies match production. `auto` and `scalar` retain the
original head. Classical remains the UCI default even in experimental binaries.

The optimized route requires `nnue_simd_available()` and uses reversed min/max
operand order to preserve NaNs and negative zero. `NNUEKernel=scalar` selects
the original implementation. Starting a new process with
`CHESSLAB_DISABLE_SIMD=1` also makes `clip` fall back to it. This is a guard for
the new kernel; existing host-target binaries are not newly promised portable
to older CPUs.

Manual UCI inspection of the isolated executable:

```powershell
.\nnue-optimization-stage1-20261017\artifacts\variant\engine.exe
# Enter these lines in its terminal:
# uci
# setoption name Evaluator value nnue
# setoption name NNUEKernel value clip
# isready
# position startpos
# go nodes 1000000
# quit
```

Do not copy this binary into `engine/build`, change launch settings or select
it as the active evaluator without the user's separate promotion approval.

## Results

The root `NNUE_STAGE1_OPTIMIZATION_REPORT.md` is mirrored here. Raw records:

- `correctness.json`, `regressions.json`, `pytest.log`: numerical/search/golden gates.
- `micro.json`: seven paired passes, 1/32/128/512 frames and 12 fixed FENs.
- `search.json`: 840 warm searches, full decisions/counters/PVs and 84 load segments.
- `analysis.json`, `search-per-position.csv`: position-grouped paired comparisons.
- `assembly-audit.json`, `*-head-assembly.txt`: generated code and local PDB sizes.
- `native-samples.json`, `native-symbols.json`: bounded post-change RIP trace.
- `preservation-*.json`, `validation.json`, `manifest.json`: unchanged-file and artifact receipts.

The 128 old-model golden scores run against a compatibility build with the
already existing 32/16 headers. Their expected CP values are not incorrectly
applied to the 64/32 network. Both original and optimized 64/32 heads use the
256 existing golden FENs as additional bit-parity inputs. No sealed test data
or training data is used. The post-change sampler runs 24 bounded 1.5-second
searches, reusing the established own-child sampling method.

## Reproduction

Run from `Z:\Code\Chess`, with existing `.venv`, `python-chess`, pytest,
Zig 0.13.0 and the original local profiling/model artifacts. No new dependency
or model export is required. The experiment is frozen; reproduce in a new
directory directly under the repository rather than overwriting these results:

```powershell
New-Item -ItemType Directory nnue-stage1-repeat
Copy-Item nnue-optimization-stage1-20261017\*.py,nnue-optimization-stage1-20261017\*.cpp,nnue-optimization-stage1-20261017\*.hpp,nnue-optimization-stage1-20261017\*.ps1 nnue-stage1-repeat\
.\.venv\Scripts\python.exe -u nnue-stage1-repeat\experiment.py prepare
.\.venv\Scripts\python.exe -u nnue-stage1-repeat\experiment.py build
.\.venv\Scripts\python.exe -u nnue-stage1-repeat\experiment.py correctness
.\.venv\Scripts\python.exe -u nnue-stage1-repeat\regressions.py
.\.venv\Scripts\python.exe nnue-stage1-repeat\assembly_audit.py
.\nnue-stage1-repeat\observe.ps1 -Output nnue-stage1-repeat/environment-before.json
.\.venv\Scripts\python.exe -u nnue-stage1-repeat\experiment.py micro
.\.venv\Scripts\python.exe -u nnue-stage1-repeat\experiment.py search
.\.venv\Scripts\python.exe -u nnue-stage1-repeat\profile_remaining.py
.\nnue-stage1-repeat\observe.ps1 -Output nnue-stage1-repeat/environment-after.json
.\.venv\Scripts\python.exe nnue-stage1-repeat\analyze.py
.\.venv\Scripts\python.exe nnue-stage1-repeat\experiment.py preserve
```

Keep the existing power profile, AC connection, options and CPU affinity
unchanged. Run commands serially. `prepare` refuses an existing frozen plan;
`search` checkpoints completed pairs and can resume without replaying them.
The initial native toolchain cache can make the first build take several
minutes. The complete performance schedule is bounded; do not add games or
automatically expand repetitions.

The analysis uses 10,000 hierarchical bootstrap draws: sample positions as
groups, then paired repeats inside each sampled position. It describes this
fixed fixture suite, not Elo, universal workloads or independent new chess
positions. Load samples are system CPU deltas after subtracting the benchmark
processes; they do not measure per-core contention or temperature.

`validate.py` checks this run's completed counts, immutable sources and report
mirror. `manifest.json` inventories local artifacts; use LF-normalized hashes
for text after Git line-ending conversion. Ignored binaries, PDB, full assembly
and source snapshots remain on this project drive; committed scripts, focused
patches and raw JSON/CSV permit reproduction.
