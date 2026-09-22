"""Exercise SDK retries through an in-memory HTTP transport.

Owns: Retryable statuses and one configured client boundary.
Does not own: Live provider availability or credentials.
"""

import httpx2
import pytest
from anthropic import APIStatusError

from acquirer_engine.llm.provider import create_client
from acquirer_engine.settings import Settings


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "expected_calls"), [(429, 2), (500, 2), (400, 1), (409, 1)])
async def test_client_retries_transient_responses_only(
    settings: Settings, status: int, expected_calls: int
) -> None:
    calls = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(
            status,
            headers={"retry-after-ms": "1"},
            json={"type": "error", "error": {"type": "test", "message": "fixture failure"}},
        )

    transport = httpx2.AsyncClient(transport=httpx2.MockTransport(handle))
    config = settings.analyst.model_copy(update={"sdk_retries": 1})
    async with create_client(config, http_client=transport, api_key="offline-test") as client:
        with pytest.raises(APIStatusError):
            await client.messages.create(
                model=settings.models.roles["analyst"].model_id,
                max_tokens=1,
                messages=[{"role": "user", "content": "fixture"}],
            )
    assert len(calls) == expected_calls
