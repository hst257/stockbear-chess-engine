# StockBear NNUE v3 design and feasibility

## Baseline and scope

Start from optimized v2 revision `2432323`. Preserve classical, all v2 source,
models, labels, splits and previous experiments. Classical stays the default.
The frozen v2 32/16 model has 26,081 parameters and SHA256
`788b865a15dbdeeb3e03b7493f8155fd19d6c73b9b0873453ad16fba51a65aa7`.
Its equal-time classical comparison was 11 wins, 14 draws and 15 losses in
40 games at 500ms/move (20 reversed-color opening pairs), not proven inferiority.
The throughput study found a 15.5% identical-work gain; retain its eager design.

## Primary feature contract: full king conditioning

Use a single normalized table shared by White and Black perspectives.
Squares use a1=0 through h8=63. For Black, mirror ranks with `square ^ 56`;
files are not mirrored. Normalize piece color as friendly=0, enemy=1.
For each non-king piece, with pawn/knight/bishop/rook/queen types numbered 0–4:

`((oriented_own_king * 10 + relative_color * 5 + type) * 64 + oriented_piece)`.

This is genuinely king-conditioned: 64 × 10 × 64 = 40,960 piece features.
Kings condition the tables; neither king is an ordinary piece feature. Both
perspectives reach the head, so both kings' contexts remain represented.
Append 12 unconditioned state features: own K/Q rights, opponent K/Q rights,
then eight legal en-passant files. Clean rights and legal EP match v2/python-chess.
Total inputs: **40,972**, plus a zero padding row at index 40,972.
Legal orthodox positions have at most 30 non-king pieces plus five state rows:
**35 active features per perspective**. Sort active indices ascending. Missing
kings and invalid positions are rejected by feature entry points. Empty squares
add no features. Halfmove/repetition counters are search rules, not neural inputs.
The head orders perspectives side-to-move first; turn is not a feature bit.
Color-swapping/rank-mirroring preserves normalized inputs, including rights/EP.

## Architecture and memory

Primary candidate A: sparse indexed embedding sum, shared 32-wide transform,
shared bias, clipped [0,1] concatenated 64-vector, 16-wide clipped hidden layer,
linear scalar output. Output is side-to-move centipawns / 400, unchanged from v2.
No transfer of incompatible v2 weights, material blend, precision change or
quantization. Float32 training/inference; disable TF32 and fused arithmetic.

Including padding: `(40972+1)*32 + 32 + 64*16+16 + 16+1` = **1,312,225**
parameters; payload **5,248,900 bytes**. AdamW weights/gradients/two moments
need about 21 MB before runtime overhead. A 2,048-position gathered batch has
at most 2,048×2×35×32 floats (18.4 MB); do not materialize dense input vectors.
About one million uint16 examples need 140 MB host feature cache; an int64
GPU-resident index copy needs 560 MB. A measured pilot must establish peak VRAM
and throughput before full training. Project drive currently has over 100 GB free.

Native frames contain two *unclipped*, fixed White/Black 32-float accumulators,
two king squares and compact state indices. No sorted piece-list metadata is
maintained per ordinary move. Expect roughly 300 bytes/frame, measured after build.
The immutable ~5 MB shared model replaces no v2 data. Each search owns its stack.
Ordinary quiet moves change two rows/perspective; captures three, promotions
two or three, EP three. Null moves change only legal-EP state and head order.

## King moves and numerical contract

Capture legal move deltas before make. When a perspective's king square changes,
refresh that perspective from the new sorted feature set. Update the other
perspective with piece/state deltas; castling includes rook relocation. Refresh
roots and isolate siblings. Sorted signed row changes preserve a deterministic
incremental arithmetic order. Refresh versus incremental sums may round
differently: initial gates are lane error <=1e-4 and output error <=0.02cp;
measure actual maxima and investigate any excess or unexplained tree instability.
Python/C++ feature indices must match exactly, and native/PyTorch scores must
meet the 0.02cp tolerance on held-out and extreme fixtures.

## Dataset and training gates

The existing 1.25M nominal pool exposes **999,464 train / 19,930 validation /
20,152 test** examples, preserving v2's common 200K holdout prefix. Reuse its
uint16 features to re-encode king-conditioned indices without relabeling; verify
against independently parsed source FENs. Copy targets/ordinals byte-for-byte,
verify original hashes and grouped split separation, and retain teacher profile
`ddc2b43b123677466a9a9f8478f67ffc028a6582266a73e36a3272bc85b30f92`.
Teacher: existing Stockfish labels at 16,384 nodes. Targets stay 90% sigmoid
teacher cp (clipped ±2000, scale 400) plus 10% side-to-move game outcome.

Gate order: Python features/tests → minimal native feature/forward prototype →
small GPU pilot with measured peak/time → primary full run. Start fresh with
seed 20261016; AdamW lr .0015, weight decay .05, batch 2048, clipping 1.0,
validation plateau scheduler and early stopping, maximum 60 epochs. Record
deviations if the pilot justifies them. Select checkpoints only on validation;
evaluate final test once. Epoch checkpoints include optimizer/scheduler/RNG and
immutable dataset/config signatures for interruption recovery.

## Integration, experiments and selection

Add independent `nnue_v3.hpp/.cpp` and Python `stockbear/v3/`; retain v2's
`nnue.hpp/.cpp` unchanged. A versioned little-endian format has fixed dimensions,
contract/architecture identifiers, float precision, output scale and payload
SHA256. Reject truncation, mismatched contracts, nonfinite or corrupt weights.
UCI/GUI explicitly select classical, existing NNUE and experimental v3. Failed
model loading preserves the previous selection. Search snapshots immutable model
ownership; join workers before model changes; each search has fresh TT state.

After correctness, compare classical/v2/v3 on the fixed 24 FENs at
100k/400k/1M nodes and 50/200/500/1000ms. Same settings, Hash16, one worker,
rotating serial trials; no tournaments during GPU training. Run a smoke pair,
then a fixed **40-game v3-v2 match at 500ms** using the first 20 neutral opening
pairs. If promising (at least 50% completed-game score with no correctness
failure), run a separately planned **40-game v3-classical** cohort on those same
pairs. No result-driven expansion. Use paired uncertainty; record caps as unknown.
Compare held-out equal-node move quality to independent 65,536-node reference
analysis, explicitly acknowledging the teacher's relationship to training labels.

Full king conditioning can overfit infrequent king contexts, costs more cache
capacity, and refreshes on king moves. These are measured risks, not a strength
promise. Bucketing or larger transforms remain fallback research options only
if the primary experiment justifies another bounded candidate. Prefer v2 when
v3 does not establish a useful equal-time benefit; never change defaults based
on validation loss alone. Preserve negative results and all previous research.
