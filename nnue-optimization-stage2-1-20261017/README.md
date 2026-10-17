# Stage 2.1 — targeted tiny-list sorting

This bounded experiment starts from accepted Stage 1 commit
`f397a5af002900bbc15a7261dc6027c48daaeff4`, kernel `clip`, compact strategy 2.
The exact Stage 2 full insertion-sort binary is a separate comparison, never
combined with rejected fusion or state-layout experiments. Active engine,
weights, training data and previous experiments remain unchanged.

First reproduce the promotion result on the original and three other legal
positions, inspect assembly, and observe actual sorting distributions. Freeze
four additional promotion validation positions before selecting at most two
new narrowly scoped sorting variants. Do not tune on validation results.

Require exact sorting (including equal keys), accumulator/head parity, fixed
depth/node decisions/counters, and interrupted-search restoration before timing.
Use seven rotated triples on the frozen 12-position suite plus four validation
positions at 200k/1M nodes and 100/500/1000 ms; maximum ten primary passes only
with a documented reason, maximum 45 minutes of primary search execution.
Preserve raw measurements and grouped uncertainty. Reject unexplained fixture
median elapsed regressions over 3%; approximately 3% gain is a target, not a
mandatory gain threshold. Microbenchmarks alone cannot establish acceptance.

Use one search thread, 16 MiB hash, CPU0, fresh TT, strict float arithmetic,
`-ffp-contract=off`, AC and the last user-confirmed Quiet/Eco profile. Never change
power settings or close unrelated apps. Counters are diagnostic observers only.
No tournaments, training, sealed-test access, lazy updates or Stage 3 work.

Per the user's latest instruction, avoid routine checkpoint commits. Keep one
final commit unless proceeding without a checkpoint creates a concrete risk.
Build/source copies and binaries remain under ignored `artifacts/` on Z:.

## Reproduction and resume

Use the existing Windows Python 3.11 environment, python-chess and Zig 0.13.
Original Stage 1/Stage 2 local artifacts and the existing 64/32 model must remain
available. The scripts verify the original binaries and do not regenerate weights.
No preparation command may be rerun in this frozen workspace. To repeat the study,
copy its scripts/headers/fixtures into a **new directory**, then bootstrap:

```powershell
$trialDir = 'nnue-stage2-1-repeat'
New-Item -ItemType Directory $trialDir
Copy-Item nnue-optimization-stage2-1-20261017\*.py,nnue-optimization-stage2-1-20261017\*.hpp,nnue-optimization-stage2-1-20261017\*.cpp,nnue-optimization-stage2-1-20261017\*.ps1 $trialDir
Copy-Item nnue-optimization-stage2-1-20261017\positions.json,nnue-optimization-stage2-1-20261017\golden-fens.txt $trialDir
.\.venv\Scripts\python.exe "$trialDir/bootstrap.py"
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" prepare
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" diagnostic
.\.venv\Scripts\python.exe -u "$trialDir/build_observer.py"
& "$trialDir/observe.ps1" -Output "$trialDir/environment-before.json"
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" observer
.\.venv\Scripts\python.exe "$trialDir/workload.py"
.\.venv\Scripts\python.exe "$trialDir/diagnose.py"
```

To reproduce the **frozen candidate**, copy its selection receipt (do not choose
another threshold based on supplementary results), then build and verify serially:

```powershell
Copy-Item nnue-optimization-stage2-1-20261017\candidate-selection.json $trialDir
foreach ($build in @('baseline', 'sort', 'selective')) {
    .\.venv\Scripts\python.exe -u "$trialDir/experiment.py" build $build
    if ($LASTEXITCODE) { throw 'Build failed' }
}
foreach ($candidate in @('sort', 'selective')) {
    .\.venv\Scripts\python.exe -u "$trialDir/experiment.py" correctness $candidate
    if ($LASTEXITCODE) { throw 'Correctness failed' }
    .\.venv\Scripts\python.exe -u "$trialDir/regressions.py" $candidate
    if ($LASTEXITCODE) { throw 'Search regressions failed' }
    .\.venv\Scripts\python.exe "$trialDir/assembly_audit.py" $candidate
}
.\.venv\Scripts\python.exe -u "$trialDir/restoration_observer.py" selective
if ($LASTEXITCODE) { throw 'Restoration observer build failed' }
.\.venv\Scripts\python.exe -u "$trialDir/regressions.py" restore-selective
if ($LASTEXITCODE) { throw 'Internal restoration failed' }
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" micro
if ($LASTEXITCODE) { throw 'Microbenchmark failed' }
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" primary
```

If interrupted, rerun only `experiment.py primary` in the same directory: completed
search keys are skipped. Never rerun completed microbenchmarks or preparation to
add observations. Full results are saved after each control. A primary extension
requires a reason in `extension.json`, `total_repeats` at most ten, and must remain
inside the 45-minute primary runtime budget. No extension is automatic.

After completion, finish analysis/audit **without new searches**:

```powershell
& "$trialDir/observe.ps1" -Output "$trialDir/environment-after.json"
.\.venv\Scripts\python.exe "$trialDir/analyze.py"
.\.venv\Scripts\python.exe "$trialDir/linked_sizes.py"
.\.venv\Scripts\python.exe "$trialDir/experiment.py" preserve
.\.venv\Scripts\python.exe "$trialDir/report.py"
.\.venv\Scripts\python.exe "$trialDir/finalize.py"
```

All logs/checkpoints remain on the project drive. Raw `primary.json` stores
three-way blocks; `diagnostic.json` and observer results stay separate.
`micro.json`, `workload-raw.jsonl`, build receipts and assembly excerpts preserve
the evidence. Root/workspace reports are mirrored; the manifest records raw and
LF-normalized hashes. Compiler caches and original model files are not pushed.

## Completed result

**Inconclusive; retain Stage 1.** Seven passes / 1,680 primary searches completed
in 17.1 minutes. The original promotion loss did not reliably repeat. Refined
whole-search factors were 1.0115× at 1M nodes (95% grouped interval
0.9942–1.0334) and 1.0286× at 1000 ms (1.0043–1.0513), but fixed-work/order
support was incomplete and pins/200k plus piece-endgame/100ms fixture medians
regressed materially. Supplementary promotion positions had no material median
regression. Full insertion sorting also remains inconclusive.

All strict sorting, accumulator/head, search and internal-restoration gates pass;
813 protected files are unchanged. No extra passes or second candidate were
added after inspecting results. No active engine or default was changed.

The bounded study is complete. To regenerate only its report/integrity audit:

```powershell
.\.venv\Scripts\python.exe nnue-optimization-stage2-1-20261017/report.py
.\.venv\Scripts\python.exe nnue-optimization-stage2-1-20261017/finalize.py
```
