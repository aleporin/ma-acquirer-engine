"""Keep request waiting and provider timing independently measurable.

Owns: Timing percentiles and explicit absence in historical observations.
Does not own: Live performance claims from synthetic timings.
"""

from acquirer_engine.llm.cost import RequestTiming
from acquirer_engine.settings import LayerSpec, Settings
from evals.graders import ops
from tests.fixtures.observations import observation


def test_partial_timing_coverage_does_not_invent_zero_provider_latency(settings: Settings) -> None:
    run = observation(settings)
    timed = run.calls[0].model_copy(
        update={
            "timing": RequestTiming(token_count_ms=3, admission_ms=20, provider_ms=77),
        }
    )
    run = run.model_copy(update={"calls": [run.calls[0], timed]})
    result = ops.grade(LayerSpec(id=6, name="ops"), [run], settings.analyst)
    assert result.metrics["replay_timed_responses"].value == 1
    assert result.metrics["replay_provider_p95_ms"].value == 77
    assert result.metrics["replay_admission_p95_ms"].value == 20
    assert result.metrics["replay_token_count_p95_ms"].value == 3


def test_legacy_total_latency_is_never_relabeled_as_provider_time(settings: Settings) -> None:
    result = ops.grade(LayerSpec(id=6, name="ops"), [observation(settings)], settings.analyst)
    assert "replay_provider_p95_ms" not in result.metrics
    assert result.metrics["replay_request_p95_ms"].value == 100
