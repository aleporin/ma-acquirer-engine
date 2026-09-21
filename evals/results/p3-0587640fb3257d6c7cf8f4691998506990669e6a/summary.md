# p3 evaluation

Evaluated revision: 0587640fb3257d6c7cf8f4691998506990669e6a
Source dirty: False
Run: c74c8d6e0905421585de4605fd042c52 | Mode: replay | Seed: 42
Configuration SHA-256: e720eeb1409d4611de199ee30aaf6f6d0c4ce6a3d59be073b2c06efc1a388c87

| Layer | Name | Selected | Status |
| --- | --- | --- | --- |
| 0 | unit_and_property_tests | True | passed |
| 1 | ranking_backtest | True | passed |
| 2 | groundedness | True | passed |
| 3 | distinctiveness | True | passed |
| 4 | rubric_quality | False | not_implemented |
| 5 | stability | True | failed |
| 6 | operations | True | passed |

| Layer | Metric | Value | Direction |
| --- | --- | --- | --- |
| 0 | coverage | 0.953590 | higher |
| 0 | pass_rate | 1.000000 | higher |
| 0 | tests | 131.000000 | higher |
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
| 2 | negative_fixtures_rejected | 6.000000 | higher |
| 2 | positive_fixture_claim_verification_rate | 1.000000 | higher |
| 2 | positive_fixtures_accepted | 3.000000 | higher |
| 2 | replay_first_pass_claim_rate | 1.000000 | higher |
| 2 | replay_first_pass_page_rate | 0.400000 | higher |
| 2 | replay_pages_without_parsed_claims | 0.000000 | lower |
| 2 | replay_parsed_claims | 155.000000 | higher |
| 2 | stray_numbers_detected | 1.000000 | higher |
| 3 | replay_max_pairwise_jaccard | 0.053971 | lower |
| 3 | replay_mean_pairwise_jaccard | 0.026553 | lower |
| 3 | replay_page_pairs | 6.000000 | higher |
| 5 | conviction_agreement | 1.000000 | higher |
| 5 | conviction_levels | 1.000000 | higher |
| 5 | replay_validation_runs | 1.000000 | higher |
| 5 | top_k_identity | 1.000000 | higher |
| 6 | replay_cache_read_tokens | 68100.000000 | higher |
| 6 | replay_cache_write_tokens | 2724.000000 | higher |
| 6 | replay_cost_usd | 0.000000 | lower |
| 6 | replay_financial_sponsor_get_comparable_deals_page_rate | 1.000000 | higher |
| 6 | replay_financial_sponsor_get_failed_deals_page_rate | 1.000000 | higher |
| 6 | replay_financial_sponsor_get_sector_stats_page_rate | 1.000000 | higher |
| 6 | replay_input_tokens | 399498.000000 | higher |
| 6 | replay_output_tokens | 27424.000000 | higher |
| 6 | replay_pages | 10.000000 | higher |
| 6 | replay_request_p50_ms | 0.091938 | lower |
| 6 | replay_request_p95_ms | 0.135959 | lower |
| 6 | replay_responses | 26.000000 | higher |
| 6 | replay_run_p50_seconds | 0.081946 | lower |
| 6 | replay_run_p95_seconds | 0.081946 | lower |
| 6 | replay_runs | 1.000000 | higher |
| 6 | replay_strategic_get_comparable_deals_page_rate | 1.000000 | higher |
| 6 | replay_strategic_get_failed_deals_page_rate | 1.000000 | higher |
| 6 | replay_strategic_get_sector_stats_page_rate | 0.750000 | higher |

Unimplemented layers have no quality measurements.
