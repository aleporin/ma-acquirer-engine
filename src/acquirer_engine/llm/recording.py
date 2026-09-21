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

from pydantic import TypeAdapter
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from acquirer_engine.deps import Deps
from acquirer_engine.errors import (
    BudgetExceeded,
    LLMError,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMTimeout,
)
from acquirer_engine.llm.budget import RunBudget, request_bound
from acquirer_engine.llm.cache import ResponseCache, request_key
from acquirer_engine.llm.cost import CostLedger, ExecutionMode
from acquirer_engine.llm.output import compatible_output_parameters, require_complete_response
from acquirer_engine.llm.trace import TraceWriter
from acquirer_engine.llm.trace_replay import ResponseArchive


@dataclass
class CallScope:
    """Request numbering isolated to the current page task."""

    acquirer: str
    attempt: int = 0
    stage: str = "analyst"
    role: str = "analyst"


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
        archive: ResponseArchive | None = None,
        escalation_model: Model | None = None,
    ) -> None:
        """Inject shared resources and keep page identity in task-local state."""
        super().__init__(profile=wrapped.profile if wrapped else None)
        self.wrapped, self.deps, self.cache, self.ledger = wrapped, deps, cache, ledger
        self.trace, self.mode = trace, mode
        seconds = deps.settings.analyst.run_timeout_seconds
        self.deadline = perf_counter() + seconds if seconds is not None else None
        self.archive = archive
        self.budget = RunBudget(deps.settings.analyst.max_run_usd if mode == "live" else None)
        self.models = {"analyst": wrapped, "escalation": escalation_model}
        self._attempts: dict[str, int] = {}
        self.first_response = asyncio.Event()
        self._scope: ContextVar[CallScope] = ContextVar("analyst_call_scope")
        self.identity = deps.settings.model_dump_json()

    @property
    def model_name(self) -> str:
        """Use configured model identity for both replay and live requests."""
        return self.deps.settings.models.roles[self._scope.get(CallScope("")).role].model_id

    @property
    def system(self) -> str:
        """Return the configured provider namespace."""
        return self.deps.settings.models.roles["analyst"].provider

    @contextmanager
    def scope(self, acquirer: str, *, resume: bool = False) -> Iterator[CallScope]:
        """Attribute concurrent requests without mutating shared buyer state."""
        attempt = self._attempts.get(acquirer, 0) if resume else 0
        token = self._scope.set(CallScope(acquirer, attempt))
        try:
            yield self._scope.get()
        finally:
            self._scope.reset(token)

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Apply the run deadline to admission and execution, including budget waits."""
        remaining = None if self.deadline is None else max(0, self.deadline - perf_counter())
        try:
            async with asyncio.timeout(remaining):
                return await self._request(messages, model_settings, model_request_parameters)
        except TimeoutError as error:
            raise LLMTimeout("Run deadline exceeded") from error

    async def _request(
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
        self._attempts[scope.acquirer] = scope.attempt
        key = request_key(
            self.identity + self.model_name,
            messages,
            {"settings": model_settings, **asdict(model_request_parameters)},
        )
        self.trace.write(
            "model_requested",
            scope.acquirer,
            attempt=scope.attempt,
            stage=scope.stage,
            cache_key=key,
            messages=messages,
        )
        started = perf_counter()
        tokens = (model_settings or {}).get(
            "max_tokens"
        ) or self.deps.settings.analyst.max_output_tokens
        estimate = self._estimate(messages, model_request_parameters, tokens)
        async with self.budget.claim(estimate) as charge:
            response = await self._response(key, messages, model_settings, model_request_parameters)
            duration = (perf_counter() - started) * 1000
            charge.actual = self._record_response(scope, response, duration)
        require_complete_response(response)
        if response.usage.output_tokens > tokens:
            raise BudgetExceeded("Response exceeds configured output token limit")
        return response

    def _record_response(self, scope: CallScope, response: ModelResponse, duration: float) -> float:
        self.trace.write(
            "model_responded", scope.acquirer, attempt=scope.attempt, response=response
        )
        record = self.ledger.record(
            scope.acquirer,
            scope.attempt,
            response.usage,
            duration,
            mode=self.mode,
            stage=scope.stage,
            model=self.deps.settings.models.roles[scope.role],
        )
        self.deps.logger.info(
            "model_called", **record.model_dump(), tool_calls=len(response.tool_calls)
        )
        self.first_response.set()
        return record.cost_usd

    def _estimate(
        self, messages: list[ModelMessage], parameters: ModelRequestParameters, output_tokens: int
    ) -> float:
        if self.mode != "live" or self.budget.limit is None:
            return 0
        encoded = TypeAdapter(list[ModelMessage]).dump_json(messages)
        config = self.deps.settings.analyst
        return request_bound(
            self.deps.settings.models.roles[self._scope.get().role],
            len(encoded) + len(str(asdict(parameters)).encode()) + config.request_overhead_tokens,
            output_tokens,
            config.sdk_retries,
        )

    async def _response(
        self,
        key: str,
        messages: list[ModelMessage],
        settings: ModelSettings | None,
        parameters: ModelRequestParameters,
    ) -> ModelResponse:
        if self.mode == "replay":
            if self.archive is not None:
                scope = self._scope.get()
                return self.archive.load(scope.acquirer, scope.attempt, messages)
            return self.cache.load(key)
        wrapped = self.models[self._scope.get().role]
        if wrapped is None:
            raise LLMInvalidOutput("No model client was injected")
        try:
            async with asyncio.timeout(self.deps.settings.analyst.request_timeout_seconds):
                response = await wrapped.request(messages, settings, parameters)
        except TimeoutError as error:
            raise LLMTimeout("Model request timed out") from error
        except ModelHTTPError as error:
            if error.status_code == 429:
                raise LLMRateLimited("Model request rate limited") from error
            raise LLMError(f"Model request failed with HTTP {error.status_code}") from error
        self.cache.store(key, response)
        return response
