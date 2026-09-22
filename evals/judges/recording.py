"""Record bounded judge requests through shared injected resources.

Owns: Response caching, request cost admission, and local transcripts.
Does not own: Building clients, interpreting verdicts, or calibration.
"""

import asyncio
from dataclasses import asdict, dataclass, field
from time import perf_counter

from pydantic import TypeAdapter
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from structlog.stdlib import BoundLogger

from acquirer_engine.errors import BudgetExceeded, LLMInvalidOutput
from acquirer_engine.llm.budget import RunBudget, request_bound
from acquirer_engine.llm.cache import ResponseCache, request_key
from acquirer_engine.llm.cost import CallRecord, CostLedger, ExecutionMode
from acquirer_engine.llm.output import require_complete_response
from acquirer_engine.llm.trace import TraceWriter
from evals.judges.plan import Job, JudgePlan


@dataclass
class JudgeDeps:
    """Resources constructed once and shared across the entire judge run."""

    plan: JudgePlan
    models: dict[str, Model]
    cache: ResponseCache
    ledger: CostLedger
    budget: RunBudget
    trace: TraceWriter
    logger: BoundLogger
    mode: ExecutionMode
    semaphore: asyncio.Semaphore
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)


class RecordedJudge(Model):
    """A job-local adapter around shared clients and accounting."""

    def __init__(self, deps: JudgeDeps, job: Job) -> None:
        wrapped = deps.models.get(job.role)
        super().__init__(profile=wrapped.profile if wrapped else None)
        self.deps, self.job, self.wrapped = deps, job, wrapped
        self.calls: list[CallRecord] = []
        self.cache_hit = False

    @property
    def model_name(self) -> str:
        return self.deps.plan.models[self.job.role].model_id

    @property
    def system(self) -> str:
        return self.deps.plan.models[self.job.role].provider

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Record one isolated request and reuse an identical paired-page response."""
        plan, job = self.deps.plan, self.job
        identity = plan.models[job.role].model_dump_json() + plan.config.model_dump_json()
        key = request_key(
            identity,
            {"prompt": job.prompt, "payload": job.payload, "version": job.prompt_file},
            {"settings": model_settings, "schemas": plan.output_schemas},
        )
        self.deps.trace.write(
            "judge_requested", job.case_id, job_id=job.job_id, cache_key=key, messages=messages
        )
        async with self.deps.locks.setdefault(key, asyncio.Lock()):
            started = perf_counter()
            if self.deps.mode == "replay" or (self.deps.cache.root / f"{key}.json").exists():
                self.cache_hit = True
                response = self.deps.cache.load(key)
                self._record(response, started, "replay")
            else:
                response = await self._fresh(
                    key, messages, model_settings, model_request_parameters, started
                )
        require_complete_response(response)
        if response.usage.output_tokens > plan.config.max_output_tokens:
            raise BudgetExceeded("Judge exceeded its output token limit")
        return response

    async def _fresh(
        self,
        key: str,
        messages: list[ModelMessage],
        settings: ModelSettings | None,
        parameters: ModelRequestParameters,
        started: float,
    ) -> ModelResponse:
        if self.wrapped is None:
            raise LLMInvalidOutput("No judge model was injected")
        config = self.deps.plan.config
        tokens = len(TypeAdapter(list[ModelMessage]).dump_json(messages))
        tokens += len(str(asdict(parameters)).encode()) + config.request_overhead_tokens
        bound = request_bound(
            self.deps.plan.models[self.job.role],
            tokens,
            config.max_output_tokens,
            config.sdk_retries,
        )
        self.deps.trace.write(
            "judge_budget_estimated",
            self.job.case_id,
            job_id=self.job.job_id,
            reservation_usd=bound,
            method="bytes",
        )
        async with self.deps.budget.claim(bound) as charge:
            async with asyncio.timeout(config.request_timeout_seconds):
                response = await self.wrapped.request(messages, settings, parameters)
            self.deps.cache.store(key, response)
            charge.actual = self._record(response, started, self.deps.mode)
        return response

    def _record(self, response: ModelResponse, started: float, mode: ExecutionMode) -> float:
        self.deps.trace.write(
            "judge_responded", self.job.case_id, job_id=self.job.job_id, response=response
        )
        record = self.deps.ledger.record(
            self.job.case_id,
            1,
            response.usage,
            (perf_counter() - started) * 1000,
            mode=mode,
            stage=self.job.kind,
            model=self.deps.plan.models[self.job.role],
        )
        self.calls.append(record)
        self.deps.logger.info(
            "judge_called", **record.model_dump(), job_id=self.job.job_id, cache_hit=self.cache_hit
        )
        return record.cost_usd
