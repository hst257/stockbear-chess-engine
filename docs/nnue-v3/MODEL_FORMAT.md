# StockBear v3 model contract

This is a separate format from StockBear float32 v1/v2 exports and Stockfish
NNUE files. Never pass it to the v2 embedding generator.

The 72-byte little-endian header is `<8s8I32s`:

| Field | Required value |
| --- | --- |
| Magic | `SBNNUE3\0` |
| Format version | 3 |
| Feature contract | 1 = full 64-square king conditioning; 2 = 16 king buckets |
| Feature count | 40,972 for contract 1; 10,252 for contract 2 |
| Transformer width | 32 |
| Hidden width | 16 |
| Weight precision in bytes | 4, IEEE float32 |
| Output cp scale | 400, side-to-move perspective |
| Architecture/layout identifier | 6: shared embedding, clipped 32/16 head, six tensors below |
| SHA256 | 32 raw bytes, checksum of the complete weight payload |

The architecture/layout identifier fixes the activation (`clip(x,0,1)`), tensor
order and shapes: `bias[32]`, `transform.weight[features+1,32]`,
`fc1.weight[16,64]`, `fc1.bias[16]`, `fc2.weight[1,16]`, `fc2.bias[1]`.
There are no gaps or trailing bytes. The last embedding row is zero padding.
Weights must be finite and have absolute magnitude at most 1e6, bounding
intermediate float operations under this fixed architecture. All readers reject
wrong dimensions/layouts/contracts, truncation, checksum damage and bad padding.

Feature indexing and state/turn conventions are specified in
[`NNUE_V3_DESIGN.md`](../../NNUE_V3_DESIGN.md). The file checksum and payload
checksum identify weights; experiment reports separately retain provenance,
dataset/split hashes, training settings and exact training-source snapshots.

Native model objects are immutable snapshots. UCI joins a current worker before
replacing a model, and commits a loaded candidate only after validation. Failed
loading retains the previous model/selection. A new search refreshes roots and
creates a fresh TT, preventing reuse across evaluators or models. GUI validation
and loading run on the worker thread. Classical remains the default.
