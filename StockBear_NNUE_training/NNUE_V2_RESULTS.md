# StockBear NNUE v2 results

**Selected model: small (64/32,
54,209 parameters).** All phases completed: 67 archives inventoried,
1,250,000 positions labeled, 12 controlled full experiments,
and two seeds for each finalist. The selected run used
999,464 training positions.

## Findings

- **More data:** compact validation teacher MSE improved from
  0.013894 (200K nominal pool) to 0.011399 (1M).
  All sizes used the same holdout and settings; larger datasets also processed more examples.
- **More capacity:** small led the common 500K comparison.
  Medium and large had lower training loss but worse validation error than the smaller finalists.
- **Generalization:** the winner was selected by the mean validation blended loss of
  two seeds, after two bounded settings per finalist. Epochs and tuning never used test scores.
- **Improvement over v1:** final test teacher MSE **0.011128**
  versus **0.019199**, measured on the same
  20,152 positions (42.0% lower). Material baseline: 0.019193.
  Historical v1 MSE 0.016341 used a different, quieter cohort and is not the direct comparator.
- **Score error:** clipped cp MAE **143.53**, RMSE
  239.55, clipped Pearson 0.7748,
  decisive sign accuracy 89.61%.
- **Extra size:** selected export 2.07× compact's bytes and 3.97×
  its theoretical dense-head MACs. Whether this pays off in search requires native latency
  and playing tests. Benchmark the validated compact and small finalists next.

Small's two-seed mean validation blended loss was 0.75% lower than compact's. The primary checkpoints' test teacher MSEs were 0.011128 and 0.011022, respectively; cp MAEs were 143.53 and 143.93. The saved validation selection remains unchanged. The small differences support retaining both finalists rather than claiming a decisive architecture advantage.

## Finalists

| Architecture | Two-seed val blended MSE | Test teacher MSE | Test cp MAE | Correlation | Export bytes |
|---|---:|---:|---:|---:|---:|
| small | 0.013153 | 0.011128 | 143.53 | 0.7748 | 218,029 |
| compact | 0.013253 | 0.011022 | 143.93 | 0.7739 | 105,518 |

## Controlled experiment ranking

Rows rank individual runs by validation blended loss; the final architecture choice
uses two-seed means. The gap is validation minus training blended MSE.

| Rank | Experiment | Nominal pool | Parameters | Epochs / selected | Val blended MSE | Val teacher MSE | Gap | Examples |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | final_small_1250000_base | 1,250,000 | 54,209 | 33 / 25 | 0.013093 | 0.011212 | 0.002740 | 32,982,312 |
| 2 | final_small_1250000_regularized | 1,250,000 | 54,209 | 40 / 32 | 0.013178 | 0.011297 | 0.002392 | 39,978,560 |
| 3 | final_compact_1250000_base | 1,250,000 | 26,081 | 41 / 33 | 0.013182 | 0.011230 | 0.001464 | 40,978,024 |
| 4 | final_small_1250000_base_seed2 | 1,250,000 | 54,209 | 28 / 20 | 0.013214 | 0.011296 | 0.002762 | 27,984,992 |
| 5 | final_compact_1250000_base_seed2 | 1,250,000 | 26,081 | 48 / 40 | 0.013325 | 0.011389 | 0.001579 | 47,974,272 |
| 6 | final_compact_1250000_regularized | 1,250,000 | 26,081 | 51 / 43 | 0.013331 | 0.011378 | 0.001146 | 50,972,664 |
| 7 | scale_compact_1000000 | 1,000,000 | 26,081 | 51 / 43 | 0.013368 | 0.011399 | 0.002203 | 40,778,121 |
| 8 | arch_small_500000 | 500,000 | 54,209 | 23 / 15 | 0.014034 | 0.011927 | 0.003602 | 9,195,009 |
| 9 | scale_compact_500000 | 500,000 | 26,081 | 38 / 30 | 0.014153 | 0.012113 | 0.003175 | 15,191,754 |
| 10 | arch_medium_500000 | 500,000 | 108,353 | 21 / 13 | 0.014648 | 0.012666 | 0.005806 | 8,395,443 |
| 11 | arch_large_500000 | 500,000 | 233,089 | 17 / 9 | 0.014771 | 0.012787 | 0.005975 | 6,796,311 |
| 12 | scale_compact_200000 | 200,000 | 26,081 | 25 / 17 | 0.016177 | 0.013894 | 0.004063 | 3,997,950 |

## Data quality, verification and limits

The common pool contains 1,484,808 legal unique positions from
121,352 game groups; nested prefixes share fixed validation/test cohorts.
Exact duplicates and game aliases share partitions, and v1 training FENs are excluded
from v2 holdouts. Captures, checks and promotions are retained. Tactical tags and
source metadata hints are heuristics. Embedded PGN evaluations are not teacher targets.

Teacher: unchanged Stockfish 19, 16,384 nodes, 6 one-thread workers.
The 65,536-node check on 384 representatives changed clipped scores by
31.20 cp on average, with
2 mate-status changes. Higher-budget labels are not perfect ground truth.
The target, two-perspective 780 features, clipped ReLU and float32 export contract remain unchanged.

**Tests: 30 passed, 0 failures, 0 errors,
0 skips.** Recovery, cache compatibility and all four widths were checked.
Each candidate passed 128-FEN NumPy/PyTorch/device parity within 0.01 cp, checksum/shape
checks and read-only native format parsing. v1 exports/checkpoints were verified unchanged.
No C++ engine, GUI, default evaluator or native weights were modified.
These results measure teacher prediction, not playing strength.

Paired game-bootstrap 95% interval for selected v2 minus v1 test MSE:
[-0.008490, -0.007614]. Negative favors v2; residual overfitting is visible in the curves.

## Files and reproduction

- Best export: `exports/v2/stockbear-v2-best.sbnnue`; independent compact/small/medium/large
  candidates and golden FENs are beside it. Selected checkpoints remain in `runs/v2/`.
- [Full experiment report](NNUE_V2_EXPERIMENT_REPORT.md), [comparison CSV](reports/v2/comparison.csv),
  [dataset manifests](reports/v2/dataset_manifests.json), [selection](reports/v2/selection.json).
- The original project retains shared labeled SQLite data and prepared arrays in `data/v2/`.
  Reproduce/resume with `.\.venv\Scripts\python.exe -m stockbear.v2 run`; test with
  `.\.venv\Scripts\python.exe -m pytest`. Configuration: `configs/v2/plan.json`.

![Scaling comparisons](reports/v2/plots/scaling_comparison.png)

![Learning curves](reports/v2/plots/learning_curves.png)

![Test error distributions](reports/v2/plots/test_errors.png)
