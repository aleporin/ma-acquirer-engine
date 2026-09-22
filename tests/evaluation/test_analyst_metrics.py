"""Check operational and prose metrics against explicit synthetic observations.

Owns: Metric arithmetic and the boundary between replay and live evidence.
Does not own: Claims about provider quality from fixture text.
"""

from acquirer_engine.settings import LayerSpec, Settings
from evals.graders import distinct, ops, stability
from tests.fixtures.observations import observation


def test_operations_do_not_present_replayed_usage_as_new_spend(settings: Settings) -> None:
    result = ops.grade(
        LayerSpec(id=6, name="operations"), [observation(settings)], settings.analyst
    )
    assert result.status == "passed"
    assert result.metrics["replay_input_tokens"].value == 100
    assert result.metrics["replay_cost_usd"].value == 0
    assert result.metrics["replay_request_p95_ms"].value == 100
    assert "live_gate_met" not in result.metrics


def test_identical_prose_has_maximal_similarity(settings: Settings) -> None:
    result = distinct.grade(
        LayerSpec(id=3, name="distinctiveness"), [observation(settings)], settings.analyst
    )
    assert result.metrics["replay_mean_pairwise_jaccard"].value == 1
    assert result.metrics["replay_page_pairs"].value == 1


def test_validation_stability_requires_all_five_runs_and_preserves_ranking_failure(
    settings: Settings,
) -> None:
    layer = LayerSpec(id=5, name="stability")
    ranking = stability.grade(layer, stability.RankingStability(0.5, 1, 1, 2))
    runs = [observation(settings, i) for i in range(5)]
    result = stability.with_validation(ranking, runs, settings.analyst)
    assert result.status == "failed"
    assert result.metrics["replay_validation_pass_5"].value == 1
    bad = runs[-1].pages[0].model_copy(update={"status": "failed", "rationale": None})
    runs[-1] = runs[-1].model_copy(update={"pages": [bad, runs[-1].pages[1]]})
    result = stability.with_validation(ranking, runs, settings.analyst)
    assert result.metrics["replay_validation_pass_5"].value == 0.5
    assert (
        "replay_validation_pass_5"
        not in stability.with_validation(ranking, runs[:1], settings.analyst).metrics
    )
