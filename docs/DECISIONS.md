# Architecture decisions

## 2026-09-22 — Group code around the execution readers need to follow

Context: the buyer loop was spread across separate scheduling, attempt, route,
and repair modules, while evaluation preparation still used build-phase names.
Decision: place the complete buyer loop in `llm/analyst.py`; group agent bindings,
evidence state, provider adaptation, cost controls, and trace replay with their
related implementations. Keep ranking policy in the scorer, prose guards together,
and report evidence resolution in one module. Move target precedence into
selection and command inspection into the CLI. Name evaluation preparation for
ranking, groundedness, analyst outcomes, routing, and judges.
Alternatives considered: retain one small file per helper, or combine the entire
pipeline into a single module.
Consequence: fewer files are needed to follow one outcome; some modules are longer.
Functions remain bounded, and provider construction, typed results, frozen inputs,
response identity, and data framing retain separate responsibilities. This is a
structural change: prompts, model policy, scoring, validation behavior, archive
contracts, and historical measurements remain unchanged. It makes no new claim
about generation quality, latency, predictive lift, or independent calibration.

## 2026-09-22 — Use the stronger writer for output corrections

Context: numeric/schema acceptance did not prevent incorrect interpretation of
margins, ownership, geography, and transaction values. Prompt corrections alone
had not produced an acceptable replacement sample.
Decision: promote the previously reserved Opus 5 escalation model to the analyst role,
disable escalation because no stronger tier is configured, and retain opt-in
portfolio review. The current router permits one same-tier repair when escalation
is disabled, despite the configured ceiling of two recovery attempts. Use the
approved $10 admission cap for concurrent reservations and a 6,000-token output
ceiling after an earlier draft reached 4,000 tokens. Retain the under-$1
returned-usage goal and 60-second end-to-end target.
Alternatives considered: retain the cheaper writer with further prompt changes,
or require the extra portfolio review despite its inconclusive historical effect.
Consequence: [v6](../evals/results/p7-f12ac9adc5c49079dd40c1b402aabad0b6a55c40/iteration.md)
completed in 44.823s for $1.914185, and
[v7](../evals/results/p7-0a63cfe438c161aef46b0502ca13c941ec1779e2/iteration.md)
in 50.613s for $1.940530. Both met the speed goal in those observations, exceeded
the cost goal, and were rejected in factual read-throughs. They do not establish
causal quality or speed improvement from model choice. The
[selected v13 run](../evals/results/p7-8d5ffa583cd6dd8a84685b443dd19200ba714b25/iteration.md)
produced 10/10 pages and 54/54 matched claims in 48.176s for $1.863930, with one
numeric repair. A source-based factual read-through found no concrete
contradiction, but selection after several iterations is not an unbiased
first-run reliability estimate. The cost goal remains unmet and independent
calibration is unmeasured. Live layer 6 still lacks matched controls for this
model/prompt cohort; historical ablations remain evidence for their original
cohort only.

## 2026-09-22 — Correct interpretation at the evidence and report boundaries

Context: correct numeric claims still allowed an inverted margin comparison,
overstated completion history, and unsupported claims about missing precedents.
Decision: prioritize exact-sector buyer rows before recency within the existing
pack caps, expose Closed/Pending/resolved counts, and reject recognized explicit
target-versus-Closed-sector median margin inversions. Version the analyst prompt
to distinguish tags, outcomes, ownership fields, and incomplete query populations.
Show canonical deal financials next to the prose, rather than only in an appendix.
Add a test-first scope guard for recognized “only through/in/on” target-theme
claims when the analyst has seen only part of a buyer's history; request observed
positive examples instead of asserting exclusivity.
Alternatives considered: edit archived prose in place, force new convictions, or
build a general semantic-verification system.
Consequence: archived failures remain intact. Both semantic guards have deliberately
narrow language coverage; complete history lifts the theme-scope restriction but
does not prove an exclusive claim true. Numeric and schema checks do not certify
all prose. The selected v13 sample passed a separate source-based factual
read-through; this is development QA, not independent banker calibration.

## 2026-09-22 — Preserve measurements independently of release status

Context: working report output and green CI do not establish live speed,
predictive lift, or agreement with a human rater.
Decision: keep original scorecards and label absent measurements explicitly.
The final replay check remains separate from earlier live observations.
Alternatives considered: replace historical failures with the latest output.
Consequence: reviewers can trace improvement and see which goals remain unmet.

## 2026-09-21 — Ship a portable, static report

Context: the primary output is a buyer list someone can read and share.
Decision: render self-contained HTML, ten Markdown pages, and structured JSON.
Escape public fields and resolve displayed citations before writing.
Alternatives considered: a web application, PDF-only output, or notebook-only delivery.
Consequence: no server is needed; printed sheet count depends on browser settings.
The JSON contract is available for a later authenticated API or CRM adapter.

## 2026-09-21 — Use a workflow with bounded analyst stages

Context: ranking requires reproducible arithmetic; a specific rationale requires
choosing and interpreting evidence.
Decision: code owns ranking and route limits. Each analyst selects typed tools,
drafts a schema-constrained page, and receives verifier feedback when it fails.
Alternatives considered: a single large prompt or an unconstrained autonomous loop.
Consequence: behavior has explicit stop conditions and can be replayed.

## 2026-09-21 — Use typed boundaries and shared resources

Context: model responses and tool results cross validation boundaries.
Decision: use Pydantic AI for typed tools, outputs, validators, usage limits,
and local test models. Construct providers in bootstrap; wrap recording at
the model boundary. Inject shared clients, ledger, cache, and logger.
Alternatives considered: raw SDK orchestration throughout the application or
another framework with an additional state abstraction.
Consequence: provider-specific changes stay near the adapter. A direct SDK
replacement still requires the same contract tests.

## 2026-09-21 — Make evidence retrieval necessary

Context: supplying every fact initially would make tool calls decorative.
Decision: the core pack includes a buyer's activity, scores, and assumptions;
valuation needs separately retrieved Closed comps. Tool results have row caps,
stable IDs, and explicit truncation.
Alternatives considered: put every transaction in the initial context.
Consequence: the tools-disabled control tests whether retrieval matters.
Numeric validation still cannot prove a comp is economically persuasive.

## 2026-09-21 — Separate repair from transport recovery

Context: malformed prose, rate limits, and budget denial need different remedies.
Decision: schema/evidence errors get bounded feedback and possible escalation.
SDK retries handle transient transport errors. Budget, deadline, and missing
replay failures stop the affected page while other buyers continue.
Alternatives considered: retry everything or fail the whole portfolio.
Consequence: failure reasons remain visible and costs stay bounded.

## 2026-09-21 — Make portfolio review opt-in

Context: in the matched observation, the reviewer approved every page without
revision and incurred $0.045584 of returned usage.
Decision: retain the tested reviewer but disable it by default.
Alternatives considered: require an extra serial review on every run.
Consequence: one observation does not prove review never improves quality;
independent rubric calibration remains pending.

## 2026-09-21 — Separate budget reservations from measured billing

Context: concurrent requests cannot each assume the remaining budget is free.
Decision: reserve a conservative maximum cost, then settle returned usage.
Keep unreturned usage uncertain. The original approved generation admission cap
was $3; the quality-correction decision above supersedes it with $10. The
under-$1 measured-cost goal remains.
Alternatives considered: check cost only after all requests finish.
Consequence: admission can stop work that might ultimately fit, but prevents
concurrent over-allocation. The 120-second request ceiling is a safety limit,
not a replacement for the 60-second end-to-end target.

## 2026-09-21 — Keep ranking and conviction deterministic

Context: sponsors have deeper histories than most strategics; the synthetic
holdout does not establish superiority over popularity.
Decision: combine bounded signals with buyer-type shrinkage, fixed weights,
deterministic ties, and fixed conviction thresholds. Report diversity without
forcing label variety. Fit only on eligible historical data.
Alternatives considered: raw counts, a trained classifier, or buyer quotas.
Consequence: arithmetic is explainable; sparse data still limits confidence.
Weights were not tuned to make the holdout pass.

## 2026-09-21 — Use explicit data policies

Context: stated and computed ratios disagree; deal-type labels can conflict
with buyer type.
Decision: trust stated multiples and buyer type, report discrepancies, and
restrict valuation to Closed transactions. Use sponsor co-activity and financial
profile distance for adjacency; discount common rationale tags.
Alternatives considered: silently repair the source or discard adjacent sectors.
Consequence: assumptions are visible and the original CSV remains unchanged.

## 2026-09-21 — Keep three replay contracts distinct

Context: replaying a prior execution differs from reusing a response for a new request.
Decision: use content-addressed caching, frozen historical replay, and a
hash-checked portable archive with exact input/policy compatibility.
Alternatives considered: filename caching or an automatic paid fallback.
Consequence: changed inputs fail explicitly. Replay uses current validation;
it does not run old code or establish new generation quality.

## 2026-09-21 — Calibrate independent judges

Context: agreeing judges may share biases or disagree with a human.
Decision: isolate five dimensions, include Unknown, mask buyer identity for
identification, shuffle with a recorded seed, and use two provider families.
Require blind human votes first; report each judge against the human separately
from judge-versus-judge agreement.
Alternatives considered: a single broad score without reference labels.
Consequence: twenty pages from one rater are a small sanity check. Missing votes,
failed requests, or undefined intervals cannot become passing results.

## 2026-09-21 — Keep feedback local and interpretable

Context: a user may know a buyer is irrelevant.
Decision: atomically persist named exclusions and disclose the sector-profile
similarity discount on remaining same-type buyers. Keep it out of backtest scoring.
Alternatives considered: online retraining or an external database.
Consequence: the preference survives restarts, but is not measured predictive
improvement. At scale this needs transactional storage per user.

## 2026-09-21 — Leave unused infrastructure out

Context: the input is 500 structured rows and the interface is a local CLI.
Decision: use dataframe queries and JSON artifacts. Do not build a vector store,
routing classifier, database server, webhooks, MCP server, or custom frontend.
Alternatives considered: infrastructure for hypothetical consumers.
Consequence: future integrations need real access, retention, and workload
requirements. Typed tools and structured output provide extension points.
