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
