"""Build explicit synthetic observations for evaluation behavior tests.

Owns: Small run and page factories with known usage and claims.
Does not own: Real provider measurements or quality assertions.
"""

from acquirer_engine.llm.cost import CallRecord
from acquirer_engine.llm.results import AnalystRun, PageResult
from acquirer_engine.settings import Settings
from acquirer_engine.validation.schema import AcquirerRationale
from tests.fixtures.rationale import rationale_payload


def observation(settings: Settings, index: int = 0) -> AnalystRun:
    page = PageResult.model_validate(
        dict(
            acquirer="Buyer A",
            acquirer_type="Strategic",
            status="verified",
            rationale=AcquirerRationale.model_validate(
                rationale_payload(), context=settings.evidence.validation
            ),
            errors=[],
            tools=["get_comparable_deals"],
            latency_seconds=2,
            claims_total=4,
            claims_verified=4,
        ),
        context=settings.evidence.validation,
    )
    call = CallRecord(
        acquirer="Buyer A",
        model="fixture",
        attempt=1,
        mode="replay",
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=30,
        cache_write_tokens=10,
        cost_usd=0,
        latency_ms=100,
    )
    return AnalystRun.model_validate(
        dict(
            run_id=f"{index:032x}",
            mode="replay",
            git_sha="a" * 40,
            prompt_version="fixture",
            latency_seconds=3,
            pages=[page, page.model_copy(update={"acquirer": "Buyer B"})],
            calls=[call],
        ),
        context=settings.evidence.validation,
    )
