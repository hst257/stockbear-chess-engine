# StockBear float32 export v1

This is a custom StockBear evaluator, not a Stockfish `.nnue` file. The parent
engine supports [native inference](../../docs/nnue.md). Quantization is deferred: the v1
artifact preserves float32 weights, with an independent NumPy reader and golden
outputs that can serve as a future C++ acceptance contract.

## Features

There are 780 binary features in each of two fixed perspectives (white, black).
Squares use python-chess numbering: a1=0, b1=1, ... h8=63.
Black perspective rotates ranks only: `square ^= 56`; files do not flip.
Relative color is 0 for a piece of the perspective's color, 1 for the opponent.
Piece type is pawn=1, knight=2, bishop=3, rook=4, queen=5, king=6.

`piece_index = (relative_color * 6 + piece_type - 1) * 64 + oriented_square`

Castling rights: 768 own kingside, 769 own queenside, 770 enemy kingside,
771 enemy queenside. Use legal-board castling rights, not merely raw FEN bits.
If a *legal* en passant capture exists, activate `772 + ep_file` (a=0, h=7).
No EP feature is active for a merely pseudo-legal EP square.

At most 37 features are active. Training pads to 37 with index 780, whose weight
row remains zero and is never counted. The serialized transform includes this
padding row, making its shape `[781, width]`.

The label FEN has halfmove clock=0, fullmove number=1. This network models static
position evaluation, not repetition history or exact fifty-move draw state.
Chess960 and nonstandard variants are excluded.

## Forward pass and incremental updates

For each perspective `p`, accumulator `a[p] = bias + sum(transform[index])`.
Keep the *unclipped* accumulators in fixed white/black order. On a move, subtract
rows for features no longer active and add rows for newly active features.
This includes captures, promotions, castling, king moves, rights changes and EP.
All features are unbucketed, so king moves do not require a full refresh.
The Python reference computes changed-feature sets from boards for correctness;
a future C++ implementation can derive the small delta from move state.

For evaluation, concatenate `clip(a[side_to_move],0,1)` and
`clip(a[opponent],0,1)`. Then:

```
h = clip(fc1.weight @ concatenated + fc1.bias, 0, 1)
z = fc2.weight @ h + fc2.bias
side_to_move_centipawns = 400 * z
white_centipawns = side_to_move_centipawns * (1 if white_to_move else -1)
```

The sigmoid is used only for training/diagnostics, not the centipawn inference
path. Integer quantization is not part of v1. Do not round or clamp accumulator
values before activation. Float32 incremental sums may drift slightly with long
move sequences; refresh on a new root and validate against golden outputs.

## Binary layout

All integers and tensor elements are little endian. The file contains:

1. 8 bytes: `SBNNUE1\0`.
2. uint32: UTF-8 JSON header length in bytes.
3. That many header bytes, with no padding.
4. Concatenated contiguous C-order float32 tensor payload.

Header fields include `format`, `feature_version`, `features`, `model`,
`score_pov`, `output_cp_scale`, `activation`, `signature`, `best_epoch`,
`payload_sha256`, and `tensors`. Each tensor entry specifies `name`, `shape`,
`dtype` (`<f4`) and `offset` in bytes from the start of the payload.

Tensor names/shapes for width=128, hidden=32:

| Name | Shape |
|---|---|
| bias | 128 |
| transform.weight | 781 × 128 |
| fc1.weight | 32 × 256 |
| fc1.bias | 32 |
| fc2.weight | 1 × 32 |
| fc2.bias | 1 |

Honor the header order and offsets. Linear weight matrices use `[out, in]`.
The selected compact model instead uses width=32 and hidden=16. The same format
applies: its transform is 781×32, fc1 is 16×64, and fc2 is 1×16. Read the shapes
from the header rather than assuming the example's dimensions.
Validate the magic, feature version, total size and payload SHA256 before use.
`stockbear.export.load_export` reads without importing PyTorch.
The adjacent `.golden.json` holds up to 128 held-out FENs and side-to-move scores.
Export must match PyTorch to within 0.01 cp on those positions.

## Teacher and target convention

The local teacher's binary SHA256, fixed node budget and UCI settings identify a
label profile. Each worker uses one thread, full strength and no tablebase path.
Clear Hash and a new game token reset search state before every position.
Scores are converted to the side-to-move perspective. Mates retain their signed
distance in the cache and use ±2000 cp in the regression target. Ordinary cp
scores are retained raw; target probabilities clip them to ±2000 cp.

`target = 0.9 * sigmoid(clip(teacher_cp,-2000,2000)/400) + 0.1 * game_result_stm`

The sigmoid/400 is a chosen training scale, not a calibrated Stockfish win
probability or three-way WDL model. The loss is squared probability error.
Game outcomes are weak auxiliary targets. Diagnostics separately report pure
teacher error, result-independent baselines and phase/month breakdowns.
