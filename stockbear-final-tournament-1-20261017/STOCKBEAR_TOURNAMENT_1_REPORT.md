# StockBear Tournament 1 — NNUE Stage 1 versus Hiddenclip

## Executive result

**Practical finalist: NNUE_HIDDENCLIP. Rule B.** Inconclusive score; predeclared engineering tiebreak for supported throughput with identical evaluation outputs; not proven higher Elo.

Completed exactly **80 games at 500 ms/move**, 40 opening pairs, reversed colors. Hiddenclip score: **52.50%**, paired-opening 95% interval **[45.62%, 59.38%]**. Statistically convincing: **False**. No Tournament 2, deployment, training, labeling, engine edits or cleanup occurred.

## Engine and model identities

| Competitor | EXE SHA256 | Kernel |
| --- | --- | --- |
| NNUE_STAGE1 | e64146bf7ccf219d3254d258615408e4b782c4aa7b430c9140beb73228055d4d | clip |
| NNUE_HIDDENCLIP | 68ced7162b20109b6ad9e705bbb4f43317c85d2cb5d10ff3ae45a02eb0bd571b | clip |

Both exact preserved EXEs embed the same 780-feature dual-64/32 model. Checkpoint SHA256 `7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`; export `a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3`. Original build manifests, identical generated headers, and source comparison establish only `stage1_head.hpp` differs. Live UCI evaluation probes verify evaluator, model, width, hidden and clip kernel. See `provenance.json`, `binary-identities.json`, `preflight.json`. No rebuild occurred.

## Frozen design and preflight

`opening-suite.json`, `schedule.json`, `tournament-config.json` were frozen before official games, seed 2026101780. Established main lines reuse 24 prior verified sequences plus 16 independently specified named sequences. No evaluator/outcome selection. Both get full starting-position history, identical switches, 16 MiB hash, one thread, CPU0, no pondering. Fresh processes/TT per game; TT retained within game. Pairs alternate which implementation is White first. Both play 40 games as White and 40 as Black.

Preflight verified identities, UCI/readiness, explicit `go movetime 500`, legal PV/moves, fixed-node parity, all 40 histories, draw/checkmate rules, color reversal, PGN parsing and atomic checkpoint reconstruction. Two bounded near-mate smoke games were excluded. A third bounded harness game deliberately stopped after two real searches, resumed without replaying them, and ended at a four-search smoke-only safeguard; it is also excluded. All three smoke games remain under `smoke/`, outside official results. New-game initialization and `game` tokens reset TT; partial resumes reconstruct all saved moves and reset both processes, with restarts recorded.

Rules use python-chess including claimable threefold/50-move draws. No evaluation-based adjudication. At 400 searched plies beyond the book, a safeguard draw is explicitly adjudicated and counted separately. Crashes, illegal moves, protocol failures/timeouts halt unscored with full logs; saved completed games are never replayed.

## Results

| Engine | Wins | Draws | Losses | Points /80 | Score% |
| --- | --- | --- | --- | --- | --- |
| NNUE_STAGE1 | 28 | 20 | 32 | 38.0 | 47.50 |
| NNUE_HIDDENCLIP | 32 | 20 | 28 | 42.0 | 52.50 |

| Engine / color | Games | W/D/L | Points | Score% |
| --- | --- | --- | --- | --- |
| NNUE_STAGE1 / white | 40 | 14/8/18 | 18.0 | 45.00 |
| NNUE_STAGE1 / black | 40 | 14/12/14 | 20.0 | 50.00 |
| NNUE_HIDDENCLIP / white | 40 | 14/12/14 | 20.0 | 50.00 |
| NNUE_HIDDENCLIP / black | 40 | 18/8/14 | 22.0 | 55.00 |

Average searched length 114.47 plies; including opening 125.12. Maximum-ply adjudications: 0. Resumed partial-game sessions: 0.

## Opening-pair uncertainty and Elo-equivalent

Bootstrap 40 complete color-reversed opening units, 50,000 draws. Hiddenclip minus Stage 1 Elo-equivalent point **+17.4**, 95% interval **[-30.5, +65.9]**. Formula: `-400 * log10(1/p - 1)`. This transforms the observed score; it is neither an absolute rating nor a precise universal Elo difference. Stage 1 score 95% is [40.62%, 54.37%]. If the score interval contains 50%, superiority is not established. Family-cluster sensitivity score 95%: [44.64%, 60.00%]; this secondary check recognizes related opening families and does not pool historical games.

## Search performance and timing

| Engine | Median nodes | Median reported NPS | Median wall NPS | Median depth | Median wall /engine seconds | Median CPU seconds |
| --- | --- | --- | --- | --- | --- | --- |
| NNUE_STAGE1 | 1132416.0 | 2284484 | 2273903 | 8.0 | 0.501981 /0.500000 | 0.453125 |
| NNUE_HIDDENCLIP | 1228928.0 | 2475776 | 2463859 | 8.0 | 0.501978 /0.500000 | 0.453125 |

These are descriptive medians on each engine's actual tournament positions. Different games/moves reach different positions and depths; these unpaired search samples do not constitute a matched-position causal NPS/depth benchmark. The previous exact-work studies supply the controlled throughput evidence. Higher NPS does not guarantee higher playing strength.

Nominal 500 ms each, symmetric 200 ms protocol/OS tolerance: hard ceiling 700 ms; flags above 550 ms wall or 525 ms reported. Abnormal delays 1/9158 (0.011%). Hard timing policy passed: True. Engineering-tiebreak delay limit 1%.

| Engine | Maximum wall | Maximum reported | Abnormal flags |
| --- | --- | --- | --- |
| NNUE_STAGE1 | 0.539521 | 0.521000 | 0 |
| NNUE_HIDDENCLIP | 0.537941 | 0.532000 | 1 |

Flagged searches were retained:

| Game / searched ply | Engine | Reported ms | Wall ms | CPU ms |
| --- | --- | --- | --- | --- |
| G009 / 48 | NNUE_HIDDENCLIP | 532.0 | 534.8 | 421.9 |

The warning is within the frozen tolerance. Both engines received `go movetime 500`; CPU accounting is quantized and does not establish why the stop check/report was late. No cause or extra usable thinking-time advantage is inferred.

Game/engine failures recorded: **0**. Full engine transcripts live under `logs/`, game failures under `failures/` if present; complete per-move CPU/wall/time/nodes/depth/score/PV/counters/background activity is in game JSON and moves CSV. Minor protocol overhead is not additional nominal thinking time.

A report-module import collision occurred **after all 80 official games finished**: a transitive Python path change selected the earlier Stage 3 `analyze` module. Reporting was repaired to invoke this workspace's script by its explicit path. `provenance/executed-tournament.py` preserves the exact frozen runner used for the games; `harness-recovery.json` records original/repaired hashes. The repair changed only postprocessing dispatch/completed-run handling. No game, engine, model, opening, clock, statistical estimator or selection rule changed, and no game was replayed. This resolved harness issue is separate from engine stability.

## Environment and integrity

AC and unchanged Windows power plan were checked before/after every game. All searches use inherited CPU0 affinity, verified per move. No priority, power, NitroSense, security or unrelated-app changes. Quiet/Eco is last user-confirmed, not independently measured. Process CPU accounting and system/background deltas are diagnostic, can be quantized, and do not measure actual frequency/temperature/throttling. Games ran serially without concurrent heavy experiments.

All **1230 protected files unchanged**. Exactly 80 unique scheduled game IDs,40 reversed opening pairs, 40 White/40 Black each, full legal replay and parseable individual/aggregate PGNs were checked. No original executable, model, production source or earlier study changed; no cleanup or Tournament 2 occurred.

## Explicit conclusions and handoff

1. **Higher score:** NNUE_HIDDENCLIP; hiddenclip 42.0/80 versus Stage 1 38.0/80.
2. **Win/draw/loss totals:** hiddenclip 32/20/28; Stage 1 28/20/32.
3. **Score percentages:** hiddenclip 52.50%; Stage 1 47.50%.
4. **Statistically convincing:** False; paired-opening score 95% [45.62%, 59.38%].
5. **Nodes at equal nominal time:** hiddenclip median 1,228,928, Stage 1 1,132,416, a descriptive difference of 8.52%. Positions differ; this is not a matched-position effect estimate.
6. **Completed depth:** median 8.0/8.0 for Stage 1/hiddenclip; means 8.409/8.466. No higher median depth is demonstrated.
7. **Timing/stability:** 0 game/engine failures, 1 minor delay warning(s), hard-policy pass True.
8. **Playing-strength gain:** not established; throughput improvement is separate evidence.
9. **Advance:** NNUE_HIDDENCLIP, rule B.
10. **Confidence:** the practical engineering tiebreak is supported; higher Elo is unproven. A fixed 80-game suite cannot establish a precise universal strength difference.

`TOURNAMENT_1_FINALIST.json` records the exact path, hash, model, options, search settings, results, selection rule and concerns. Stage 3.1's throughput estimates were positive but its formal acceptance remained inconclusive because of background-load flags; this tournament's explicit user-authorized tiebreak is distinct from promoting an inference benchmark or a production evaluator. Run Tournament 2 only under a separate instruction.

## Frozen opening suite

| ID | Description | SAN |
| --- | --- | --- |
| O01 | King's Gambit Accepted | e4 e5 f4 exf4 Nf3 g5 h4 g4 Ne5 Nf6 |
| O02 | Sicilian Closed | e4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 d3 d6 |
| O03 | Sicilian Dragon | e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6 Be3 Bg7 |
| O04 | French Advance | e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3 Qb6 a3 Bd7 |
| O05 | Caro-Kann Advance | e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 c5 O-O Nc6 |
| O06 | Philidor | e4 e5 Nf3 d6 d4 Nf6 Nc3 Nbd7 Bc4 Be7 O-O O-O |
| O07 | Reti | Nf3 d5 g3 Nf6 Bg2 e6 O-O Be7 c4 O-O b3 c5 |
| O08 | Grunfeld Exchange | d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5 e4 Nxc3 bxc3 Bg7 |
| O09 | Queen's Gambit Accepted | d4 d5 c4 dxc4 Nf3 Nf6 e3 e6 Bxc4 c5 O-O a6 |
| O10 | London | d4 d5 Nf3 Nf6 Bf4 e6 e3 Bd6 Bg3 O-O Bd3 c5 |
| O11 | Sicilian Sveshnikov | e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5 Ndb5 d6 |
| O12 | Benoni | d4 Nf6 c4 c5 d5 e6 Nc3 exd5 cxd5 d6 e4 g6 |
| O13 | Dutch | d4 f5 g3 Nf6 Bg2 g6 Nf3 Bg7 O-O O-O |
| O14 | Slav | d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 a4 Bf5 |
| O15 | Alekhine | e4 Nf6 e5 Nd5 d4 d6 Nf3 Bg4 Be2 e6 |
| O16 | Queen's Indian | d4 Nf6 c4 e6 Nf3 b6 g3 Bb7 Bg2 Be7 O-O O-O |
| O17 | Caro-Kann | e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 |
| O18 | Nimzo-Indian | d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O Bd3 d5 |
| O19 | King's Indian | d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O |
| O20 | Italian | e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 |
| O21 | Petroff | e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4 d4 d5 Bd3 Be7 O-O Nc6 |
| O22 | Scotch | e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Bc5 Be3 Qf6 |
| O23 | Ruy Lopez | e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 |
| O24 | Scandinavian Modern | e4 d5 exd5 Nf6 d4 Nxd5 c4 Nb6 Nf3 g6 |
| O25 | Vienna | e4 e5 Nc3 Nf6 Bc4 Nc6 d3 Bc5 Nf3 d6 |
| O26 | French | e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7 |
| O27 | Pirc | e4 d6 d4 Nf6 Nc3 g6 Be3 Bg7 Qd2 c6 f3 b5 |
| O28 | Bird | f4 d5 Nf3 g6 e3 Bg7 Be2 Nf6 O-O O-O |
| O29 | Four Knights | e4 e5 Nf3 Nc6 Nc3 Nf6 Bb5 Bb4 O-O O-O |
| O30 | Sicilian Najdorf | e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 |
| O31 | Queen's Gambit Declined | d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 |
| O32 | Benko | d4 Nf6 c4 c5 d5 b5 cxb5 a6 bxa6 Bxa6 Nc3 d6 |
| O33 | Trompowsky | d4 Nf6 Bg5 Ne4 Bf4 d5 e3 c5 Bd3 Nf6 |
| O34 | Scandinavian | e4 d5 exd5 Qxd5 Nc3 Qa5 d4 c6 Nf3 Nf6 Bc4 Bf5 |
| O35 | English Symmetrical | c4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 Nf3 Nf6 |
| O36 | Modern | e4 g6 d4 Bg7 Nc3 d6 f4 a6 Nf3 b5 |
| O37 | Sicilian Alapin | e4 c5 c3 Nf6 e5 Nd5 d4 cxd4 Nf3 Nc6 cxd4 d6 |
| O38 | Bogo-Indian | d4 Nf6 c4 e6 Nf3 Bb4+ Bd2 Bxd2+ Qxd2 d5 Nc3 O-O |
| O39 | Catalan | d4 Nf6 c4 e6 g3 d5 Bg2 Be7 Nf3 O-O |
| O40 | English | c4 e5 Nc3 Nf6 g3 d5 cxd5 Nxd5 Bg2 Nb6 |

## Reproduction

See `README.md`: standalone start/status/resume commands. JSON game records are authoritative, PGNs/CSVs are validated derived exports; completed records are skipped. `manifest.json` preserves receipt hashes. No further games are scheduled.
