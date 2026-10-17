# Stage 3 — dense float32 head investigation

Accepted baseline: Stage 1 `f397a5af002900bbc15a7261dc6027c48daaeff4`,
`NNUEKernel=clip`, compact strategy 2. No Stage 2/2.1 sorting changes are imported.
The original baseline engine, head and selected 64/32 model remain unchanged.

Before choosing implementations, run fresh baseline searches/head timings,
sample native instruction pointers, and inspect linked/pre-link machine code.
Select at most two independent, narrow, evidence-directed head changes. Preserve
every per-neuron and output addition sequence, Stage 1 input clipping and all
special-value behavior. Require strict bitwise/transition/fixed-work/restoration
gates before micro/full-search benchmarks. Never weaken parity to accept a gain.

Initial plan: seven rotated pairs per candidate, frozen 12 positions, 200k/1M
nodes and 100/500/1000 ms. Maximum ten passes only with a documented predeclared
uncertainty justification, maximum 45 minutes primary execution per candidate.
No automatic extensions or variants beyond two. Head microbenchmarks use
1/32/128/512 frames, 200k iterations, 10k warmups and matching checksums.

One search thread, 16 MiB hash, CPU0, fresh TT, strict `-ffp-contract=off` and the
same compiler/ISA as Stage 1. AC and last-confirmed Quiet/Eco; no power/app changes.
Run CPU-intensive work serially. No training, sealed data, tournaments, new
weights, quantization, lazy updates, search changes, or active-engine promotion.
Keep one final commit unless there is a concrete risk requiring a checkpoint.

EXE/PDB, complete source/header/assembly copies and compiler caches stay on Z:
under ignored `artifacts/`. Capstone 5.0.3 in the existing project environment
enables linked x64 disassembly; MinGW objdump cannot read this PE.

## Reproduce in a new directory

Use the existing Windows Python 3.11 / python-chess / Zig 0.13 environment.
Original Stage 1/Stage 2/Stage 2.1 local artifacts and selected model must remain
present. Preparation hashes them and refuses missing/mismatched inputs; it does
not regenerate weights. Do not rerun preparation in this frozen directory.

```powershell
.\.venv\Scripts\python.exe -m pip install capstone==5.0.3
$trialDir = 'nnue-stage3-repeat'
New-Item -ItemType Directory $trialDir
Copy-Item nnue-optimization-stage3-20261017\*.py,nnue-optimization-stage3-20261017\*.cpp,nnue-optimization-stage3-20261017\*.ps1 $trialDir
Copy-Item nnue-optimization-stage3-20261017\positions.json,nnue-optimization-stage3-20261017\golden-fens.txt $trialDir
.\.venv\Scripts\python.exe "$trialDir/bootstrap.py"
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" prepare
if ($LASTEXITCODE) { throw 'Preparation failed' }
& "$trialDir/observe.ps1" -Output "$trialDir/environment-before.json"
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" build baseline
if ($LASTEXITCODE) { throw 'Baseline build failed' }
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" initial
if ($LASTEXITCODE) { throw 'Baseline verification failed' }
.\.venv\Scripts\python.exe -u "$trialDir/profile_head.py"
if ($LASTEXITCODE) { throw 'Sampling failed' }
.\.venv\Scripts\python.exe "$trialDir/inspect_head.py" baseline
.\.venv\Scripts\python.exe "$trialDir/profile_analysis.py"
```

For exact reproduction of the frozen two variants, copy the selection receipt
after profiling, then create the headers and run the serial gated schedule:

```powershell
Copy-Item nnue-optimization-stage3-20261017\candidate-selection.json $trialDir
.\.venv\Scripts\python.exe "$trialDir/make_candidates.py"
.\.venv\Scripts\python.exe -u "$trialDir/run_trials.py"
```

`run_trials.py` stops a candidate on any correctness failure; it never relaxes
numeric parity. Completed trials/failed frozen candidates are skipped. Inspect
saved receipts before a resume. To resume only missing primary searches:

```powershell
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" search unroll4
.\.venv\Scripts\python.exe -u "$trialDir/experiment.py" search hiddenclip
```

Only run those search commands after that variant's correctness/regression gates
pass. Completed search keys are skipped. Never replay completed measurements or
repeat a failed numerical candidate as if it were another independent sample.
An extension requires a written reason in `extension-<label>.json`, at most ten
passes, and satisfaction of the predeclared rule in `plan.json`.

After both bounded trials, use saved results to complete the audit:

```powershell
& "$trialDir/observe.ps1" -Output "$trialDir/environment-after.json"
foreach ($build in @('baseline', 'unroll4', 'hiddenclip')) {
    .\.venv\Scripts\python.exe "$trialDir/inspect_head.py" $build
}
.\.venv\Scripts\python.exe "$trialDir/kernel_shape.py"
.\.venv\Scripts\python.exe "$trialDir/analyze.py"
.\.venv\Scripts\python.exe "$trialDir/regression_diagnosis.py"
.\.venv\Scripts\python.exe -u "$trialDir/classical_context.py"
.\.venv\Scripts\python.exe "$trialDir/experiment.py" preserve
.\.venv\Scripts\python.exe "$trialDir/report.py"
.\.venv\Scripts\python.exe "$trialDir/finalize.py"
```

The optional classical comparison runs only after an acceptance gate passes;
otherwise it writes a skip receipt without searching. Existing study analysis,
report and manifest can be regenerated without benchmarks using `analyze.py`,
`report.py` and `finalize.py`. Raw JSON/CSV, linked disassembly and test receipts
are committed; complete EXE/PDB/source/generated-weight/full-assembly copies and
caches stay under ignored `artifacts/`. No full GUI/desktop run is claimed.

## Completed result

**Inconclusive; retain Stage 1 as the accepted experimental baseline.**
Both variants pass every numerical, transition, fixed-work and restoration gate.
Seven primary passes per variant completed: 1,680 searches, no extension or
additional diagnostic searches. All 829 protected files are unchanged.

| Independent variant | 1M-node factor | 1000-ms factor | Decision |
|---|---|---|---|
| Four-way unrolling | 0.9834× [0.9651, 1.0147] | 0.9965× [0.9607, 1.0178] | Inconclusive; no established whole-search gain |
| Hidden vector clipping | 1.0642× [1.0399, 1.0848] | 1.0768× [1.0512, 1.1019] | Promising, but inconclusive |

Hidden clipping has positive grouped intervals at all five controls, yet the
100-ms piece-endgame median is 0.9300× (7.53% elapsed regression). Its repeat-only
interval crosses one; a read-only audit finds neither a proven kernel defect nor
a specific causal explanation. No pair was dropped and the gate was not waived.
The extension rule excludes material fixture/order failures, so neither trial
continued beyond seven passes. Optional classical context was skipped because
no candidate passed every primary gate. No active executable/default was changed.

The complete `NNUE_STAGE3_OPTIMIZATION_REPORT.md` includes native sampling,
linked-code analysis, all per-position results, uncertainty and the anomaly audit.
The study is complete; no further benchmarks or optimization stages are scheduled.
