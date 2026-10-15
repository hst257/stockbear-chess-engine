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
| `UseSEE` | Local-bitboard LVA exchange estimate with x-rays, pinned recapture rejection, legal king captures, en passant and promotion accounting. Losing captures follow ordinary quiets. Ordering only; no SEE pruning. |
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

The initial full suite passes **955 tests**, including the new independent
exchange oracle, both-color tactical sacrifices/quiet mates, ordering score
equivalence with selectivity disabled, deterministic search-local history,
native history bounds, adaptive reduction guards, and evaluation symmetry.
The native audit also checks random real/null make/unmake restoration.

Six real-engine rook/queen conversion runs at 25 ms/move reached checkmate:
the previously capped rook ending and its mirror in 11 plies each, central
rook endings in 39/43 plies, and queen endings in 17/17 plies. These are
specific examples, not a complete endgame solver. See
[conversion records](strength/endgame-verification.json).

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
