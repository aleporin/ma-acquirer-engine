# p1 evaluation

Evaluated revision: 675f60ac7c8dc2f6a41d8d83233cf0cb2ca7ade3
Source dirty: False
Run: 76d7a909925f4b65b27a4492a8afbadc | Mode: replay | Seed: 42
Configuration SHA-256: dcc5dbdc4347f9c49192301f9281a96c5047d70824953cd5308d00d60789cf12

| Layer | Name | Selected | Status |
| --- | --- | --- | --- |
| 0 | unit_and_property_tests | True | passed |
| 1 | ranking_backtest | True | passed |
| 2 | groundedness | True | not_implemented |
| 3 | distinctiveness | True | not_implemented |
| 4 | rubric_quality | False | not_implemented |
| 5 | stability | True | failed |
| 6 | operations | True | not_implemented |

| Layer | Metric | Value | Direction |
| --- | --- | --- | --- |
| 0 | coverage | 0.968668 | higher |
| 0 | pass_rate | 1.000000 | higher |
| 0 | tests | 33.000000 | higher |
| 1 | global_popularity_mrr | 0.126381 | higher |
| 1 | global_popularity_ndcg_at_k | 0.176085 | higher |
| 1 | global_popularity_recall_at_k | 0.408451 | higher |
| 1 | lift_vs_global_popularity_mrr_high | 0.091685 | higher |
| 1 | lift_vs_global_popularity_mrr_low | -0.004937 | higher |
| 1 | lift_vs_global_popularity_mrr_mean | 0.044708 | higher |
| 1 | lift_vs_global_popularity_ndcg_at_k_high | 0.082837 | higher |
| 1 | lift_vs_global_popularity_ndcg_at_k_low | -0.044530 | higher |
| 1 | lift_vs_global_popularity_ndcg_at_k_mean | 0.021223 | higher |
| 1 | lift_vs_global_popularity_recall_at_k_high | 0.084507 | higher |
| 1 | lift_vs_global_popularity_recall_at_k_low | -0.147887 | higher |
| 1 | lift_vs_global_popularity_recall_at_k_mean | -0.028169 | higher |
| 1 | lift_vs_random_mrr_high | 0.154282 | higher |
| 1 | lift_vs_random_mrr_low | 0.055661 | higher |
| 1 | lift_vs_random_mrr_mean | 0.104082 | higher |
| 1 | lift_vs_random_ndcg_at_k_high | 0.187673 | higher |
| 1 | lift_vs_random_ndcg_at_k_low | 0.073213 | higher |
| 1 | lift_vs_random_ndcg_at_k_mean | 0.130583 | higher |
| 1 | lift_vs_random_recall_at_k_high | 0.345070 | higher |
| 1 | lift_vs_random_recall_at_k_low | 0.161972 | higher |
| 1 | lift_vs_random_recall_at_k_mean | 0.253521 | higher |
| 1 | lift_vs_sector_popularity_mrr_high | 0.069922 | higher |
| 1 | lift_vs_sector_popularity_mrr_low | -0.000786 | higher |
| 1 | lift_vs_sector_popularity_mrr_mean | 0.034472 | higher |
| 1 | lift_vs_sector_popularity_ndcg_at_k_high | 0.056517 | higher |
| 1 | lift_vs_sector_popularity_ndcg_at_k_low | -0.025536 | higher |
| 1 | lift_vs_sector_popularity_ndcg_at_k_mean | 0.015381 | higher |
| 1 | lift_vs_sector_popularity_recall_at_k_high | 0.028169 | higher |
| 1 | lift_vs_sector_popularity_recall_at_k_low | -0.140845 | higher |
| 1 | lift_vs_sector_popularity_recall_at_k_mean | -0.056338 | higher |
| 1 | random_mrr | 0.067007 | higher |
| 1 | random_ndcg_at_k | 0.066724 | higher |
| 1 | random_recall_at_k | 0.126761 | higher |
| 1 | ranker_mrr | 0.171089 | higher |
| 1 | ranker_ndcg_at_k | 0.197307 | higher |
| 1 | ranker_recall_at_k | 0.380282 | higher |
| 1 | sector_popularity_mrr | 0.136617 | higher |
| 1 | sector_popularity_ndcg_at_k | 0.181927 | higher |
| 1 | sector_popularity_recall_at_k | 0.436620 | higher |
| 5 | conviction_agreement | 1.000000 | higher |
| 5 | conviction_levels | 1.000000 | higher |
| 5 | top_k_identity | 1.000000 | higher |

Unimplemented layers have no quality measurements.
