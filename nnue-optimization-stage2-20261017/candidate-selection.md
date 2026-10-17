# Candidate selection before implementation measurements

Fresh Stage 1 clip observer: 7,192,359 updates / 7,200,000 nodes; one root
refresh/search; 2.32556 rows/perspective; 518.652 logical copy bytes/child.
Frame 1,176 bytes; 65 frames allocated once, 76,440 bytes. Float children need
512 lane bytes plus state metadata; integer lanes are allocated but untouched.

Timer-exclusive bookkeeping remainder is 301 ns/update, sorting 94.72,
row arithmetic 80.50, copying 60.66, metadata 59.14, extraction 30.96,
indexing 29.94, legal-EP checking 0.249 averaged across updates. These timings
include severe observer perturbation: counter builds take 1.055x elapsed,
timers 3.201x. They are clues, not production latency or an Amdahl forecast.
EP executes only 17,364 times / 7.19M updates. Refresh/caching is not a target.

The verified Stage 1 native trace on the exact baseline contains 4,069 samples:
32.37% head, 19.32% recognized maintenance; generic row/state sorting alone
accounts for 2.43% including sort helpers, while much maintenance is inlined
into descent. Attribution cannot reliably separate inlined row arithmetic.
Reuse this coarse native evidence; do not claim exact maintenance cycle shares.

First candidate: specialize the two tiny sorts (state features <=5, changed
rows <=16) with one insertion-sort helper. This addresses repeated generic
bookkeeping without changing storage, extraction, copying or arithmetic. Keep
absolute feature ordering and distinct child ownership. Baseline is separate.

Inactive prototype 5 shrinks a state temporary from 152 to 24 bytes, not the
1,176-byte accumulator frame. Prototype 4 fuses parent copy and ordered row
arithmetic for 2/3/4 rows; it may reduce traffic but needs exact compiled parity
and independent measurement. Both remain possible later candidates if the
first result is inconclusive. Deferred prototype 3 is outside this stage.

Stop after a clear winner; otherwise investigate at most three variants,
independently. No unverified combination. Predeclared material per-fixture
regression threshold is >3% median slowdown, requiring explanation rather
than hiding it in the aggregate. Tiny unstable gains remain inconclusive.
