# M&A Acquirer Engine

Turn a transaction CSV into ten ranked buyers and an evidence-linked rationale
for each. Python computes the facts, ranking, and conviction; a bounded analyst
stage retrieves evidence and writes the prose. The deliverable opens in a browser.

The core is the ranking → evidence → draft → verify → report path. Evaluation
received extra investment to make failures, costs, and iteration inspectable.
Custom targets, saved buyer exclusions, and comparison are optional extensions.
This is a prototype with measured limits, not a production underwriting model.

## Run without an API key

Install [uv 0.12.17](https://docs.astral.sh/uv/getting-started/installation/), then,
from the repository root:

~~~sh
make run
~~~

The command installs locked dependencies and Python 3.12.14 if needed, then
replays an actual recorded model conversation through the current tools and
validation. Installation needs internet; replay makes no provider calls.
macOS and Linux are supported; Windows needs a Linux environment such as WSL.

Open the printed `runs/ID/index.html` path. Each run also writes ten Markdown
buyer pages, structured `run.json`, an input snapshot, and a replay trace.
The HTML contains ten buyer sections plus an index and evidence appendix;
browser printing can use more than ten sheets. You can also open the committed
[sample report](sample_output/index.html) immediately.

See [report, target, and comparison commands](REPORTING.md),
[the demo walkthrough](docs/DEMO.md), and [follow one run in code](EXECUTION.md).

## What the measurements say

| Question | Observation |
| --- | --- |
| Does the complete live pipeline work? | Latest recorded run: 10/10 verified pages, 54/54 final numeric claims; one page repaired |
| How fast and costly was it? | 48.18 seconds and $1.863930 returned usage; the under-$1 goal remains unmet |
| Does replay reproduce it? | All 21 recorded responses; 10/10 pages; $0 new provider spend |
| Does ranking beat simple popularity? | Recall@10 is 38.0%, versus 40.8% global and 43.7% sector popularity; no demonstrated lift |
| Are ranks stable? | Identical top ten and convictions across five deterministic runs |
| Are the pages banker-ready? | Independent judge/human calibration is not yet measured |

These observations come from committed artifacts, not illustrative outputs.
[Evaluation results and the iteration trail](docs/EVALS.md) explain denominators,
confidence intervals, live versus replay evidence, and unfinished gates.
The saved live run was selected after multiple correction iterations and checked
against its source evidence. It is not an unbiased reliability estimate, a latency
distribution, or independent banker calibration.

## How it works

1. **Validate and rank.** Load the CSV, fit buyer features, shrink sparse signals
   toward the buyer-type prior, and select the top ten with fixed tie-breaks.
2. **Prepare evidence.** Each buyer receives a bounded pack of its own history,
   score components, target assumptions, and code-computed conviction.
3. **Retrieve and draft.** The analyst chooses among five typed evidence tools.
   Closed valuation comps must be retrieved; the initial pack cannot satisfy that check.
4. **Check and recover.** Validate the schema, citations, numeric claims, and prose
   numbers, plus narrow margin-comparison and partial-evidence scope checks.
   Return precise errors for one same-tier repair under the shipped configuration.
   A failed buyer retains an error banner while the others finish.
5. **Render and retain.** Write escaped HTML, Markdown, JSON, usage, and replay
   records. Internal working notes stay in JSON and never appear on the buyer pages.

The first response warms the shared prompt prefix, then buyer tasks run
concurrently. Provider clients, the ledger, cache, and logger are constructed
once and injected. The optional portfolio reviewer is disabled by default:
in a historical matched observation it changed no pages, while adding cost.
The shipped primary uses the stronger configured model; escalation is disabled.

Prompts separate task rules, output schema, and delimited untrusted data.
Model-written answers determine tool use; deterministic validation determines
whether to accept, repair, escalate, or stop. This is a workflow with bounded
agent stages. [Architecture decisions](docs/DECISIONS.md) explain the choices,
including the typed Pydantic AI boundary and why there is no application server.

## Code entry points

Start with [`cli.py`](src/acquirer_engine/cli.py), then
[`pipeline.py`](src/acquirer_engine/pipeline.py). The workflow is visible in four
stage files: [`select.py`](src/acquirer_engine/stages/select.py) →
[`draft.py`](src/acquirer_engine/stages/draft.py) →
[`review.py`](src/acquirer_engine/stages/review.py) →
[`render.py`](src/acquirer_engine/stages/render.py). Review is optional.

[`factory.py`](src/acquirer_engine/factory.py) constructs shared resources before
model stages receive required `RuntimeDeps`. The [execution map](EXECUTION.md)
connects the stages to data, ranking, evidence, replay, and the ten model-support
modules. Evaluation enters separately through [`evals/command.py`](evals/command.py).
The structure changes no measured result or model behavior described above.

## Assumptions and limits

- Default target: Healthcare Services, $200M EV, Private, Regional. Strong margin
  means the eligible sector's upper-tercile boundary. The primary size band scales
  with target EV from 0.5× to 2×; there is no invented regional location.
- The 500-row dataset is synthetic. Stated multiples are canonical despite
  403 ratio discrepancies; margin discrepancies affect 362 rows.
  Buyer type takes precedence over inconsistent deal-type labels.
- Rumored rows do not influence fitting. Closed deals alone support valuation.
  Pending outcomes are excluded from the completion-rate denominator.
- Adjacent-sector activity broadens sparse evidence, and common rationale tags
  receive less weight. There is no forced sponsor/strategic quota.
- All default top-ten convictions are Medium under the fixed thresholds.
  Diversity is diagnostic; labels are not changed to manufacture a spread.
- Verification proves numeric/reference consistency. It cannot prove economic
  causation, current buyer appetite, or the quality of a qualitative thesis.
  Outside-dataset notes are visibly labeled unverified.
  Cited source tables expose stated EV, multiples, margin, and transaction context.
  The earlier margin error was corrected; narrow guards do not establish general
  qualitative accuracy. [The evaluation guide](docs/EVALS.md) records that boundary.
- Live prose may change even at identical inputs. Ranking and facts are
  deterministic; versioned caches and frozen transcripts reproduce recorded responses.
  Replay does not measure a new prompt's quality or new provider latency.
- Real deal data would require access controls, a reviewed retention agreement,
  encrypted artifact storage, and identifier redaction. Local traces contain
  full conversations and should be treated as confidential.

## Commands and development

~~~sh
uv sync --locked
make test
make lint
make eval RESULTS=/tmp/acquirer-eval
uv run pre-commit install
~~~

The tests use local models and reject network access. CI runs lint, types, size
checks, the full test suite, keyless report replay, and offline evaluation layers
0–2. Green CI does not mean human calibration or live performance targets passed.
The pinned lockfile and YAML settings define the runtime; model IDs, dated prices,
thresholds, and budgets are configuration rather than Python constants.

~~~sh
# Free: compare two targets without drafting new pages.
uv run acquirers compare examples/healthcare.yaml examples/healthcare_large.yaml

# Free: inspect and replay a previously saved local run.
uv run acquirers runs
uv run acquirers replay RUN_ID

# Free: inspect the judge plan; no clients are constructed.
make eval-judges
~~~

Fresh generation requires `ANTHROPIC_API_KEY` in the environment and explicit
`--fresh`. Independent judging uses `OPENAI_API_KEY` and `GEMINI_API_KEY`.
The application does not read dotenv files; [.env.example](.env.example) lists
empty variable names. Keep real keys outside the repository.

~~~sh
# Paid generation, only when spending is intended.
make run RUN_FLAGS=--fresh
~~~

The generation admission cap is $10; it is distinct from the under-$1 measurement
goal. Reservations account for worst-case tokens and SDK retries. Missing returned
usage remains an uncertain charge, never an invented zero.

[REPORTING.md](REPORTING.md) covers custom targets and persisted flags.
[JUDGING.md](JUDGING.md) covers blind labels, separate paid judging, and replay.
[ROUTING.md](ROUTING.md) records recovery and ablation evidence.

## What I would improve next

First, collect independent banker labels and measure agreement, then test the
current model/prompt with matched controls and reduce cost using paired runs. Validate ranking on real, permissioned
transactions before tuning it to this synthetic holdout.

At higher volume, persist immutable runs in object storage and use queued jobs.
Dagster could coordinate data refresh and evaluation. The structured `run.json`
contract could serve a Salesforce component without changing scoring or validation;
typed evidence tools could be exposed over MCP when there is an actual client.
Those integrations are intentionally not implemented.

For review, start with the [demo](docs/DEMO.md), [execution map](EXECUTION.md), and
[decision records](docs/DECISIONS.md). The [submission guide](docs/SUBMISSION.md)
identifies the evidence and the remaining human checks.
