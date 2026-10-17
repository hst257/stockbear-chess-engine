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
