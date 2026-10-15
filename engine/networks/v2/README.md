# StockBear v2 finalists

These are byte-for-byte copies of the original training exports and 128-position
golden references. Both retain the StockBear float32 v1 file format; “v2” names
the training generation, not a new binary format. The training folder remains
unchanged. Compact is 32/16; Small is 64/32. Neither is a Stockfish NNUE file.

Build each into a separate executable from the repository root:

```powershell
.\.venv\Scripts\python.exe tools/build_engine.py --nnue-model engine/networks/v2/stockbear-v2-compact.sbnnue --output engine/build/stockbear-v2-compact.exe
.\.venv\Scripts\python.exe tools/build_engine.py --nnue-model engine/networks/v2/stockbear-v2-small.sbnnue --output engine/build/stockbear-v2-small.exe
.\launch.bat --mode engine --evaluator nnue --engine engine/build/stockbear-v2-compact.exe
```

Use the Small executable in the last command to play that model. Game setup and
Search lab switch between classical and the NNUE embedded in that executable.
Model selection is at build/startup; runtime file loading is not implemented.
The ordinary build retains the bundled v1 NNUE. Classical remains the default
evaluator in every build.

UCI options:

```text
setoption name Evaluator value nnue
setoption name NNUEKernel value scalar
setoption name NNUEIncremental value true
```

`auto` selects optimized portable float32; `reference` selects original float32
inference and board-derived updates; `scalar` selects the optimized layout and
move-derived updates. `quant` explicitly selects experimental integer inference.
`NNUEIncremental=false` independently rebuilds each evaluation. Kernel changes
stop/join a running search, refresh its next root and use fresh TT storage.
No search policy or classical evaluation formula changes with the kernel.

See [optimization results](../../../NNUE_V2_OPTIMIZATION_RESULTS.md) and
[reproduction guide](../../../docs/nnue-v2/README.md) before interpreting speed
or game results. Quantization and explicit SIMD did not beat the retained
float32 implementation reliably; the SIMD prototypes remain in Git history and
their frozen measurement binaries, rather than the production evaluator.
