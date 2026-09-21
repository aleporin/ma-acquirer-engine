"""Construct one configured provider client at the command boundary.

Owns: SDK retry eligibility and per-attempt timeout configuration.
Does not own: Client creation during requests, ranking, or output repair.
"""

import httpx2
from anthropic import AsyncAnthropic

from acquirer_engine.llm.config import AnalystConfig


class AnalystClient(AsyncAnthropic):
    """Keep SDK backoff/jitter while excluding nontransient client statuses."""

    def _should_retry(self, response: httpx2.Response) -> bool:
        return response.status_code in {408, 429} or response.status_code >= 500


def create_client(
    config: AnalystConfig,
    *,
    http_client: httpx2.AsyncClient | None = None,
    api_key: str | None = None,
) -> AsyncAnthropic:
    """Build the client's complete lifecycle once before task fan-out.

    Args:
        config: Timeout and SDK retry limits.
        http_client: Optional injected transport for offline integration tests.
        api_key: Test credential override; live SDK reads its environment normally.
    Returns:
        An owned async client, to be closed by the command boundary.
    """
    return AnalystClient(
        api_key=api_key,
        http_client=http_client,
        max_retries=config.sdk_retries,
        timeout=config.request_timeout_seconds,
    )
