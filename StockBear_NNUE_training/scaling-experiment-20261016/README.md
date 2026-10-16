# Controlled v2 scaling experiment

All generated checkpoints, exports, logs and benchmark binaries live in
`artifacts/` beside these frozen configurations. Existing runs remain untouched.
The baseline configuration references the completed expanded run for reading only.
The legacy `stockbear.expanded_train` entry point is unchanged; the opt-in
`stockbear.scaling_train` extension reuses its model, batch, target and metric
implementations without changing legacy checkpoint signatures.

From `Z:\Code\Chess\StockBear_NNUE_training`:

```powershell
.\.venv\Scripts\python.exe -m stockbear.scaling_train check --config scaling-experiment-20261016/medium.json
.\.venv\Scripts\python.exe -m stockbear.scaling_train train --config scaling-experiment-20261016/medium.json --stop-after 2
.\.venv\Scripts\python.exe -m stockbear.scaling_train train --config scaling-experiment-20261016/medium.json --resume
```

Repeat with `large.json`. Pilots use the first two full epochs and continue from
those checkpoints after health verification; they do not change the schedule.
`--resume` restores optimizer, scheduler and all random states at the last complete
epoch. An interrupted partial epoch is replayed. Resume rejects changed code,
configuration, dataset or runtime. Keep source files unchanged during training.

`best.pt` follows the baseline's strict `MSE < selected_best - 0.00001` rule.
`raw_best.pt` additionally preserves the literal minimum without changing patience
or the primary selection criterion. `last.pt` is resumable; `final.pt` is written
only on completion. All checkpoints include explicit architecture metadata.
Only train/validation arrays are verified or loaded; test arrays are never opened.
