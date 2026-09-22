"""Freeze exact judge prompts, settings, schemas, and page provenance.

Owns: Reproducible request plans and offline conservative cost estimates.
Does not own: Executing requests or granting paid-run approval.
"""

import hashlib
import json
from pathlib import Path
from typing import TypedDict

from acquirer_engine.errors import EvaluationError
from acquirer_engine.llm.cost import request_bound
from acquirer_engine.settings import ModelsConfig, ModelSpec
from evals.judges.cases import identify_input
from evals.judges.config import JudgeConfig
from evals.judges.schema import (
    Case,
    Corpus,
    Dimension,
    HumanLabel,
    IdentificationAnswer,
    Record,
    RubricAnswer,
)


class Job(Record):
    """Expected identification answers are metadata, excluded from the request."""

    job_id: str
    case_id: str
    role: str
    kind: str
    prompt_file: str
    prompt: str
    payload: str
    seed: int | None = None
    expected_choice: int | None = None
    candidate_order: tuple[str, ...] = ()


class JobIdentity(TypedDict):
    """Typed construction fields shared by both isolated request formats."""

    job_id: str
    case_id: str
    role: str
    kind: str
    prompt_file: str
    prompt: str


class JudgePlan(Record):
    """Full causal inputs retained so replay never reads today's prompts or prices."""

    corpus: Corpus
    config: JudgeConfig
    models: dict[str, ModelSpec]
    labels: tuple[HumanLabel, ...]
    jobs: tuple[Job, ...]
    output_schemas: dict[str, str]

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def output_schemas() -> dict[str, str]:
    """Fingerprint local output contracts independently of provider transformations."""
    return {
        name: json.dumps(schema.model_json_schema(), sort_keys=True)
        for name, schema in (("rubric", RubricAnswer), ("identification", IdentificationAnswer))
    }


def _job(case: Case, role: str, kind: str, filename: str, prompt: str, seed: int) -> Job:
    identity = hashlib.sha256(f"{case.case_id}:{role}:{kind}".encode()).hexdigest()
    common = JobIdentity(
        job_id=identity,
        case_id=case.case_id,
        role=role,
        kind=kind,
        prompt_file=filename,
        prompt=prompt,
    )
    if kind == "identification":
        derived = int(
            hashlib.sha256(f"{seed}:{case.source_run_id}:{case.buyer}".encode()).hexdigest(), 16
        )
        inputs = identify_input(case, derived)
        return Job(
            **common,
            payload=inputs.payload,
            seed=inputs.seed,
            expected_choice=inputs.expected_choice,
            candidate_order=inputs.candidate_order,
        )
    payload = json.dumps(
        {
            "target": case.target,
            "buyer": case.buyer,
            "page": case.page,
            "evidence": case.evidence,
            "dimension": kind,
        },
        sort_keys=True,
    )
    return Job(**common, payload=payload)


def build_plan(
    corpus: Corpus,
    config: JudgeConfig,
    models: ModelsConfig,
    prompts: Path,
    labels: list[HumanLabel],
) -> JudgePlan:
    """Build separate dimension requests without exposing human votes.

    Args:
        corpus, config, models: Frozen cases and explicit judge policy/prices.
        prompts: Directory containing the configured versioned prompt files.
        labels: Completed human labels, or empty for an offline cost plan.
    Returns:
        Exact inputs for one comparison, with two independent provider families.
    Raises:
        EvaluationError: Models or prompts are missing or not independent.
    """
    try:
        specs = {role: models.roles[role] for role in config.roles}
        if {spec.provider for spec in specs.values()} != {"openai", "google"}:
            raise EvaluationError("Judges must use independent OpenAI and Google models")
        files = {str(d): config.rubric_prompts[d] for d in Dimension}
        files["identification"] = config.identification_prompt
        contents = {kind: (prompts / name).read_text() for kind, name in files.items()}
        jobs = tuple(
            _job(case, role, kind, filename, contents[kind], config.seed)
            for case in corpus.cases
            for role in config.roles
            for kind, filename in files.items()
        )
        return JudgePlan(
            corpus=corpus,
            config=config,
            models=specs,
            labels=tuple(labels),
            jobs=jobs,
            output_schemas=output_schemas(),
        )
    except (OSError, KeyError) as error:
        raise EvaluationError("Missing judge model or versioned prompt") from error


def estimate_plan(plan: JudgePlan) -> dict[str, float | int]:
    """Report request inventory and a byte-based worst-case spend estimate.

    Args:
        plan: Prepared calls, including both original and post-review pages.
    Returns:
        Calls, unique payload count, conservative USD, and the enforced run cap.
    """
    unique: dict[tuple[str, str, str], Job] = {}
    for job in plan.jobs:
        unique[(job.role, job.prompt, job.payload)] = job
    total = 0.0
    for job in unique.values():
        schema = plan.output_schemas["identification" if job.kind == "identification" else "rubric"]
        tokens = (
            len((job.prompt + job.payload + schema).encode()) + plan.config.request_overhead_tokens
        )
        total += request_bound(
            plan.models[job.role], tokens, plan.config.max_output_tokens, plan.config.sdk_retries
        )
    return {
        "jobs": len(plan.jobs),
        "unique_requests": len(unique),
        "conservative_usd": total,
        "max_run_usd": plan.config.max_run_usd,
    }
