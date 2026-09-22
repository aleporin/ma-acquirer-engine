# Architecture and decisions

## Execution map

```text
cli.py → pipeline.py
  ├─ stages/select.py    validate inputs, rank buyers, prepare evidence
  ├─ factory.py          construct shared runtime resources
  ├─ stages/draft.py     retrieve → draft → validate → repair if needed
  ├─ stages/review.py    optional portfolio review (disabled by default)
  └─ save run.json
cli.py → stages/render.py → HTML + Markdown
```

| Concern | Implementation |
| --- | --- |
| CSV validation and quality | [`data.py`](../src/acquirer_engine/data.py) |
| Historical features and scoring | [`ranking/`](../src/acquirer_engine/ranking) |
| Initial evidence and stable IDs | [`evidence/pack.py`](../src/acquirer_engine/evidence/pack.py) |
| Agent definitions and evidence queries | [`llm/agents.py`](../src/acquirer_engine/llm/agents.py), [`llm/tools.py`](../src/acquirer_engine/llm/tools.py) |
| Claim and prose checks | [`validation/`](../src/acquirer_engine/validation) |
| Requests, usage, and traces | [`llm/recording.py`](../src/acquirer_engine/llm/recording.py), [`llm/cost.py`](../src/acquirer_engine/llm/cost.py), [`llm/trace.py`](../src/acquirer_engine/llm/trace.py) |
| Saved inputs and replay | [`replay.py`](../src/acquirer_engine/replay.py) |
| Independent evaluation | [`evals/command.py`](../evals/command.py) → [`evals/harness.py`](../evals/harness.py) |

## 2026-09-22 — Keep the workflow explicit

**Context:** the product has a fixed sequence with a bounded model stage.
**Decision:** keep CLI handling, orchestration, resource construction, and the four
stages separate. `Deps` holds settings/logger; `RuntimeDeps` adds required shared
services; each buyer gets its own evidence and conversation state.
**Alternatives:** a monolithic script or a graph framework for the entire flow.
**Consequence:** stage order is visible in Python, and dependencies can be replaced
in tests without creating clients inside the call path.

## 2026-09-22 — Use a stronger writer with bounded recovery

**Context:** schema-valid drafts could still misinterpret the evidence.
**Decision:** use the stronger configured writer, one same-tier repair, and opt-in
portfolio review. Escalation is disabled because no stronger tier is configured.
The router's second recovery slot belongs to escalation, so `max_repairs: 2` does
not enable two same-tier repairs. See [analyst settings](../config/analyst.yaml).
The first response warms the shared prompt prefix; remaining buyers run behind
a semaphore. Schema/evidence failures retain conversation and tool history for
repair. SDK retries handle transient transport errors; exhausted retries,
deadlines, budgets, and missing replay responses stop the affected page.
**Alternatives:** a cheaper writer with more retries, or mandatory extra review.
**Consequence:** the selected run completed ten pages within the speed goal but
exceeded the cost goal. Historical review changed no pages in one observation;
that does not prove review never helps. [Measurements](EVALS.md) remain separate
from design choices. Failed pages retain banners and cause a nonzero CLI exit.

## 2026-09-22 — Validate evidence without claiming semantic certainty

**Context:** correct numbers alone did not prevent an inverted margin comparison
or an exclusive claim based on incomplete history.
**Decision:** prioritize exact-sector evidence, expose Closed/Pending/resolved
counts, and add narrow checks for recognized margin-direction and exclusivity
phrases. Display source financials beside the prose. Keep original failed archives.
**Alternatives:** manual edits to generated pages or a general semantic verifier.
**Consequence:** known faults are caught, but qualitative reasoning still needs
independent evaluation. Complete history does not by itself prove an exclusive claim.

## 2026-09-21 — Compute ranking from historical signals

**Context:** the buyer list needs reproducible arithmetic, while many buyers have
sparse histories.
**Decision:** combine sector, size, recency, completion, margin, geography,
rationale-tag, and deal-type signals. Shrink sparse signals toward buyer-type
priors; use fixed weights, tie-breaks, and conviction thresholds. The weights are
initial design assumptions, not an established banking framework.
Use stated multiples and margins; report source discrepancies instead of silently
recalculating them. Exclude Rumored deals from fitting and Pending deals from the
completion denominator. Closed deals alone support valuation. Sponsor co-activity
and profile distance define sector adjacency; common tags receive less weight.
**Alternatives:** popularity alone, a trained classifier, or model-written scores.
**Consequence:** every score is explainable, but the synthetic holdout has not
shown lift over popularity. Fixed thresholds yield ten Medium convictions;
labels are not forced to create diversity.

## 2026-09-21 — Use typed tools and a thin evidence pack

**Context:** the analyst must choose evidence without receiving the entire CSV.
**Decision:** Pydantic validates boundary data; Pydantic AI defines typed tools,
structured outputs, output validators, and local test models. Prompts separate
instructions, output schema, and delimited untrusted data. A buyer's initial pack
contains its activity and scores; valuation requires separately retrieved Closed
comps. Five tools return stable IDs, capped rows, and explicit truncation.
**Alternatives:** a single large prompt, raw SDK orchestration, or vector retrieval.
**Consequence:** tool use is necessary and testable. The verifier sees only each
buyer's pack and retrieved evidence, so one buyer cannot borrow another's provenance.

## 2026-09-21 — Share resources and record actual usage

**Context:** concurrent calls share a budget and need inspectable failures.
**Decision:** construct providers, ledger, cache, and logger once in `factory.py`.
Reserve estimated input plus maximum output/retry charges before admission, then
settle returned usage. Missing usage remains an uncertain bound. Structlog writes
JSON events; recorded conversations support debugging and replay.
**Alternatives:** create a client per request or check cost only after completion.
**Consequence:** reservations prevent concurrent over-allocation but can reject a
request whose eventual bill would fit. The $10 admission cap is distinct from the
under-$1 measured-cost goal. Local traces contain confidential conversation data.

## 2026-09-21 — Keep replay strict

**Context:** repeating a saved conversation differs from generating a new one.
**Decision:** separate content-addressed response caching, frozen run-ID replay,
and a hash-checked portable archive. Bundle replay requires matching inputs and
policy; run-ID replay loads the original snapshot. Neither has a paid fallback.
**Alternatives:** filename caching or silently regenerating missing responses.
**Consequence:** replay writes a new run with lineage and applies current validation
to recorded responses. It does not run old code or measure new model quality.

## 2026-09-21 — Deliver a local report with small extensions

**Context:** 500 structured rows and a shareable buyer list need little infrastructure.
**Decision:** use pandas queries, PyYAML settings, a Typer CLI, and escaped Jinja
HTML/Markdown templates. Keep feedback in atomically written local JSON. Exclude
flagged buyers and disclose a cosine-similarity discount for remaining same-type
buyers; the evaluated base ranker stays unchanged. Comparison reuses selection
without drafting. Optional model summaries are labeled unverified interpretations.
**Alternatives:** a database-backed web app, notebook-only output, or online retraining.
**Consequence:** no server is needed. Copy the complete output directory for linked
citations; browser printing may use more than ten sheets. Per-user transactional
storage, access controls, and CRM/API adapters belong to a larger deployment.

## 2026-09-21 — Evaluate independently of generation

**Context:** passing numeric checks does not establish useful ranking or prose.
**Decision:** keep temporal baselines, fixtures, repeated-run checks, cost/latency,
and controlled ablations in a separate harness. Judge five isolated dimensions
with two model families against blind human labels; report agreement and uncertainty.
**Alternatives:** a single broad model score or only end-to-end happy-path tests.
**Consequence:** missing calibration stays unmeasured, failed runs remain available,
and replay results are distinguished from live observations. See [EVALS.md](EVALS.md).
