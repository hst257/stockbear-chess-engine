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
