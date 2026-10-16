# StockBear Final Classical vs NNUE Showdown

## Executive summary

**No: the newly trained NNUE has not earned replacement of StockBear's classical evaluator. Keep classical as the default.** Classical led both matches. The 64/32 result is inconclusive; 128/32 performed substantially worse in this equal-time suite despite its lower teacher-prediction error.

Completed **48 games at 1 second per move**: 24 classical versus 64/32, then 24 classical versus 128/32. Each match used the same 12 fresh opening pairs with reversed colors. No longer controls or extra games were played.

The NNUE candidate with the highest observed score against classical is **64/32**. Neither candidate establishes NNUE superiority under the paired tests after correcting for two comparisons. Observed scores, conditional statistical evidence and the default-evaluator recommendation are distinguished below.

## Engine verification and fairness

The isolated classical executable is a byte-identical copy of the verified 64/32 binary, explicitly selected with `Evaluator=classical`. Its embedded network is unused. Source inspection confirms both NNUE selector flags become false, no NNUE accumulator stack is allocated, and evaluation falls through to the original handcrafted evaluator with its pawn cache. Five CLI/UCI probes across starting, opening and endgame positions matched the protected original engine exactly, including full evaluation components. Switching through NNUE and changing NNUE-only settings restored the same classical evaluations. Every classical tournament search was required to report zero NNUE evaluations; every NNUE search had NNUE calls equal to evaluation calls.

All copies retain identical unchanged C++ search sources, compiler/`-O2` flags, 16 MiB hash, pruning and ordering settings, one search thread and no pondering. NNUE uses scalar float32 and verified incremental accumulators. The classical pawn cache is naturally active only for classical; it is part of the original evaluation implementation. Network dimensions/weights and evaluator selection are the only intended differences.

Prior 38-test regression receipts per distinct NNUE binary were reused after matching their exact hashes. Fresh preflight checks verified intended evaluation, legal moves, castling, en passant, promotion, mate, stalemate and 1-second deadlines for all three copies. Another **29 targeted engine regressions** and **12 preflight harness checks** passed; two later analysis checks covered paired tests, infinite Elo limits and shared-opening comparisons. No training or intensive benchmarks ran during games.

| Engine | Evaluation | Binary SHA-256 | Active network SHA-256 |
|---|---|---|---|
| StockBear-NNUE-128 | nnue | `1d6ea1153a2aa9a75a967d7d40a61af260c0ca6f12d3b1cd7978cff217fc7fd0` | `782a673dd23018d130883af3c97a5d4126dfcf2b74ac1964aab806d71805433c` |
| StockBear-NNUE-64 | nnue | `ffd785d4e8eecacbf6822d98f4a7b6f43972ea89e20c45d0135227e745eab606` | `a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3` |
| StockBear-Classical | classical | `ffd785d4e8eecacbf6822d98f4a7b6f43972ea89e20c45d0135227e745eab606` | Disabled; no active network |

## Tournament configuration

The opening suite was frozen before games with seed 20261017. It comprises 12 manually chosen established lines with starting FENs distinct from the previous showdown. No evaluator or Stockfish analysis was used to select or filter them. Some opening families overlap normal chess practice, so this is a fresh fixed suite, not a statistically independent random sample of all chess. Pair starts alternate which evaluator has White. Match A precedes Match B as requested, so timing/thermal drift across matches remains possible; each match contains its own classical control and its own matched-root comparison.

Each game starts fresh engine processes. Full opening and game history is sent to UCI; python-chess validates every move and claims available threefold/50-move draws, as well as enforcing terminal/automatic draw rules. No evaluation-based adjudication or resignation. The 400-searched-ply cap is unfinished/unscored, not a draw. The per-move wall deadline is 1.100 seconds, including 100 ms protocol/OS allowance; engine and wall time are stored separately. Infrastructure failures halt and retain checkpoints without a chess forfeit.

| Opening ID | Line | Starting FEN |
|---|---|---|
| F01 | Bogo-Indian: d4 Nf6 c4 e6 Nf3 Bb4+ Bd2 Bxd2+ Qxd2 d5 Nc3 O-O | `rnbq1rk1/ppp2ppp/4pn2/3p4/2PP4/2N2N2/PP1QPPPP/R3KB1R w KQ - 2 7` |
| F02 | Queen's Indian: d4 Nf6 c4 e6 Nf3 b6 g3 Bb7 Bg2 Be7 O-O O-O | `rn1q1rk1/pbppbppp/1p2pn2/8/2PP4/5NP1/PP2PPBP/RNBQ1RK1 w - - 5 7` |
| F03 | Caro-Kann Advance: e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 c5 O-O Nc6 | `r2qkbnr/pp3ppp/2n1p3/2ppPb2/3P4/5N2/PPP1BPPP/RNBQ1RK1 w kq - 2 7` |
| F04 | Grunfeld Exchange: d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5 e4 Nxc3 bxc3 Bg7 | `rnbqk2r/ppp1ppbp/6p1/8/3PP3/2P5/P4PPP/R1BQKBNR w KQkq - 1 7` |
| F05 | French Advance: e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3 Qb6 a3 Bd7 | `r3kbnr/pp1b1ppp/1qn1p3/2ppP3/3P4/P1P2N2/1P3PPP/RNBQKB1R w KQkq - 1 7` |
| F06 | London: d4 d5 Nf3 Nf6 Bf4 e6 e3 Bd6 Bg3 O-O Bd3 c5 | `rnbq1rk1/pp3ppp/3bpn2/2pp4/3P4/3BPNB1/PPP2PPP/RN1QK2R w KQ - 0 7` |
| F07 | Reti: Nf3 d5 g3 Nf6 Bg2 e6 O-O Be7 c4 O-O b3 c5 | `rnbq1rk1/pp2bppp/4pn2/2pp4/2P5/1P3NP1/P2PPPBP/RNBQ1RK1 w - - 0 7` |
| F08 | Scandinavian: e4 d5 exd5 Qxd5 Nc3 Qa5 d4 c6 Nf3 Nf6 Bc4 Bf5 | `rn2kb1r/pp2pppp/2p2n2/q4b2/2BP4/2N2N2/PPP2PPP/R1BQK2R w KQkq - 4 7` |
| F09 | Pirc: e4 d6 d4 Nf6 Nc3 g6 Be3 Bg7 Qd2 c6 f3 b5 | `rnbqk2r/p3ppbp/2pp1np1/1p6/3PP3/2N1BP2/PPPQ2PP/R3KBNR w KQkq - 0 7` |
| F10 | Queen's Gambit Accepted: d4 d5 c4 dxc4 Nf3 Nf6 e3 e6 Bxc4 c5 O-O a6 | `rnbqkb1r/1p3ppp/p3pn2/2p5/2BP4/4PN2/PP3PPP/RNBQ1RK1 w kq - 0 7` |
| F11 | Petroff: e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4 d4 d5 Bd3 Be7 O-O Nc6 | `r1bqk2r/ppp1bppp/2n5/3p4/3Pn3/3B1N2/PPP2PPP/RNBQ1RK1 w kq - 4 8` |
| F12 | Sicilian Alapin: e4 c5 c3 Nf6 e5 Nd5 d4 cxd4 Nf3 Nc6 cxd4 d6 | `r1bqkb1r/pp2pppp/2np4/3nP3/3P4/5N2/PP3PPP/RNBQKB1R w KQkq - 0 7` |

## Classical vs 64/32

| Metric | Classical | NNUE |
|---|---:|---:|
| Wins | 10 | 8 |
| Draws | 6 | 6 |
| Losses | 8 | 10 |
| Points | 13 | 11 |
| Score | 54.17% | 45.83% |
| Unfinished (unscored) | 0 | 0 |
| Mean / median reported NPS | 2,972,037 / 3,022,720 | 1,544,759 / 1,618,176 |
| Aggregate nodes / engine seconds (NPS) | 3,031,415 | 1,580,703 |
| Mean completed depth | 8.90 | 8.17 |
| Median completed depth | 9 | 8 |
| Total searched nodes | 3,125,152,816 | 1,636,694,257 |
| Mean engine time / move (s) | 0.9389 | 0.9439 |
| Mean / median wall time (s) | 0.9407 / 1.0017 | 0.9457 / 1.0017 |
| Maximum wall time (s) | 1.0052 | 1.0051 |
| Total engine search seconds | 1030.922 | 1035.422 |
| Evaluation calls | 2,537,000,550 | 1,354,562,081 |
| NNUE evaluations | 0 | 1,354,562,081 |

NNUE scores **11/24 (45.83%)**. Aggregate NPS change versus classical: **-47.9%**. Failure events: 0 crashes, 0 timeouts, 0 illegal moves, 0 other infrastructure failures.

Paired opening units: 12. Conservative 95% score bounds: **6.6–85.0%**; descriptive paired-bootstrap 95%: 27.1–64.6%. Score-equivalent Elo estimate: **-29**, with conservative transformed bounds [-460, +302] and descriptive bootstrap bounds [-172, +104]. One-sided NNUE-superiority p=0.74219; two-sided paired sign-flip p=0.82812; Holm-adjusted two-sided p=0.82812.

## Classical vs 128/32

| Metric | Classical | NNUE |
|---|---:|---:|
| Wins | 16 | 5 |
| Draws | 3 | 3 |
| Losses | 5 | 16 |
| Points | 17.5 | 6.5 |
| Score | 72.92% | 27.08% |
| Unfinished (unscored) | 0 | 0 |
| Mean / median reported NPS | 2,432,401 / 2,351,616 | 699,195 / 700,032 |
| Aggregate nodes / engine seconds (NPS) | 2,488,581 | 715,613 |
| Mean completed depth | 8.72 | 7.71 |
| Median completed depth | 9 | 8 |
| Total searched nodes | 2,675,605,648 | 775,972,318 |
| Mean engine time / move (s) | 0.9301 | 0.9429 |
| Mean / median wall time (s) | 0.9321 / 1.0019 | 0.9450 / 1.0020 |
| Maximum wall time (s) | 1.0041 | 1.0037 |
| Total engine search seconds | 1075.153 | 1084.346 |
| Evaluation calls | 2,169,163,665 | 646,532,964 |
| NNUE evaluations | 0 | 646,532,964 |

NNUE scores **6.5/24 (27.08%)**. Aggregate NPS change versus classical: **-71.2%**. Failure events: 0 crashes, 0 timeouts, 0 illegal moves, 0 other infrastructure failures.

Paired opening units: 12. Conservative 95% score bounds: **0.0–66.3%**; descriptive paired-bootstrap 95%: 14.6–39.6%. Score-equivalent Elo estimate: **-172**, with conservative transformed bounds [-infinity, +117] and descriptive bootstrap bounds [-307, -73]. One-sided NNUE-superiority p=1.00000; two-sided paired sign-flip p=0.01562; Holm-adjusted two-sided p=0.03125.

## Search speed and depth at identical roots

Only the first search of each color-reversed game is compared. Each evaluator searches the identical opening FEN/history with fresh processes and the same 1-second budget. Ratios are geometric means over the 12 matched FENs, not an inference microbenchmark; evaluators can still explore different trees.

| NNUE | Matched roots | NPS relative to classical | Mean completed-depth difference |
|---|---:|---:|---:|
| 64/32 | 12 | 0.603× (-39.7%) | -0.50 |
| 128/32 | 12 | 0.384× (-61.6%) | -0.75 |

The selected 128/32 model has lower validation blended MSE (0.0108725) than 64/32 (0.0111739). Its observed score against classical differs by -18.75 percentage points on the same 12 opening pairs, with descriptive paired-bootstrap bounds [-35.42, +0.00] percentage points. This exploratory comparison is against a common opponent, not a direct 128-versus-64 match or proof that teacher prediction causes chess strength.

Arithmetic mean and median NPS above use per-move UCI-reported values. Aggregate NPS divides total nodes by total engine seconds, weighting longer searches more heavily. Completed depth is the last fully finished iteration; counters include work in interrupted deeper iterations. Speed and depth alone do not determine playing strength. Results apply to these scalar float32 builds on this laptop.

## Statistical uncertainty

An opening pair, including both colors, is one uncertainty unit. Primary 95% Hoeffding bounds are very conservative for only 12 pairs. The 5,000-resample paired bootstrap is descriptive, may degenerate for unanimous outcomes, and does not repair the fixed-suite sampling limitation. Elo is the conventional 400*log10(score/(1-score)) score equivalent; it is not an external rating or definitive strength estimate. Bounds reaching 0 or 1 map to infinite Elo limits, not silently truncated finite precision.

The exact sign-flip test exchanges entire evaluator labels within each opening pair and assumes independent, label-exchangeable pair outcomes under equal strength. Holm adjustment covers the two two-sided evaluator-difference comparisons; direction comes from the paired score. The one-sided NNUE-superiority p is also shown without a separate significance decision. Any significant finding is conditional on those assumptions and this suite; related openings, limited sample size, training/model selection and one hardware/time configuration limit generalization. No prior NNUE-versus-NNUE game contributes to these scores, tests or Elo estimates.

## Instructive games

Examples below are selected by outcome and length to show the recorded range, without a new teacher analysis. They illustrate results rather than proving the cause of a win.

- [G023](final-nnue-showdown-20261017/games/G023.pgn): StockBear-NNUE-64–StockBear-Classical, Sicilian Alapin, 1-0, checkmate, 45 searched plies.
- [G017](final-nnue-showdown-20261017/games/G017.pgn): StockBear-Classical–StockBear-NNUE-64, Pirc, 1-0, checkmate, 65 searched plies.
- [G006](final-nnue-showdown-20261017/games/G006.pgn): StockBear-NNUE-64–StockBear-Classical, Caro-Kann Advance, 1/2-1/2, threefold_repetition, 49 searched plies.
- [G043](final-nnue-showdown-20261017/games/G043.pgn): StockBear-NNUE-128–StockBear-Classical, Queen's Gambit Accepted, 1-0, checkmate, 45 searched plies.
- [G033](final-nnue-showdown-20261017/games/G033.pgn): StockBear-Classical–StockBear-NNUE-128, French Advance, 1-0, checkmate, 59 searched plies.
- [G036](final-nnue-showdown-20261017/games/G036.pgn): StockBear-Classical–StockBear-NNUE-128, London, 1/2-1/2, threefold_repetition, 85 searched plies.

## Conclusions and default-evaluator recommendation

**Observed leader:** classical scored 13/24 against 64/32 and 17.5/24 against 128/32. NNUE 64/32 is the stronger observed NNUE candidate against this common opponent: 11/24 (45.83%), versus 128/32's 6.5/24 (27.08%). These are separate head-to-head results, not a pooled Elo estimate.

**Statistical evidence:** 64/32 does not demonstrate superiority over classical; its two-sided Holm-adjusted paired p-value is 0.828125, so its small observed deficit is also inconclusive. Classical's advantage over 128/32 has conditional paired-test support (adjusted p=0.03125); 128/32 won no opening pair on aggregate, losing seven and splitting five. Its descriptive paired bootstrap score interval is 14.58–39.58%. The much more conservative distribution-free interval still includes parity (0–66.29%): the sharper test and bootstrap rely on additional exchangeability/sampling assumptions. This is evidence on one small fixed suite, not a precise universal Elo claim.

**Teacher prediction versus play:** 128/32's lower selected validation MSE did not translate into a better score against classical here. Its 18.75-percentage-point observed deficit versus 64/32 has descriptive matched-opening bootstrap bounds −35.42 to 0.00 points; that comparison remains exploratory. Better teacher prediction alone neither establishes better equal-time chess nor explains the cause of the loss. The earlier NNUE-only showdown favored 128/32 at 1 second, but different opponents/openings and small samples can change the ranking; none of those earlier games is pooled here.

**Engineering recommendation:** retain classical as StockBear's default and keep both NNUE models for isolated experiments. The larger model's additional cost is not justified by these results. On identical opening roots, 64/32 loses about 40% of classical's NPS and 0.50 completed ply; 128/32 loses about 62% and 0.75 ply. Across whole games, NPS is lower by 47.86% and 71.24%, with mean completed-depth deficits of 0.73 and 1.00 ply. Different search trees also affect these measurements, so they do not prove inference cost alone caused the score difference. No evaluator was automatically promoted or installed.

**Smallest useful next strength experiment:** if continuing the inconclusive 64/32 question, predeclare one further 24-game classical-versus-64/32 match at 1 second, using 12 fresh holdout opening pairs with reversed colors and the same frozen binaries/options. This is a useful independent replication, not a promise of enough power to resolve a small Elo gap. Freeze the analysis and count before play; do not select openings or extend the schedule based on interim outcomes. No such extra games were run in this investigation.

## Preservation and completion

Final audit replayed **4,501 searched moves** in **48 games**, verified PGNs, evaluator counters, deadlines and frozen identities. **491 protected files** were unchanged. Classical NNUE evaluations across the tournament: **0**. Termination counts: `{'checkmate': 39, 'threefold_repetition': 9}`. Saved failure events: **0**. Elapsed first-start to last-finish time: 2.03 hours, including the user-requested pause. Recorded search wall time totals 1.18 hours.

The user paused after exactly 15 completed games and resumed through a one-time thread automation at 03:30 IST on October 17. Completed games were skipped. To impose the initial 15-game boundary, G014 had been interrupted after 22 saved searched moves and resumed with fresh processes and full legal history. Its cold transient caches are a minor fairness limitation; the later scheduled pause fell between games. `pause-history.json` retains the timestamps. No completed result was replayed.

Original classical evaluation, the active executable, previous checkpoints, optimized v2/v3 models, and previous showdown artifacts are preserved. The sealed test dataset was not opened or hashed. No networks were trained, no labels generated and no search heuristics changed.

## Artifacts and reproduction

Directory: `Z:\Code\Chess\final-nnue-showdown-20261017`. `plan.json` records options, game order, openings, source/engine/network identities and frozen runner dependencies. `verification.json`, `audit.json`, `analysis.json`, `scoreboard.json` and `games/Gxxx.json`/PGN retain verification and raw results. Isolated executables and logs are in `artifacts/`. Completed JSON records are authoritative; resume skips them and restores partial move histories.

```powershell
Set-Location Z:\Code\Chess
.\.venv\Scripts\python.exe -m tools.final_nnue_showdown progress
.\.venv\Scripts\python.exe -u -m tools.final_nnue_showdown run --resume
.\.venv\Scripts\python.exe -m tools.report_final_nnue_showdown
```

A completed schedule starts no extra games. A fresh reproduction needs another experiment directory. The previous NNUE scaling/showdown reports are background context only.
