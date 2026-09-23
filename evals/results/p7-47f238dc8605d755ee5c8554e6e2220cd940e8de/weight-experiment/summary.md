# Exploratory ranking weights

The 2022–2024 benchmark was already inspected during development. These results
are exploratory, not proof of generalization. Production weights are unchanged.

Frozen selection: `sector_anchored_strategics_breadth_tolerant_sponsors`; objective: pooled recall@10, then MRR.
Type-only winner: `sector_anchored_strategics_breadth_tolerant_sponsors`; buyer-adjusted: `buyer:shared`.
Benchmark: 142 queries, 17 queries with unseen buyer labels.

| Method | Recall@10 | MRR | nDCG@10 |
|---|---:|---:|---:|
| global_popularity | 40.85% | 0.1264 | 0.1761 |
| sector_popularity | 43.66% | 0.1366 | 0.1819 |
| random | 12.68% | 0.0670 | 0.0667 |
| shared | 38.03% | 0.1711 | 0.1973 |
| buyer:shared | 38.73% | 0.1679 | 0.1968 |
| sector_anchored_strategics_breadth_tolerant_sponsors | 40.85% | 0.1811 | 0.2116 |

Selected minus baseline, paired 95% bootstrap interval for recall@10:

- shared: +2.82 percentage points [-2.11, +7.75]
- global_popularity: +0.00 percentage points [-11.97, +10.58]
- sector_popularity: -2.82 percentage points [-11.97, +5.63]
- random: +28.17 percentage points [+19.01, +37.32]

Intervals resample transactions and do not adjust for repeated buyers or
development/search decisions. Observed purchases do not establish mandates.
