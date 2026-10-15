# Native NNUE v2 experiments

The [final report](../../NNUE_V2_OPTIMIZATION_RESULTS.md) explains conclusions and
limitations. JSON/PGN files here are frozen records, not files to overwrite.
The source baseline is tag `nnue-v2-native-baseline-1b1794e`.
Historical v1 records remain in `docs/nnue/`.

## Build and select

Follow the [model guide](../../engine/networks/v2/README.md) for separate Compact
and Small binaries, GUI startup, UCI kernels and defaults. The original float32
export format is unchanged. The build derives transposed float weights and
optional integer constants; original `.sbnnue` bytes are never rewritten.
Build sidecars record flags, model hashes, source hashes and integer bounds.
Generated headers and binaries are ignored by Git.

## Reproduce measurements

Build the binaries named in a configuration JSON, using the matching model and
`--target nnue-bench` for its microbenchmark executable. Archived configurations
refer to their original source checkpoints; see the final report's commit map.
Always choose fresh result paths. Run CPU measurements serially:

```powershell
.\.venv\Scripts\python.exe -m tools.benchmark_nnue_v2 --config tools/nnue_v2_final.json --output artifacts/new-performance.json
.\.venv\Scripts\python.exe -m tools.benchmark_nnue_white --output artifacts/new-white-evaluation.json
.\.venv\Scripts\python.exe -m tools.validate_nnue_v2 --config tools/nnue_v2_final.json --output artifacts/new-parity.json
.\.venv\Scripts\python.exe -m tools.measure_nnue_memory --config tools/nnue_v2_final.json --output artifacts/new-memory.json
.\.venv\Scripts\python.exe -m pytest -q
```

The full held-out parity tool reads the original training SQLite pool **read
only**: 20,152 grouped test FENs, plus seeded random/edge positions. No training
is performed. Normal builds, microbenchmarks and bundled goldens do not require
that local dataset, NumPy, Torch or a GPU.

The microbenchmark accepts `FEN REPEATS [KERNEL]`, `--batch [KERNEL]`,
`--verify [KERNEL]` and `--cpu`. It measures complete feature extraction,
active-width copy, board-derived update, move-derived update, rebuild and head.
Update microbenchmarks use a prepared legal child; full search includes delta
preparation, make/unmake, synchronization and all search work. Memory is process
memory, not just weight bytes. Raw head throughput is not search NPS.

Profile builds use `--profile`, then `python -m tools.profile_nnue_v2 --stage
final` after building its two named binaries. Timings are exclusive internal
clock scopes and include instrumentation overhead. Cache/branch hardware
counters were unavailable. Never compare instrumented NPS with release NPS.

## Integer experiment

Weights use signed int16; first-layer sums and all dots use int32. Activation
scale is 4096. Weight scales start at 4096 and reduce by powers of two if needed
for actual int16/int32 bounds. Both finalists use 4096 in every layer. Biases use
their layer's product scale. Embedding and activation conversion round nearest,
ties away from zero; only activations saturate, to [0,4096]. Accumulators remain
unclipped. The first-layer proof includes up to 74 transient rows during sorted
updates, rather than assuming only the final 37 active features. Dense proofs
include absolute bias plus the sum of absolute products, so SIMD partial sums
were also safe. Final output is `400 * integer / (activation_scale * output_scale)`.
No sigmoid, material blend, retraining or QAT is applied. Unsupported integer
bounds disable this optional representation without rejecting a valid float file.

Float32 is preferred: integer prediction changes are small but its speed gain
is inconsistent for Compact and negative for Small. Explicit AVX2/FMA capability
was verified; FMA contraction remains disabled. SIMD float and integer prototypes
were numerically validated, measured, and removed for lack of useful overall
gain. Compiler vectorization of the portable ordered-neuron loop is retained.
