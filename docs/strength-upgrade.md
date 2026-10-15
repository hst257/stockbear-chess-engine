# Classical strength upgrade (ChessLab 0.12)

This upgrade adds search guidance and classical evaluation experiments before
NNUE. It keeps the custom C++ search, existing board UI, and one-second default.
The previous 0.11 binary was frozen before editing at
`artifacts/strength/baseline-0.11.exe` (source `cc9c2a1`). Generated executables
remain ignored; source, measurements, and game records are committed.

## Search and evaluation

| UCI switch (default true) | Behavior |
| --- | --- |
| `UseHistory` | Color/from/to quiet history, bounded gravity updates, depth-based cutoff rewards and maluses for previously searched quiet moves. Fresh each search; shared across its iterations. |
| `UseKillers` | Two quiet cutoff moves per ply, below favorable captures and above ordinary quiets. No synthetic-null training. |
| `UseSEE` | Local-bitboard LVA exchange estimate with x-rays, pinned recapture rejection, legal king captures, en passant and promotion accounting. Losing captures receive negative ordering priorities. Ordering only; no SEE pruning. |
| `UseAdaptiveLMR` | Extend the existing base `LMRReduction` using depth, move number and history. Clamp reductions to 1–4 and leave at least one child ply. Protect killers and retain nominal-depth verification/PVS re-search. Has no effect when LMR or ordering is off. |
| `UseReverseFutility` | Non-root, non-check, unit-window static cutoffs at depths 1–3 with a 120 cp/depth margin. |
| `UseFutility` | Skip low-priority nonchecking quiets at depths 1–2 with a 180 cp/depth margin, after searching at least one move. Protect TT/PV/killers, strong history, castling and promotions. |
| `UseCheckExtensions` | At most two additional checked-node plies along any real line, within the absolute ply ceiling. Extension-budget contexts use separate TT keys. |
| `UseMopUp` | Pawnless mating material against a bare king: favor king approach and edge confinement. B+N additionally favors bishop-colored corners. Exclude lone minors, two knights, same-colored bishops and defended endings. Gated by advanced evaluation and `EvalEndgame`. |

Both futility features reject low material, repeated positions, clocks >=90,
mate windows and synthetic null paths. Neither affects quiescence. Minimax
ignores selective pruning/extensions; ordering and evaluation remain shared.
Selective scores are not guaranteed to equal exhaustive scores. TT score
reuse still requires the established depth/ply/history/clock contracts.
Stop, undo, fallback and completed-iteration publication are unchanged.

The Python `EngineSettings` snapshot carries every switch. Launch flags are
`--[no-]history`, `--[no-]killers`, `--[no-]see`, `--[no-]adaptive-lmr`,
`--[no-]reverse-futility`, `--[no-]futility`, `--[no-]check-extensions` and
`--[no-]mop-up`. UCI emits feature counters in the existing `optim` record.

For an exhaustive comparison, disable null moves, LMR, both futility switches
and check extensions; use identical evaluation/quiescence settings. Turn off
history/killers/SEE too when reproducing historical node counts or tie choices.

## Classical tuning

`Weight{Pawns,Passers,BishopPair,Rooks,Mobility,Outposts,KingSafety,Space,Endgame}{MG,EG}`
are independent integer percentages, range 0–200. Material and PST stay fixed.
Multiply each component before the single global taper; diagnostics reconcile
the scaled components, rounding and final endgame scaling exactly.

`tools.tune_evaluation` fits 18 percentages with bounded coordinate descent
and a weak prior toward 100%. Deeper frozen-engine scores supply soft labels.
Opening pairs stay in one split; duplicate positions are excluded. Its report
can be passed directly to the match runner with `--candidate-options`.

The saved experiment has 635 training and 165 held-out positions, sampled from
the previous audit PGNs with depth-4 teacher scores. Training probability MSE
fell from 0.01167345 to 0.01102010; held-out MSE fell from 0.01516563 to
0.01508056 (about 0.56%). This small, own-engine dataset is calibration evidence,
not Elo evidence. Neutral 100% defaults remain until game validation supports
a change. The proposed weights are reproducible in
[the report](strength/tuning-report.json) and [dataset](strength/tuning-data.json).

## Verification and reproduction

The final full suite passes **960 tests** in 90.22 seconds, including the independent
exchange oracle, both-color tactical sacrifices/quiet mates, ordering score
equivalence with selectivity disabled, deterministic search-local history,
native history bounds, adaptive reduction guards, and evaluation symmetry.
The native audit also checks random real/null make/unmake restoration.

The UBSan audit passed **27,509** random transitions, history saturation, adaptive
reduction bounds, pawn-cache collisions, and bounded search checks. No sanitizer
finding occurred. The pinned compiler emitted libunwind export-attribute warnings
while building its runtime; project sources compiled successfully.

All five real Pygame/UCI time presets, undo/new cancellation, comparison mode and
six clean worker exits passed. A separate desktop launch rendered White's legal
Nc3 response and exited cleanly. GUI frame timings were gathered while the
sanitizer compiler ran, so they are diagnostic rather than an isolated performance
comparison. See [GUI evidence](strength/gui-verification.json) and
[final verification](strength/verification.json).

Six real-engine rook/queen conversion runs at 25 ms/move reached checkmate:
the previously capped rook ending and its mirror in 11 plies each, central
rook endings in 39/43 plies, and queen endings in 17/17 plies. These are
specific examples, not a complete endgame solver. See
[conversion records](strength/endgame-verification.json).

### Search measurements and games

The [three-repeat alternating comparison](strength/search-comparison.json)
uses unchanged portable O2 builds, default options and 100/500/1000 ms limits.
At 1 second the median completed nominal depths changed as follows:

| Position | 0.11 | 0.12 |
| --- | ---: | ---: |
| Opening | 9 | 10 |
| Middlegame | 8 | 8 |
| Tactical / Kiwipete | 8 | 8 |
| Pawn ending | 13 | 13 |
| Zugzwang fixture | 15 | 20 |

At nominal depth 6, median opening time fell from 55 to 7 ms and middlegame
time from 104 to 39 ms. Kiwipete regressed from 136 to 159 ms: SEE and more
informed ordering have a cost, and extensions change the searched horizon.
Raw 1-second NPS decreased roughly 20–32% across these positions. These are
different selective trees, so depth and node reductions alone prove no Elo gain.

The [100-game match](strength/version-matches.json), with
[replayable PGNs](strength/version-matches.pgn), used 50 unique opening pairs,
20 ms per move, both colors, seed 20261015 and a 240-additional-ply cap.
Results: **50 wins, 39 draws, 11 losses, no unfinished games**; 69.5% score.
The experiment's logistic estimate is +143 Elo, with a conservative paired
95% Hoeffding interval approximately +2 to +358 under nominal independent-pair
assumptions. This suggests improvement at this very fast control; shared opening
families, a baseline-evaluator opening filter, OS scheduling, and the single
machine/control prevent a universal strength claim. The score was evaluated
after the predetermined 100 games, not by repeatedly stopping on significance.

The fitted-weight [40-game screen](strength/tuning-matches.json), using seed
20261016 and the same new binary on both sides, produced **14 wins, 15 draws,
10 losses and 1 unfinished cap**. The score on completed games was 55.13%, but
the conservative paired rating interval spans about -199 to +321 Elo. This does
not justify changing defaults: the proposed weights remain an optional
`--candidate-options docs/strength/tuning-report.json` preset. The capped game
is excluded as unfinished, never silently scored as a draw.

Both match files were independently replayed: **16,737 legal plies**, exact PGN
move agreement, paired openings, colors, results, summaries and executable hashes
all verified. See [replay evidence](strength/replay-verification.json). Search
measurements and matches use the C++ implementation committed as `d81fb26`;
later commits add regression cases, Python formatting and reports, without
changing that native binary.

```powershell
.\.venv\Scripts\python.exe tools/build_engine.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tools.verify_endgames --output artifacts/strength/local-endgames.json
.\.venv\Scripts\python.exe -m tools.verify_gui_engine --output artifacts/strength/gui
.\.venv\Scripts\python.exe -m tools.tune_evaluation --data docs/strength/tuning-data.json --output artifacts/strength/local-tuning.json
.\.venv\Scripts\python.exe -m tools.compare_engine_versions --engines baseline=artifacts/strength/baseline-0.11.exe candidate=engine/build/chesslab-engine.exe --allow-search-changes --output artifacts/strength/local-comparison.json
.\.venv\Scripts\python.exe -m tools.match_optimizations --comparison versions --opponent artifacts/strength/baseline-0.11.exe --games 100 --movetime 20 --max-plies 240 --output artifacts/strength/local-match.json
```

The comparison's explicit `--allow-search-changes` avoids demanding identical
trees from selective algorithms; the older audit default still checks exact
equivalence. Matches record executable hashes, effective option overrides,
paired openings, moves and unfinished caps. Small samples cannot establish a
universal rating. NNUE and multithreading are outside this upgrade.
