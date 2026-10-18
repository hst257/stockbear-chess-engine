# StockBear Grand Final — NNUE Hiddenclip versus Classical

## Executive summary

**Selected configuration: CLASSICAL, Rule C.** Inconclusive result; retain the preserved classical baseline conservatively. This does not prove higher classical Elo. Exactly 80 official games at 500 ms, 40 reversed opening pairs. NNUE score **50.62%**, paired 95% **[41.88%, 59.38%]**. No deployment or default change.

## Exact engine identities and provenance

| Engine | Executable | SHA256 | Evaluator |
| --- | --- | --- | --- |
| CLASSICAL | Z:\Code\Chess\final-nnue-showdown-20261017\artifacts\engines\classical\StockBear-classical.exe | ffd785d4e8eecacbf6822d98f4a7b6f43972ea89e20c45d0135227e745eab606 | classical |
| NNUE_HIDDENCLIP | Z:\Code\Chess\nnue-optimization-stage3-20261017\artifacts\hiddenclip\engine.exe | 68ced7162b20109b6ad9e705bbb4f43317c85d2cb5d10ff3ae45a02eb0bd571b | nnue |

The classical EXE is the exact archived prior final-showdown baseline, matching its original 64/32 source binary and build receipt. Its embedded NNUE is unused: every classical search must have zero NNUE evaluations. All search sources/headers, classical evaluator, rules and build flags match. Only the NNUE head implementation and clip UCI selector differ; see provenance.json. No rebuild. Hiddenclip is the exact Tournament 1 finalist, clip kernel, incremental float32, 780 features→dual64→32→1. Checkpoint SHA256 `7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`; export `a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3`.

## Setup, frozen openings and preflight

Tournament 1 opening-suite.json was copied byte-for-byte: SHA256 `ac396f24d9e6f7f7c01a6afdb1dc96f5a28500ba77ac3b873abb972a55fa1903`. All 40 IDs, full legal startpos histories, FENs and moves are unchanged. The 80 assignments preserve its balanced order with CLASSICAL replacing Stage 1; each competitor plays 40 games as White and 40 as Black. Seed 2026101780. No outcome-dependent selection, extension or pooling.

Both use `go movetime 500`,16 MiB hash, one search thread, no pondering, verified CPU0 affinity; equal search switches. Classical uses Evaluator=classical and supported scalar selector (NNUE unused); challenger uses the exact Tournament 1 options Evaluator=nnue, NNUEKernel=clip. Fresh processes/TT each game, retained within game; full history every play. Preflight covers exact hashes/model, legal histories, evaluator counters, clocks, UCI resets, mate/draw rules, PGNs, atomic checkpoints and genuine interrupted/resumed smoke. All smoke results are excluded. Standalone launcher guards duplicate writers and reconstructs partial games without replaying saved moves.

python-chess is authoritative, including claimable repetition/50-move draws and terminal/material rules. No evaluation adjudication; 400 searched plies beyond opening is a separately identified safeguard draw. Crashes, illegal moves, protocol failures/timeouts halt unscored with checkpoints and full logs, symmetric for both engines.

## Complete results

| Engine | Wins | Draws | Losses | Points /80 | Score% |
| --- | --- | --- | --- | --- | --- |
| CLASSICAL | 24 | 31 | 25 | 39.5 | 49.38 |
| NNUE_HIDDENCLIP | 25 | 31 | 24 | 40.5 | 50.62 |

| Engine /color | Games | W/D/L | Points | Score% |
| --- | --- | --- | --- | --- |
| CLASSICAL / white | 40 | 15/16/9 | 23.0 | 57.50 |
| CLASSICAL / black | 40 | 9/15/16 | 16.5 | 41.25 |
| NNUE_HIDDENCLIP / white | 40 | 16/15/9 | 23.5 | 58.75 |
| NNUE_HIDDENCLIP / black | 40 | 9/16/15 | 17.0 | 42.50 |

Average game length: 109.54 total plies (98.89 searched); safeguard draws 0; official partial resumptions 1. Full 80 rows: games.csv and games.pgn.

## Paired uncertainty and Elo-equivalent

Frozen Tournament 1 method: 50,000 bootstrap resamples of 40 complete color-reversed opening pairs, seed 2026101780. NNUE score 50.62% [95% 41.88%,59.38%]; classical 49.38% [95% 40.62%,58.13%]. NNUE-minus-classical Elo-equivalent **+4.3 [95% -57.0,+65.9]**. Formula -400*log10(1/p-1); boundary scores yield infinities. Convincing superiority: **False** (the interval contains 50%). Opening-family cluster sensitivity NNUE 95% [41.67%,58.75%]. This conditional bootstrap is neither an absolute rating nor a guarantee across all chess; family dependence and selected suite remain limitations.

## Search performance

| Engine | Mean /median depth | Median nodes | Median NPS | Median wall NPS | Median wall /reported ms | Median CPU ms |
| --- | --- | --- | --- | --- | --- | --- |
| CLASSICAL | 8.221 /8.0 | 944256.0 | 1908430 | 1895230 | 502.413 /500.000 | 421.875 |
| NNUE_HIDDENCLIP | 7.934 /8 | 868352 | 1755648 | 1745860 | 502.407 /500.000 | 421.875 |

Tournament medians describe different reached positions and search trees; they are not a matched-work inference benchmark or proof of causation. NPS is not chess strength. First searched moves in each opening pair do share identical opening histories and fresh state; root comparisons in analysis.json are exploratory throughput descriptions under different evaluators.

## Timing, reliability and environment

Each search requests 500 ms, symmetric 200 ms OS/protocol allowance; 700 ms hard ceiling. Flags at>550 ms wall or>525 ms reported. Hard-policy pass True; abnormal flags 2/7911 (0.025%, frozen 1% acceptance limit). Engine/game failures 0. Full per-move logs/counters/PVs, CPU time, wall time and background deltas retained. Protocol-delay proxy is max(0, wall-reported), not a separately measured transport latency.

| Engine | Max wall ms | Max reported ms | Warnings |
| --- | --- | --- | --- |
| CLASSICAL | 541.312 | 517.000 | 0 |
| NNUE_HIDDENCLIP | 563.908 | 524.000 | 2 |

| Game /searched ply | Engine | Wall ms | Reported ms |
| --- | --- | --- | --- |
| G030 /95 | NNUE_HIDDENCLIP | 563.908 | 500.000 |
| G033 /52 | NNUE_HIDDENCLIP | 553.155 | 500.000 |

AC and the unchanged Windows power plan were checked before/after each game. CPU0 verified per search; no priority, NitroSense, power, security or unrelated-app settings changed. Quiet/Eco is last user-confirmed and not independently measurable here. CPU accounting is quantized (historically 15.625 ms); system/background deltas do not measure CPU0 contention. Effective frequency, temperature and thermal throttling unavailable; no inferred thermal cause.

## Historical context and final selection

Tournament 1 compared two implementations of the same model: Hiddenclip 32 wins, Stage 1 28 wins, 20 draws,52.50%,+17.4 Elo-equivalent, statistically inconclusive; hiddenclip advanced under its engineering Rule B. This tournament compares learned against handcrafted evaluation. Neither tournament is pooled. The older 48-game, 1-second study used unoptimized scalar NNUE and a different suite: classical 13/24 against 64/32 and 17.5/24 against 128/32; it is historical context only. Stage 1 was accepted as isolated inference optimization; Stage 3.1 showed positive throughput with formal environmental inconclusiveness. Those speed findings do not predetermine this match.

**Rule C: CLASSICAL.** Inconclusive result; retain the preserved classical baseline conservatively. This does not prove higher classical Elo. This is a handoff for later explicitly authorized consolidation; no production promotion.

## Answers and interpretation

1. NNUE defeated classical on observed score: True; statistically convincing NNUE win: False.
2. W/D/L NNUE 25/31/24; classical 24/31/25.
3. Score NNUE 50.62%, classical 49.38%.
4. Statistically convincing: False; use the paired interval above.
5. NNUE-minus-classical estimated Elo-equivalent +4.3, uncertainty above.
6. Mean completed depth NNUE 7.934, classical 8.221.
7. Median NPS NNUE 1,755,648, classical 1,908,430; descriptive different-tree workloads.
8. Engine failures 0; every scored move and PV legally replayed.
9. Symmetric 500 ms requests and 700 ms ceiling; hard-policy pass True.
10. Selected final configuration CLASSICAL, Rule C; not deployed.
11. Limits: 80 games, 40 fixed pairs, one laptop, one time budget, related openings and environmental uncertainty; small Elo effects unresolved.
12. This NNUE has not demonstrated the required convincing improvement; speed optimization alone is insufficient evidence to replace classical. This does not establish that NNUE approaches cannot improve StockBear.

## Integrity and reproduction

Exactly 80 unique scheduled games, 40 reversed pairs, 40 White/40 Black each; all PGNs legal and results matched. 1687 protected files unchanged. No training, labeling, source/model/default change, cleanup or deployment occurred. See final-audit.json for independently checked exports and manifest.json for checksums. README.md gives start/status/resume/analyze commands; all original studies and raw records retained. No extra games or optimization follow.

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


## Planned pause and manual continuation

The user requested a pause when 65 games were complete, allowing exactly two more. Games 66 and 67 finished before the runner stopped; game 68 had zero searched moves. The remaining 13 games resumed manually on October 18 after the scheduling request returned a setup card without confirmed activation. All 67 completed game records, PGNs, partial snapshots and protocol logs match the pre-pause checksums byte-for-byte. No completed game was replayed. G068 records one reconstruction with fresh engines, but no within-game searches or warm caches were discarded at the boundary. The KeyboardInterrupt in the first runner error log is the expected requested pause, not an engine failure. Separate sessions introduce possible environmental drift despite unchanged AC/power-plan/affinity policy. No thermal cause is inferred. pause-manifest.json is the historical 67-game snapshot; manifest.json is the completed delivery manifest.

## Matched opening-root search diagnostic

Across the same 40 opening histories, NNUE/classical wall-NPS geometric mean was 1.0048; NNUE-minus-classical mean completed depth was +0.150 plies. Both searched for the same nominal 500 ms with fresh state. Different evaluators explore different trees, so this exploratory root comparison is not an isolated inference-cost measurement.
