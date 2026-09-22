# M&A Acquirer Engine

Rank likely acquirers from transaction history and measure the ranking against
held-out deals. The current scope is **Phase 6: portable reports and target inputs**.
Run `make run` with no API keys to produce the ten-buyer report, or open
[sample_output/index.html](sample_output/index.html). See [report commands](REPORTING.md).
The independent judge harness and [blind packet](JUDGING.md) are ready; live judging is pending. Review is now
configuration opt-in. The latest default run verified ten pages and 79/79 claims
in 72.65 seconds for $1.02, with three successful repairs and no budget denials.
The 60-second target remains unmet. Historical replay reproduces all 27 responses
and page outcomes for $0. See [routing and results](ROUTING.md).

The initial ranker has recall@10 of 38.0%, versus 40.8% for global popularity,
43.7% for sector popularity, and 12.7% for a seeded random baseline. Its recall
lift over both popularity baselines has a 95% interval containing zero. These
are measurements on synthetic data, not a claim of predictive superiority.

The assignment top ten are stable across five runs and all receive Medium
conviction under fixed thresholds. Diversity is a reported diagnostic; it does
not force labels or fail the gate. Identical ranks and convictions remain required.

## Setup and commands

Install [uv 0.12.17](https://docs.astral.sh/uv/getting-started/installation/), then
run from the repository root:

```sh
uv sync --locked
make lint
make test
make eval
```

uv downloads the pinned Python 3.12.14 interpreter if needed. Dependencies are
locked in `uv.lock`. Installation needs internet access; tests and evaluation
make no provider calls and need no keys.

For development:

```sh
source .venv/bin/activate
pre-commit install
pre-commit run --all-files
```

Checks include Ruff, strict mypy, file/function size limits, and private-key
detection. Unit-test fixtures reject socket connections.

| Command | Behavior |
| --- | --- |
| `make test` | Run the complete offline behavioral suite |
| `make lint` | Check formatting, lint, types, and size limits |
| `make eval` | Write measured layers 0–2 and ranking stability in 5; fail on unmet gates |
| `make eval EVAL_FLAGS=--ci RESULTS=/tmp/ci-results` | Select layers 0–2 for offline CI |
| `make eval-diff A=before.json B=after.json` | Show metric changes and flag regressions |
| `make eval-judges` | Print the free judge cost plan; explicit `--fresh` permits paid calls |
| `make run` | Replay the committed archive into linked HTML, ten Markdown pages, and JSON |
| `make run RUN_FLAGS=--fresh` | Make paid analyst calls and refresh the response cache |
| `acquirers eval --analyst-run runs/ID/run.json` | Measure a saved run without provider access |
| `acquirers runs` | List saved run IDs, outcomes, source, prompt, cost, and latency |
| `acquirers replay RUN_ID` | Replay one archive with its saved inputs and responses |
| `acquirers flag BUYER --reason REASON` | Persist a buyer exclusion and similarity preference |
| `acquirers compare a.yaml b.yaml` | Compare two rankings offline and save a side-by-side report |

Evaluation is offline. For repeat evaluations, supply a new `RESULTS` directory;
existing baseline directories are never overwritten.

## Ranking and assumptions

The default target is Healthcare Services, $200M EV, private, and regional. Its
margin is the sector's upper-tercile boundary in eligible history. The primary
size band scales with EV (0.5–2x), with a wider declining band (0.25–4x).
Regional geography has no invented location; National and Multi-Regional buyer
footprints receive expansion credit.

The loader validates all fields, asserts the redundant sub-sector matches its
sector, removes that column, and rejects duplicate identities or conflicting
buyer types. Stated multiples remain canonical. The quality report records 403
multiple discrepancies, 362 margin discrepancies, 57/52 sponsor/strategic deal-type
conflicts, ten rumored deals, and 94 expected null close times.

Rumored transactions are excluded from fitting. Completion is Closed divided by
Closed + Withdrawn + Terminated; pending deals do not enter that denominator.
Valuation summaries use Closed transactions only. Acquirer type is authoritative;
deal type receives a small scoring weight.

Sector adjacency blends sponsor co-activity cosine with distances between sector
financial profiles. Adjacent-sector contributions are discounted. Inverse document
frequency reduces common rationale tags to little or no signal.

Each buyer gets bounded sector, size, activity, completion, margin, tag, geography,
and deal-type signals. Signals shrink toward the empirical mean of that buyer type
using a configurable prior strength. Weighted contributions sum to the base score. Product-only saved feedback can
apply a separate, disclosed similarity penalty; it does not change the backtest.
Names resolve ties; there is no strategic/sponsor quota. Conviction depends on the
score and relevant-history count, independently of other buyers' assigned levels.

## Evaluation and limits

The split is fixed: 358 transactions through 2021 form the training population;
all 142 transactions from 2022–2024 are test queries. Training removes rumored
rows before fitting every transform, candidate identity, and prior. There are
93 eligible historical candidates and 17 test labels absent from that universe.
Those labels remain misses in every method's denominator.

Queries use target sector, EV, margin, geography, and prior ownership. Held-out
buyer names, outcomes, deal types, and post-deal rationale tags are not features.
Using observed transaction EV still makes this a retrospective test; synthetic
assignment and sparse histories limit what the scores can demonstrate.

Metrics are recall@10, full-list MRR, and nDCG@10 with one relevant buyer per query.
Every method uses the same population and candidate universe. Paired bootstrap
intervals resample transactions with a fixed seed; they are not clustered by
buyer. Random baseline shuffles use the seed and query identity. Every feature
group is also removed once, with remaining weights renormalized. Initial weights
and conviction boundaries were fixed before examining the holdout and have not
been adjusted to make the measured results pass.

Layer 0 executes isolated data, feature, ranking, evidence, validation, and analyst tests and
reads their JUnit/coverage artifacts. `make test` covers the complete suite.
Layer 1 passing means its measurements completed; it does not mean positive lift.
Layer 5 requires ranking identity and conviction agreement across five runs and
reports conviction diversity separately. With saved analyst runs, it also measures the
fraction of buyers whose pages validate in all five executions. Repeat
`--analyst-run` for each distinct artifact; duplicate run IDs are rejected.
Replay repetition measures reproducibility, not live model stochasticity.

Layer 3 measures pairwise word-ngram Jaccard similarity on accepted pages. A
passing status means measurement completed, not that prose quality is established.
Phase 5 adds name-masked identification and calibrated rubric judges from saved
judge archives; see [execution, labeling, and limits](JUDGING.md).
Layer 6 records observed tokens, cache usage, USD, empirical latency percentiles,
and tool-selection rates by buyer type. Every metric is prefixed by execution
mode. With no supplied run artifacts, layers 3 and 6 remain unmeasured stubs.

Each result bundle under [evals/results](evals/results/) contains:

- `scorecard.json` and `summary.md`: provenance, selected layers, metrics, and statuses.
- `backtest.json`: split counts, per-query ranks, baselines, paired intervals, and ablations.
- `data_quality.json`: measured source discrepancies.
- `top10.json`: ordered buyers, conviction, and each score's arithmetic.
- `groundedness.json`: fixture identity, expected errors, and observed verifier outcomes.

Source revision, dirty state, run ID, UTC time, configuration digest, and seed are
recorded. Committed baselines come from clean source; their source commit precedes
the separate `eval(pN):` artifact commit. Logs stay local under `runs/`.
CI checks the latest tracked ranking snapshot; intentional identity changes need
a `ranking:` marker in an intervening commit message. CI selects layers 0–2, so
green CI does not imply live generation or the Phase 4 ablation gate passed.

## Evidence and rationale validation

A core pack contains only the buyer's eligible own-history rows, score breakdown,
code-computed conviction, and target assumptions. Stable transaction IDs address
rows; `stat:<name>:<scope>` IDs address computed numbers. Aggregates use the full
eligible buyer history even when the displayed rows are truncated. Recent rows
come first, with transaction IDs breaking ties. The row cap and conservative
UTF-8 byte bound both apply; fixed context that cannot fit raises `EvidenceError`.
This bound covers serialized pack content, not prompts, tool schemas, or measured
provider token usage.

The ordered rationale schema puts internal reasoning first, requires at least two
categorized risks with evidence or an explicit judgment marker, and applies YAML
length caps. Validation requires its configuration as Pydantic context. The
verifier checks every claim's ID, numeric metric, and canonical value. Counts and
years must match exactly; continuous values allow the configured rounding error.
Prose numerals must appear in claims, including years and ranges. Currency units
are normalized to millions; percentages and multiples must use matching metrics.
Rounding must fit both the displayed precision and the canonical-unit tolerance.
Labeled outside notes are excluded from groundedness checks.

Valuation must cite separately retrieved Closed transactions and explicit claims
for their stated EV/EBITDA and EV/Revenue multiples. Core rows alone cannot satisfy
that requirement. Conflicting copies of an evidence ID fail instead of overwriting
facts. Conviction must match the ranker's result.

Layer 2 runs three hand-written valid pages and six planted-invalid pages. Saved
analyst runs add first-pass numeric claim and whole-page acceptance rates; they
do not replace the fixture results. A schema failure has no parsed claims and is
reported separately, never counted as a perfect claim rate. First-pass, post-repair,
and post-review rates remain separate. The verifier catches numeric and reference errors; it does not prove
that prose attaches a valid number to the right subject, that a selected comp is
economically persuasive, or that a qualitative thesis is true. Those limitations
remain for later evaluation and human review. The fixtures contain synthetic
examples, not generated analyst pages.

## Structure and configuration

Start with the [execution walkthrough](EXECUTION.md). `data/` validates input;
`ranking/` owns target profiles, signals, priors, and ordering. `evals/ranking/`
owns holdout measurement. `evals/phase1.py` composes graders and companion artifacts.
`evidence/` assembles addressable facts; `validation/` checks structured rationale.
`evals/grounded.py` executes labeled pages and `evals/phase2.py` adds their results.
`cli.py` registers commands; `run_command.py` builds settings and a logger; `pipeline.py` coordinates
the portfolio. `bootstrap.py` owns shared resource construction and client lifetime.
`llm/analyst.py` contains the buyer recovery loop; `llm/agents.py` declares typed
agents. `llm/context.py` holds page state and `llm/batch.py` schedules buyers.
`evals/command.py` assembles eval commands. A fresh run owns one SDK client,
agent, cost ledger, cache, and trace writer, passed through `Deps`. Each buyer owns
only its tool evidence and validation state. `llm/` contains those boundaries;
`evals/phase3.py` measures saved run artifacts without contacting providers.

PyYAML parses configuration files and Pydantic validates them:
`models.yaml` records dated provider metadata; `scoring.yaml` contains all tunable
ranking policy and target assumptions; `eval.yaml` selects layers and controls
splits, uncertainty, and size limits; `evidence.yaml` controls context budgets,
section lengths, rounding tolerance, and banned phrases. `analyst.yaml` controls
tool rounds, rows, output tokens, concurrency, timeouts, and measurement policy.
`judges.yaml` controls separate judge execution and calibration. `feedback.yaml`
sets the preference discount; `comparison.yaml` bounds an optional summary. Model metadata
does not establish account access or tested live behavior.

Maintained files stay below 300 lines and Python functions below 50. Generated
artifacts, lockfiles, and the unchanged transaction CSV are exempt. GitHub Actions
runs lint, tests, and offline CI evaluation and uploads the generated scorecard.

## Analyst execution

This is a workflow with a bounded agent stage: code ranks the buyers, each analyst
chooses evidence tools, and code verifies the output. Five typed queries expose
comps, sector benchmarks, adjacent activity, sponsor platforms, and failed deals.
Returned rows are capped, with truncation explicit. Only actual tool returns
enter the verifier's retrieval context. Dataset strings are cleaned and escaped
inside delimited data blocks; they cannot supply application instructions.

The first buyer response warms the shared instruction/tool prefix before the
remaining buyers start behind a semaphore. Tool use is capped at three rounds per page;
each generation permits at most four model requests. The request deadline is now 120 seconds, including
SDK retries with backoff and jitter for transient failures. The run performance
target remains 60 seconds; a slower completed run still fails that criterion.
The larger safety ceiling lets slow responses finish for quality measurement;
it is not evidence that live latency or page quality has improved.
A failed page records errors and does not cancel other buyers; the command exits
nonzero if any page fails.
Phase 4 adds recovery, portfolio review, and a conservative configured USD cap.

The final output tool requests strict structured output with the provider's
supported schema subset. Full schema, length, risk-reference, and claim checks
still run locally; unsupported provider constraints remain local requirements.
The generation schema separates evidence risks, which require references, from
judgment risks, which omit references. Stored judgments have an empty list.
The output allowance is 4,000 tokens; the latest complete live run peaked at
2,529 with no truncated responses. The versioned prompt
asks for a concise page that leaves room for its claims. Responses that end at the token limit are
recorded with usage, then rejected explicitly, even if their partial arguments
can be parsed. Schema failures retain field-level reasons without raw inputs.

`runs/ID/run.json` contains page outcomes and per-response usage; `trace.jsonl`
retains full model/tool observations for local inspection. Structured diagnostics
go to stderr and `log.jsonl`, without raw CSV rows or prompts at info level.
`attempt` numbers framework requests within a page, not hidden SDK HTTP attempts.
The ledger subtracts cache reads/writes from total input before applying dated
prices. A live zero-token response fails. Replay retains historical token counts
but records zero new spend. Billing for unsuccessful requests without returned
usage is unknown; the ledger does not invent it.

Fresh execution needs `ANTHROPIC_API_KEY` in the environment. Default `make run`
checks a committed response archive against the selected inputs and policy, then
replays its conversation through current verification. No paid fallback exists.
Without a portable bundle, matching request-cache entries can be replayed. Cache identity
includes configuration, prompt, schema, evidence, and tool results. Fresh execution
replaces matching cache entries. The curated archive is in `cache/replay/`.

Each new run writes `snapshot.json` before model requests: settings, prompt,
prepared buyer evidence, and tool-query history. No credentials are included.
`acquirers replay RUN_ID` reads that snapshot and the original trace, independently
of the current configuration, CSV, prompts, or shared cache. Use the full ID from
`acquirers runs`. It reruns current tools and validation, checking each conversation
against the original request before returning its saved response. Typed request
failures replay as their original errors. Older budget/timeout failures are
recovered only from explicit validation or reviewer records for a missing response.
Unexplained gaps and changed conversations fail. Rejected drafts stay available.

Replay writes a new run with `replay_of`, original source SHA, executing SHA, and
zero new spend. `source_dirty` marks uncommitted executing code (`*` in the listing).
Original files are preserved. Outcomes may change with verifier improvements;
replay does not reproduce old code or measure a new prompt's generation quality.
Older runs need an input snapshot; reconstructed snapshots are labeled explicitly.

The pinned model does not support temperature; the setting is null and omitted.
Prose can vary between fresh runs. Only cache replay reproduces a saved response,
and replay still executes tools and validation. Unit tests use local models and
a fake HTTP transport, including a hostile input and full-conversation replay.

The [routing results](ROUTING.md) link the measured controls and explain the
remaining limits. Every earlier failed measurement is retained under
[evals/results](evals/results/); later success does not replace those artifacts.
