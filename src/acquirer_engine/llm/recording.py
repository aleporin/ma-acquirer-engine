"""Record each analyst model request behind one injected client.

Owns: Request replay, response usage, task attribution, and per-call deadlines.
Does not own: Creating provider clients, tool execution, or repair policy.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from time import perf_counter

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from acquirer_engine.deps import Deps
from acquirer_engine.errors import LLMError, LLMInvalidOutput, LLMRateLimited, LLMTimeout
from acquirer_engine.llm.cache import ResponseCache, request_key
from acquirer_engine.llm.cost import CostLedger, ExecutionMode
from acquirer_engine.llm.output import compatible_output_parameters, require_complete_response
from acquirer_engine.llm.trace import TraceWriter


@dataclass
class CallScope:
    """Request numbering isolated to the current page task."""

    acquirer: str
    attempt: int = 0


class RecordedModel(Model):
    """One shared request boundary; replay can operate with no wrapped client."""

    def __init__(
        self,
        wrapped: Model | None,
        deps: Deps,
        cache: ResponseCache,
        ledger: CostLedger,
        trace: TraceWriter,
        *,
        mode: ExecutionMode,
    ) -> None:
        """Inject shared resources and keep page identity in task-local state."""
        super().__init__(profile=wrapped.profile if wrapped else None)
        self.wrapped, self.deps, self.cache, self.ledger = wrapped, deps, cache, ledger
        self.trace, self.mode = trace, mode
        self.first_response = asyncio.Event()
        self._scope: ContextVar[CallScope] = ContextVar("analyst_call_scope")
        self.identity = deps.settings.model_dump_json()

    @property
    def model_name(self) -> str:
        """Use configured model identity for both replay and live requests."""
        return self.deps.settings.models.roles["analyst"].model_id

    @property
    def system(self) -> str:
        """Return the configured provider namespace."""
        return self.deps.settings.models.roles["analyst"].provider

    @contextmanager
    def scope(self, acquirer: str) -> Iterator[None]:
        """Attribute concurrent requests without mutating shared buyer state."""
        token = self._scope.set(CallScope(acquirer))
        try:
            yield
        finally:
            self._scope.reset(token)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Replay or call once, retaining every returned usage record.

        Args:
            messages: Framework conversation including tool observations.
            model_settings: Settings applied to this request.
            model_request_parameters: Typed tools and output schema.
        Returns:
            The raw response; acceptance happens in the output validator.
        Raises:
            LLMError: Replay fails or a provider request fails.
        """
        model_request_parameters = compatible_output_parameters(model_request_parameters)
        scope = self._scope.get()
        scope.attempt += 1
        key = request_key(
            self.identity,
            messages,
            {"settings": model_settings, **asdict(model_request_parameters)},
        )
        self.trace.write(
            "model_requested",
            scope.acquirer,
            attempt=scope.attempt,
            cache_key=key,
            messages=messages,
        )
        started = perf_counter()
        response = await self._response(key, messages, model_settings, model_request_parameters)
        duration = (perf_counter() - started) * 1000
        self.trace.write(
            "model_responded", scope.acquirer, attempt=scope.attempt, response=response
        )
        record = self.ledger.record(
            scope.acquirer, scope.attempt, response.usage, duration, mode=self.mode
        )
        self.deps.logger.info(
            "model_called", **record.model_dump(), tool_calls=len(response.tool_calls)
        )
        self.first_response.set()
        require_complete_response(response)
        return response

    async def _response(
        self,
        key: str,
        messages: list[ModelMessage],
        settings: ModelSettings | None,
        parameters: ModelRequestParameters,
    ) -> ModelResponse:
        if self.mode == "replay":
            return self.cache.load(key)
        if self.wrapped is None:
            raise LLMInvalidOutput("No model client was injected")
        try:
            async with asyncio.timeout(self.deps.settings.analyst.request_timeout_seconds):
                response = await self.wrapped.request(messages, settings, parameters)
        except TimeoutError as error:
            raise LLMTimeout("Model request timed out") from error
        except ModelHTTPError as error:
            if error.status_code == 429:
                raise LLMRateLimited("Model request rate limited") from error
            raise LLMError(f"Model request failed with HTTP {error.status_code}") from error
        self.cache.store(key, response)
        return response
