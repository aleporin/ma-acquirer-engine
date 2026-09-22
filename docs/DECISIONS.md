# Architecture decisions

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
Keep unreturned usage uncertain. Use the approved $3 generation admission cap;
retain the under-$1 measured-cost goal.
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
