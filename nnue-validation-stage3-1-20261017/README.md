# Stage 3.1 exact-binary validation

This workspace validates existing Stage 1 / Stage 3 `hiddenclip` executables.
It does not compile, optimize, train, label, play games or change the active engine.
Keep the original Stage 3 `artifacts/` directory: binaries/PDB/generated weights
are ignored research artifacts and cannot be recreated silently for this study.
Byte-identical local archival EXE/PDB copies are also retained under this
workspace's ignored `artifacts/exact-binaries/`; `archived-binaries.json` records
their hashes and measured original paths. The runner always verifies the original
paths and never silently substitutes an archive or rebuild.

From `Z:\Code\Chess`, PowerShell:

```powershell
# Read-only identity / immutable-plan / protected-file checks:
.\.venv\Scripts\python.exe .\nnue-validation-stage3-1-20261017\validate.py integrity

# Resume only if the frozen schedule was interrupted; completed pairs are skipped:
.\.venv\Scripts\python.exe -u .\nnue-validation-stage3-1-20261017\validate.py run

# No engines are launched by analysis or reporting:
.\.venv\Scripts\python.exe .\nnue-validation-stage3-1-20261017\analyze.py
.\.venv\Scripts\python.exe .\nnue-validation-stage3-1-20261017\cpu_diagnostics.py
.\.venv\Scripts\python.exe .\nnue-validation-stage3-1-20261017\report.py
.\.venv\Scripts\python.exe .\nnue-validation-stage3-1-20261017\finalize.py
```

`freeze` is for a new empty study only. Never rerun it over a frozen plan.
No additional measurements are scheduled by the analysis/report commands.
The optional `telemetry.ps1` records CPU0 Windows counter snapshots and stops at
schedule completion; it neither adjusts the engine nor supplies calibrated MHz.

`validation-plan.json` fixes all positions, controls, repetitions, thresholds,
seed, primary estimator, bootstrap and interruption policies before timings.
`schedule.json` has exact pair orders. `pairs.jsonl` is the fsynced pair checkpoint;
`blocks.jsonl` contains pre/post AC, power-plan and load checks. `events.jsonl`
retains pauses/resumes; `setup-audit.json` discloses pre-measurement harness fixes.
Incomplete final JSONL lines after a hard machine failure require forensic audit
before resuming; do not silently truncate evidence. A mid-block power interruption
requires audit, not automatic exclusion of slower individual results.

All primary pairs, including background-flagged blocks, enter the primary result.
Stable-block analysis is a symmetric sensitivity check. General, independent
endgame and sentinel estimates stay separate. Original Stage 3 data is historical
only. Repetition intervals for the sentinel are not across-position intervals.

The report, CSV/JSON, hashes and protected-file receipts are the completed study.
Acceptance, if supported, concerns an experimental baseline only. Production
deployment requires separate approval. No Elo inference is made.
