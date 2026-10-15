# Candidate contracts and decisions

All candidates keep float32 row additions/subtractions in the same per-perspective
feature-index order. Roots use full refresh. Legacy full-metadata APIs remain
available. `--nnue-update legacy|merge|compact|deferred|fused|compact-small` selects a build-time
experiment, not a new UCI/search setting. Model/kernel/search options are frozen.

## Merge full metadata

Hypothesis: merge existing features and sorted deltas once, avoiding repeated
binary searches and array shifts. Full feature lists and missing-piece checks
remain. Exact 96-case search parity and bitwise transition oracle passed. Three
400k-node trials yielded 1.010× wall speedup, selected-position bootstrap
0.987–1.030×. **Reject as an independent production change:** no clear benefit.

## Compact search metadata

Hypothesis: move-derived updates consume only the previous castling/legal-EP
state features; maintaining all sorted piece features is redundant. Keep the
complete unclipped float lanes, but retain sorted state features only in child
metadata. The general updater still produces/validates full feature sets.

The trusted invariant is local to the search-only API: each delta is obtained
from the current board and a move produced by legal move generation before
make; after-move state extraction remains unchanged, including legal EP and
clean castling rights. Null edges use an empty piece delta. Children use distinct
stack storage. Never pass a compact child to the generic feature-diff updater.
Kernel selection is search-local and roots refresh, so switching to reference or
quantized evaluation starts with full metadata. Quantized/reference paths retain
the legacy implementation. No chess legality or state-feature check is removed.

Removing the redundant sorted-list missing-piece lookup relies on that legal
delta invariant. The independent native oracle computes both full reference and
compact children for every tested transition and compares float bits, final score
bits, nulls and sibling preservation. Fixed-work search parity exercises the
actual integrated path, rather than merely a standalone evaluator.

Initial three-trial 400k-node wall speedup: 1.169× (1.138–1.200 selected-position
bootstrap), NNUE/classical NPS 0.697→0.816. One fixture regressed in that screening
sample. Acceptance depends on final repeated measurements and regression gates.

## Intermediate-cached deferral prototype

Invariant: a pending frame records its move delta and exact after-move state
features. Numerical sums are required only immediately before a head call.
Materialization first ensures its parent, then applies the original ordered delta
and caches **every** intermediate frame. A live edge materializes at most once;
sibling reuse invalidates that child slot. Roots are always ready. PVS retries
reuse an unchanged live frame; cancellation discards the private stack.

Worst pending chain is bounded by the 64-ply search stack. Work cannot exceed
eager row replay for the same tree; it avoids the previous 2.50× repeated replay
failure. Fully unused subtrees can save row/copy work. Delta/state construction
still happens at every edge. Additional pending storage is approximately 11.7KB
(65 frames of delta, full state-feature container and readiness), plus allocation,
branches and recursive readiness checks. This increases cache pressure; there
are no measured hardware cache-miss claims.

The prototype is behind `--nnue-update deferred` and never changes search return,
pruning or time checks. It is release-only: eager-frame diagnostic lifetimes do
not describe delayed materialization, and the build rejects combining these old
counters with the prototype. Exact search/evaluation parity and release timing
are its acceptance gates. Eager updates remain the default until a reproducible
additional benefit is demonstrated.

Direct five-trial comparison against eager compact: 0.973× speed, selected-FEN
bootstrap 0.955–0.992×. **Rejected:** approximately 2.7% slower despite bounded
replay. The bookkeeping/allocation/readiness cost outweighed skipped updates.

## Scalar fused row loop

Keep one lane in a local float while applying exactly the same ordered rows;
specialize two/three/four-row cases, avoiding a separate lane copy and repeated
array writes. No explicit SIMD, sign multiplication or fast-math. Bitwise lane
and score oracles, plus 96 deterministic search cases, passed. Direct five-trial
speed relative to eager compact was 0.990× (0.970–1.010×). **Rejected:** no
repeatable additional benefit. Compiler dependency/loop choices are plausible
explanations, not measured hardware instruction/cache attribution.

## Five-state temporary

Replace the 152-byte feature extraction temporary with a 24-byte container:
four clean castling rights plus at most one legal EP file. Keep accumulator
storage unchanged. Exact arithmetic/search gates passed. The direct five-trial
speed ratio was 0.995× (0.979–1.012×). **Rejected as a production optimization:**
smaller source-level temporary size did not demonstrate a runtime benefit.

Only eager compact child metadata is selected for final verification. Other
implementations remain build-time experiments; the ordinary build omits them.
Default scalar and auto use compact state, while reference/quantized keep full
metadata. `--nnue-update legacy` explicitly restores the original update path.
