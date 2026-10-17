# Stage 2 — accumulator maintenance experiment

Build directly on Stage 1 commit `f397a5af002900bbc15a7261dc6027c48daaeff4`.
Both control and candidates use `NNUEKernel=clip`, one thread, 16 MiB hash,
CPU 0 and identical strict float compiler flags. Production, weights, search,
datasets and previous experiments remain protected and unchanged.

Before candidate implementation, reconfirm Stage 1 parity, save preservation
hashes, and measure maintenance using an isolated counter/timer build. Audit
compact2, small-state5 and fused-row4 before selecting at most three narrow,
independently tested candidates. No lazy updates or combined unverified changes.

Correctness gates: bitwise accumulator/head parity, the existing legal/null
transition oracle, special transitions and restoration, and exact depth/200k/1M
search decisions/counters. Then seven rotated paired repetitions on the frozen
12-position suite at 200k/1M nodes and 100/500/1000 ms, with at most ten if needed
to resolve noise. Microbenchmarks exercise diverse actual move/update paths.

Keep AC power and the last user-confirmed Quiet/Eco setting. Record background
load; run CPU work serially. Report instrumentation overhead and position-grouped
uncertainty. Accept only reproducible whole-search gains with exact parity and
no unexplained material regression. Stop early on a clear winner; preserve Stage
1 if no candidate meets the gates. An accepted candidate remains isolated.

Scripts, focused patches, raw measurements and the report are committed. Binaries,
PDB, generated headers, assembly and source snapshots remain under the local
ignored `artifacts/` directory on this project drive. No tournaments, training,
test-set access, active-engine promotion or Stage 3 work is authorized here.

## Source and test contracts

`experiment.py prepare` copies the exact Stage 1 clip executable/source and
existing 64/32 generated headers, saves 800 protected-file hashes, and reruns
the original transition/head gates. It never regenerates weights.

Independent labels: `sort` (strategy 2 plus `small_sort.hpp`), `fused` (existing
strategy 4), and `small` (existing strategy 5). Each starts from Stage 1 source.
No combined implementation or strategy 3 is selected. Empty source patches for
reused prototypes are intentional: their change is the recorded build option.

`update_harness.cpp` checks legal branches, root/child isolation, special/null
moves, poisoned child values and 17,000 tiny-sort order cases. Its lane/head
digest is compared with Stage 1. Microbenchmarks use 8,264 varied edges across
ten categories. Their mixed category is null-heavy, not search-frequency weighted.

## Reproduction

Use the existing Windows `.venv` with Python 3.11, python-chess and Zig 0.13.0.
This archival experiment requires preserved local Stage 1/profiling artifacts,
model/export and protected research files. It refuses missing/mismatched files;
binaries/models are not all in Git. Use a **new directory**:

```powershell
$trialDir = 'nnue-stage2-repeat'
New-Item -ItemType Directory $trialDir
Copy-Item nnue-optimization-stage2-20261017\*.py,nnue-optimization-stage2-20261017\*.cpp,nnue-optimization-stage2-20261017\*.hpp,nnue-optimization-stage2-20261017\*.ps1 $trialDir
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" prepare
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" build baseline
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" build counters
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" build timers
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" instrumented
.\.venv\Scripts\python.exe "$trialDir/profile_analysis.py"
foreach ($candidate in @('sort', 'fused', 'small')) {
    .\.venv\Scripts\python.exe -u "$trialDir/experiment.py" build $candidate
    if ($LASTEXITCODE) { throw 'Build failed' }
    .\.venv\Scripts\python.exe -u "$trialDir/experiment.py" correctness $candidate
    if ($LASTEXITCODE) { throw 'Parity failed' }
    .\.venv\Scripts\python.exe -u "$trialDir/regressions.py" $candidate
    if ($LASTEXITCODE) { throw 'Regression failed' }
    .\.venv\Scripts\python.exe -u "$trialDir/experiment.py" micro $candidate
    .\.venv\Scripts\python.exe -u "$trialDir/experiment.py" search $candidate
    .\.venv\Scripts\python.exe "$trialDir/assembly_audit.py" $candidate
    .\.venv\Scripts\python.exe "$trialDir/analyze.py" $candidate
}
```

Run serially with AC and the same profile; do not change power settings.
Rerunning `search` resumes by skipping completed record keys. The original sort
trial reached ten passes after inconclusive seven-pass results;
`extension-sort.json` records the decision. The initial plan stays frozen.
Reproduce ten passes only with a new extension receipt in your new directory
containing `total_repeats: 10`. Never exceed the ten-pass ceiling or overwrite
these measurements. Capture conditions and recheck protected files:

```powershell
& "$trialDir/observe.ps1" -Output "$trialDir/environment.json"
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" preserve
```

Analysis uses paired wall NPS and position-grouped uncertainty. Detailed timers
perturb search heavily; their totals are diagnostic clues. The root report,
raw JSON/CSV, build receipts, patches and assembly retain the actual decisions.

## Completed outcome

All three independent trials are complete: 2,880 primary searches, plus 108
separate descriptive classical-context searches. No Stage 2 candidate is accepted.
Retain Stage 1 as the experimental baseline; the production engine and classical
default remain unchanged.

| Trial | Decision | Evidence |
|---|---|---|
| Tiny-list sorting | Inconclusive | About 2.7–3.2% aggregate gain, but 3.1% elapsed regression on promotion at 1M nodes |
| Ordered row fusion | Rejected | Whole-search slowdown, including longer timed controls |
| Smaller temporary state | Rejected | Whole-search slowdown despite mixed microbenchmark benefits |

All bitwise and fixed-work gates pass. The separate internal-restoration observer
and 147 selected legacy compatibility tests pass. All 800 protected files retain
their original hashes. See `NNUE_STAGE2_OPTIMIZATION_REPORT.md` for grouped
uncertainty, complete per-position results and limitations.

To regenerate the report and audit from the saved results **without running
search benchmarks**, use the original workspace and preserved local artifacts:

```powershell
.\.venv\Scripts\python.exe nnue-optimization-stage2-20261017/report.py sort
.\.venv\Scripts\python.exe nnue-optimization-stage2-20261017/validate.py sort
```

Validation checks binary/source hashes, exact fixed-work pairs, unique record
keys, final microbenchmark provenance, restoration and legacy receipts, protected
files, and mirrored reports. It writes `validation.json` and `manifest.json`.
No remaining games, benchmarks, training or follow-up optimization are scheduled.
