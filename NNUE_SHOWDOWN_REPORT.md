# StockBear NNUE Architecture Showdown

## Result and recommendation

The equal-weight ranking across the two retained controls selects **128** as the leading candidate for a future classical match. The winner remains uncertain: the small fixed opening suite and broad paired-opening intervals do not establish a definitive strength difference. No Elo estimate pools time controls, and validation MSE is not used to rank chess results.

**128/32 is the recommended candidate for the next classical comparison at 1 second per move.** It has the highest observed 1-second score, while 64/32 leads at 500 ms. The largest network's extra evaluation cost is promising at 1 second on this suite, but the 500 ms results do not justify a blanket claim that larger is stronger. Broad uncertainty means this is a practical candidate choice, not a proven upgrade.

## Configuration and fairness

Completed 108/108 games: 72 at 500 ms and 36 at 1000 ms. During the 1-second cohort, the user requested: ‘skip the 3s matchups, i think upto 1s will be enough’. The 18 scheduled 3-second games and four 5-second final games were omitted before either cohort began. The original frozen plan is retained alongside `schedule-amendment.json`; this was a user runtime amendment, not a result-driven automatic extension. Three pairings at each retained control; no extra classical matches, training, relabeling or test-set access. All matches ran sequentially, with no training or intensive benchmarks alongside them.

The three isolated `-O2` C++17 binaries share unchanged search sources/flags, alpha-beta/PVS, move ordering, pruning, 16 MiB hash, one search worker, float32 `scalar` NNUE and incremental accumulators. No pondering. Only embedded architecture/weights differ. The active StockBear installation and classical evaluator remain unchanged.

Twelve established opening main lines were shuffled with seed 20261016; no engine selected or filtered them. All pairings use the same first 12/6 opening pairs at 500/1000 ms, with reversed colors. Pairing order rotates; first-color order alternates across openings. Long-control samples are nested, not independent samples with which to infer a time trend from unmatched totals.

Fresh processes reset game state. Full opening/move history is sent to UCI. Python-chess automatically claims available threefold/50-move draws and enforces checkmate, stalemate, insufficient material, fivefold and 75-move draws. No score-based win/draw adjudication or resignation. A 400-searched-ply cap is unfinished/unscored. The wall deadline is movetime plus 100 ms of protocol/OS allowance; engine and wall thinking times are saved separately.

The original equal-format ranking rule is applied to the two retained controls: the mean of each model's 500 ms and 1000 ms score fractions; tied groups use their equal-format head-to-head mini-league, then fewer parameters. The combined point total below is descriptive and weights the larger 500 ms cohort more heavily; it is not the selection score.

## Engine and network identities

| Model | Dimensions | Engine SHA-256 | Network SHA-256 |
|---|---|---|---|
| StockBear-NNUE-32 | 32/16 | `edd77e4ef6f8bf637302bc5727d38ada5ab169f168dae61597133ae05991c889` | `d7079405932ec934e6a73bc1888da8d745a0b39c4616e6a1bb0b211d20ca48d6` |
| StockBear-NNUE-64 | 64/32 | `ffd785d4e8eecacbf6822d98f4a7b6f43972ea89e20c45d0135227e745eab606` | `a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3` |
| StockBear-NNUE-128 | 128/32 | `1d6ea1153a2aa9a75a967d7d40a61af260c0ca6f12d3b1cd7978cff217fc7fd0` | `782a673dd23018d130883af3c97a5d4126dfcf2b74ac1964aab806d71805433c` |

Sources, flags, network/checkpoint provenance and exact paths are frozen in `plan.json` and the scaling experiment manifest. Actual UCI network identity/dimensions/kernel were checked before each new game, and binary/network/source hashes before every scheduled game and resume. All three passed 38 relevant existing regressions each; six core harness tests verified pairing, scoring, interruption/resume, missing-PGN recovery and unscored failure handling. Two additional amendment tests verified the 108-game boundary, no-op completion, and rejection of changed plans or omitted games. Preflight timed checks covered 500/1000/3000/5000 ms; special rules, terminal positions, incremental/rebuild equivalence, repetition, perft and completed-depth snapshots were verified.

## Combined round-robin scoreboard

| Model | W / D / L | Points / scored games | Raw score | Equal-format score |
|---|---:|---:|---:|---:|
| 128 | 22 / 29 / 21 | 36.5 / 72 | 50.7% | 52.6% |
| 64 | 21 / 31 / 20 | 36.5 / 72 | 50.7% | 49.0% |
| 32 | 20 / 30 / 22 | 35 / 72 | 48.6% | 48.4% |

## Per-format head-to-head results

W/D/L and score refer to the first model. NPS is total nodes divided by engine-reported search seconds, including interrupted deeper-iteration work. It is a time-weighted aggregate, not the isolated inference benchmark. The NPS percentage is second-versus-first. Depth is the deepest completed iteration, not selective depth.

### 0.5 seconds per move

| Pair | W / D / L | Points | Score | NPS first / second | NPS Δ second | Mean depth first / second | Paired 95% bound |
|---|---:|---:|---:|---:|---:|---:|---:|
| 32-64 | 7 / 9 / 8 | 11.5 | 47.9% | 2,921,815 / 1,828,821 | -37.4% | 8.61 / 8.24 | 8.7–87.1% (12 pairs) |
| 32-128 | 8 / 8 / 8 | 12 | 50.0% | 2,927,929 / 1,030,471 | -64.8% | 8.60 / 7.86 | 10.8–89.2% (12 pairs) |
| 64-128 | 8 / 11 / 5 | 13.5 | 56.2% | 1,763,903 / 1,001,639 | -43.2% | 8.25 / 7.79 | 17.0–95.5% (12 pairs) |

Failure events: 0 crashes, 0 timeouts, 0 illegal moves, 0 other infrastructure failures. All saved failure events are unscored and listed separately from chess results.

| Model | W / D / L; score | Mean / median depth | Mean engine / wall move time (s) | Max wall time (s) | Nodes | NNUE calls |
|---|---:|---:|---:|---:|---:|---:|
| 32 | 15 / 17 / 16; 49.0% | 8.60 / 9 | 0.4772 / 0.4789 | 0.5078 | 3,439,020,025 | 2,800,351,851 |
| 64 | 16 / 20 / 12; 54.2% | 8.24 / 8 | 0.4801 / 0.4818 | 0.5064 | 2,207,329,026 | 1,817,295,570 |
| 128 | 13 / 19 / 16; 46.9% | 7.83 / 8 | 0.4800 / 0.4818 | 0.5033 | 1,199,697,492 | 993,301,014 |

### 1 second per move — exploratory

| Pair | W / D / L | Points | Score | NPS first / second | NPS Δ second | Mean depth first / second | Paired 95% bound |
|---|---:|---:|---:|---:|---:|---:|---:|
| 32-64 | 2 / 7 / 3 | 5.5 | 45.8% | 2,992,739 / 1,857,212 | -37.9% | 9.24 / 8.86 | 0.0–100.0% (6 pairs) |
| 32-128 | 3 / 6 / 3 | 6 | 50.0% | 2,995,528 / 1,024,718 | -65.8% | 9.38 / 8.53 | 0.0–100.0% (6 pairs) |
| 64-128 | 2 / 4 / 6 | 4 | 33.3% | 1,859,867 / 1,038,446 | -44.2% | 9.11 / 8.60 | 0.0–88.8% (6 pairs) |

Failure events: 0 crashes, 0 timeouts, 0 illegal moves, 0 other infrastructure failures. All saved failure events are unscored and listed separately from chess results.

| Model | W / D / L; score | Mean / median depth | Mean engine / wall move time (s) | Max wall time (s) | Nodes | NNUE calls |
|---|---:|---:|---:|---:|---:|---:|
| 32 | 5 / 13 / 6; 47.9% | 9.31 / 9 | 0.9689 / 0.9706 | 1.0041 | 3,835,257,918 | 3,114,363,512 |
| 64 | 5 / 11 / 8; 43.8% | 9.00 / 9 | 0.9676 / 0.9693 | 1.0043 | 2,436,907,071 | 1,980,991,784 |
| 128 | 9 / 10 / 5; 58.3% | 8.56 / 8 | 0.9710 / 0.9728 | 1.0230 | 1,486,736,619 | 1,211,642,735 |

## Search-speed cost on matched opening roots

Whole-game NPS/depth can change with the positions an evaluator chooses. To reduce that confounding, the following reuses the first searched move of each game: identical opening FEN/history, same budget, fresh engine. Each model has repeated root samples against both opponents. Ratios are geometric means over matched opening IDs. No additional searches were run.

| Time (ms) | Ratio | Matched roots | NPS ratio | Mean completed-depth difference |
|---|---|---:|---:|---:|
| 500 | 64/32 | 12 | 0.686× | +0.00 |
| 500 | 128/32 | 12 | 0.438× | -0.58 |
| 500 | 128/64 | 12 | 0.639× | -0.58 |
| 1000 | 64/32 | 6 | 0.669× | -0.17 |
| 1000 | 128/32 | 6 | 0.413× | -0.67 |
| 1000 | 128/64 | 6 | 0.618× | -0.50 |

NPS differences measure full search using different evaluators and therefore different trees. Even matched-root figures cannot isolate only the arithmetic cost of inference. Depth is a coarse, selective search measure and is not chess strength by itself. The earlier scaling microbenchmarks remain separate evidence. Existing release counters provide evaluation calls; accumulator-update/full-refresh counters are unavailable and were not inferred or enabled through a heavier diagnostic build.

## Uncertainty and time-control interpretation

Each uncertainty unit is an opening pair with colors together. The table uses the conservative 95% Hoeffding bounded-pair interval. Descriptive 5,000-resample paired-bootstrap intervals are also saved in `analysis.json`; they can be degenerate in tiny or unanimous samples. Neither method eliminates selection bias, dependence between related positions or fixed-suite limitations. The 1-second cohort has only six opening pairs per pairing and is exploratory; close scores do not establish definitive Elo differences. The 108-game endpoint was adopted after intermediate results existed, rather than preregistered as a separate 108-game study. Both retained cohorts were completed in full, and no games were added based on their results.

Cross-control trends compare the shared first six round-robin opening pairs. All per-format results stand separately; there is no pooled Elo estimate or automatic extension based on outcomes.

| Pair (score for first model) | Same first 6 pairs: 500 ms | 1000 ms |
|---|---:|---:|
| 32-64 | 50.0% | 45.8% |
| 32-128 | 58.3% | 50.0% |
| 64-128 | 66.7% | 33.3% |

These matched trend cells contain just twelve games each and remain exploratory. Per-format round-robin score leaders are: 500 ms: 64; 1000 ms: 128.

## Architecture tradeoff

The following scores compare each larger model directly with the next smaller one at equal thinking time. They are observed scores on this suite, with uncertainty as reported above.

| Larger model vs smaller | 500 ms score | 1000 ms score |
|---|---:|---:|
| 64 vs 32 | 52.1% | 54.2% |
| 128 vs 64 | 43.8% | 66.7% |

64/32 scores slightly above 50% against 32/16 at both controls, but those margins are small. 128/32 loses its 500 ms head-to-head against 64/32 (43.75%) and wins the 1-second head-to-head (66.67%). 128/32 and 32/16 score exactly 50% against each other at both controls. Thus the largest network's 1-second lead comes from its matchup against medium, rather than a demonstrated direct gain over compact. Medium and large tie on raw combined points at 36.5/72; the equal-format weighting favors large 52.60% versus 48.96%. This ranking is sensitive to which thinking time matters in deployment.

At 1 second, 128/32 searches 1.03 million nodes/s across its games, versus 1.86 million for 64/32 and 2.99 million for 32/16. Its mean completed depth is 8.56, versus 9.00 and 9.31 respectively. Matched opening roots show 128/32 at 61.8% of medium's NPS and 41.3% of compact's, with depth differences of −0.50 and −0.67 ply. This is a substantial measured search-speed cost and a modest completed-depth loss; neither depth nor the extra teacher accuracy alone establishes chess strength.

The earlier scaling experiment found validation MSE 0.0118161 / 0.0111739 / 0.0108725 for 32/16 / 64/32 / 128/32. The largest model's 7.99% MSE reduction versus compact measures teacher prediction, not Elo. Here its search cost is directly visible in NPS and completed-depth loss. The per-control leaders and matched-opening trend above show whether that prediction improvement translates into equal-time play on this particular suite; they cannot establish the same ordering at untested controls.

These findings apply to the tested scalar float32 builds on this machine. A different inference kernel or processor could change the search-cost tradeoff and would require its own equal-time comparison.

## Failures, adjudications and preservation

Termination counts: `{'checkmate': 63, 'threefold_repetition': 43, 'insufficient_material': 2}`. Saved failure events: **0**. Final replay audit checked **11,645 searched moves**, PGNs, plan identities, legal results and deadlines. **152 protected files** were unchanged. Failures, if any, are recorded individually in `failures/` and are unscored; completed chess results are not silently replaced by infrastructure forfeits. In-progress move checkpoints and all completed games are retained. To apply the user amendment, G099 was interrupted after 43 saved searched moves and resumed from its legal full move history. Its new processes started with cold transient search caches; that single game's restart is a minor fairness limitation. The first resume attempt stalled before engine startup under restricted subprocess access and was stopped without changing moves; the successful resume used the same verified binaries and weights. No completed games were replayed. Elapsed wall time from first game start to last completion: 2.21 hours (includes pauses between runner invocations).

## Artifacts and reproduction

Experiment directory: `Z:\Code\Chess\nnue-showdown-20261016`. `plan.json` freezes every opening FEN/identifier, engine/network hash, search option and game schedule. `games/Gxxx.json` and matching PGNs retain each game and per-move statistics. `schedule-amendment.json` records the shortened scope; `scoreboard.json`, `analysis.json`, `verification.json` and `audit.json` retain progress and validation. Binaries/build logs and runner output are under `artifacts/`.

```powershell
Set-Location Z:\Code\Chess
.\.venv\Scripts\python.exe -m tools.run_nnue_showdown_amended progress
.\.venv\Scripts\python.exe -u -m tools.run_nnue_showdown_amended run
.\.venv\Scripts\python.exe -m tools.report_nnue_showdown
```

Resume validates all frozen identities, skips completed games and continues saved in-progress moves. The amended entry point starts no additional games after G108. Do not use the original unbounded runner, whose retained historical plan still includes the omitted controls. Fresh experiments require a new dedicated output directory. The sealed dataset, original checkpoints, optimized v2/v3 networks and classical StockBear remain intact.
