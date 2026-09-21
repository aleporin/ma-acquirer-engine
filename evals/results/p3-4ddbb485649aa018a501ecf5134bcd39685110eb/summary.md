# p3 evaluation

Evaluated revision: 4ddbb485649aa018a501ecf5134bcd39685110eb
Source dirty: False
Run: 2b4a3895b2db4def97120d99c22ead96 | Mode: replay | Seed: 42
Configuration SHA-256: 6bdc606c0efb6d6b3797fd5e991a3c79875371564cfeceecd86a4df7d6fe9589

| Layer | Name | Selected | Status |
| --- | --- | --- | --- |
| 0 | unit_and_property_tests | True | passed |
| 1 | ranking_backtest | True | passed |
| 2 | groundedness | True | passed |
| 3 | distinctiveness | True | failed |
| 4 | rubric_quality | False | not_implemented |
| 5 | stability | True | failed |
| 6 | operations | True | failed |

| Layer | Metric | Value | Direction |
| --- | --- | --- | --- |
| 0 | coverage | 0.954622 | higher |
| 0 | pass_rate | 1.000000 | higher |
| 0 | tests | 95.000000 | higher |
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
| 2 | fixture_expectation_rate | 1.000000 | higher |
| 2 | live_first_pass_claim_rate | 1.000000 | higher |
| 2 | live_first_pass_page_rate | 0.000000 | higher |
| 2 | live_pages_without_parsed_claims | 2.000000 | lower |
| 2 | live_parsed_claims | 259.000000 | higher |
| 2 | negative_fixtures_rejected | 6.000000 | higher |
| 2 | positive_fixture_claim_verification_rate | 1.000000 | higher |
| 2 | positive_fixtures_accepted | 3.000000 | higher |
| 2 | stray_numbers_detected | 1.000000 | higher |
| 3 | live_page_pairs | 0.000000 | higher |
| 5 | conviction_agreement | 1.000000 | higher |
| 5 | conviction_levels | 1.000000 | higher |
| 5 | live_validation_runs | 1.000000 | higher |
| 5 | top_k_identity | 1.000000 | higher |
| 6 | live_cache_read_tokens | 63552.000000 | higher |
| 6 | live_cache_write_tokens | 2648.000000 | higher |
| 6 | live_cost_usd | 1.065058 | lower |
| 6 | live_financial_sponsor_get_comparable_deals_page_rate | 1.000000 | higher |
| 6 | live_financial_sponsor_get_failed_deals_page_rate | 1.000000 | higher |
| 6 | live_financial_sponsor_get_sector_stats_page_rate | 1.000000 | higher |
| 6 | live_gate_met | 0.000000 | higher |
| 6 | live_input_tokens | 371969.000000 | higher |
| 6 | live_output_tokens | 43419.000000 | higher |
| 6 | live_pages | 10.000000 | higher |
| 6 | live_request_p50_ms | 3770.081208 | lower |
| 6 | live_request_p95_ms | 39489.485334 | lower |
| 6 | live_responses | 25.000000 | higher |
| 6 | live_run_p50_seconds | 158.811208 | lower |
| 6 | live_run_p95_seconds | 158.811208 | lower |
| 6 | live_runs | 1.000000 | higher |
| 6 | live_strategic_get_comparable_deals_page_rate | 1.000000 | higher |
| 6 | live_strategic_get_failed_deals_page_rate | 1.000000 | higher |
| 6 | live_strategic_get_sector_stats_page_rate | 1.000000 | higher |

Unimplemented layers have no quality measurements.
