"""Own independent judge clients at the paid command boundary.

Owns: Shared connection lifetimes and explicitly configured SDK retry policy.
Does not own: Loading dotenv files, approving spending, or individual requests.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from google import genai
from google.genai.types import HttpOptions, HttpRetryOptions
from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

from acquirer_engine.errors import ConfigError
from evals.judges.plan import JudgePlan


@asynccontextmanager
async def clients(plan: JudgePlan) -> AsyncIterator[dict[str, Model]]:
    """Construct each provider once, only after explicit fresh execution is selected.

    Args:
        plan: Frozen identities, limits, and SDK retry policy.
    Yields:
        Both independent judge models sharing their respective provider clients.
    Raises:
        ConfigError: Required environment variables are absent.
    """
    if not all(os.environ.get(key) for key in ("OPENAI_API_KEY", "GEMINI_API_KEY")):
        raise ConfigError("Fresh judging requires OPENAI_API_KEY and GEMINI_API_KEY")
    config = plan.config
    with genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=HttpOptions(
            timeout=int(config.request_timeout_seconds * 1000),
            retry_options=HttpRetryOptions(attempts=config.sdk_retries + 1),
        ),
    ) as google:
        async with (
            google.aio,
            AsyncOpenAI(
                max_retries=config.sdk_retries, timeout=config.request_timeout_seconds
            ) as openai,
        ):
            models: dict[str, Model] = {}
            for role, spec in plan.models.items():
                models[role] = (
                    OpenAIResponsesModel(
                        spec.model_id, provider=OpenAIProvider(openai_client=openai)
                    )
                    if spec.provider == "openai"
                    else GoogleModel(spec.model_id, provider=GoogleProvider(client=google))
                )
            yield models
