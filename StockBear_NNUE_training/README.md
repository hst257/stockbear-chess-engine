# StockBear NNUE training

Standalone, phased training project for a custom efficiently updatable chess evaluator.
Scope: stream June–September broadcast PGNs, split by game, label with the local
Stockfish teacher, train in PyTorch, validate and export. No classical-engine changes.

Phases: audit → deterministic sampling → resumable labeling → pilot → bounded full
training → held-out diagnostics → portable float32 export and parity checks.

Implementation and measured results will be documented here after the pilot.
