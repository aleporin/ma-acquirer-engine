"""Specify billing for providers without a cache-write token price.

Owns: Zero-write compatibility and rejection of unpriced positive usage.
Does not own: Provider invoice reconciliation or judge execution.
"""

import pytest
from pydantic_ai.usage import RequestUsage

from acquirer_engine.errors import ConfigError
from acquirer_engine.llm.cost import CostLedger
from acquirer_engine.settings import Settings


def test_no_cache_write_price_is_valid_when_no_writes_were_used(settings: Settings) -> None:
    ledger = CostLedger(settings.models.roles["judge_b"])
    call = ledger.record(
        "case", 1, RequestUsage(input_tokens=100, output_tokens=20), 3, mode="live"
    )
    assert call.cost_usd == pytest.approx((100 * 2 + 20 * 12) / 1_000_000)


def test_unpriced_cache_writes_are_never_silently_free(settings: Settings) -> None:
    ledger = CostLedger(settings.models.roles["judge_b"])
    with pytest.raises(ConfigError, match="price"):
        ledger.record(
            "case",
            1,
            RequestUsage(input_tokens=100, output_tokens=20, cache_write_tokens=10),
            3,
            mode="live",
        )
    assert not ledger.entries
