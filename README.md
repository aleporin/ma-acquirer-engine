# M&A Acquirer Engine

Rank ten potential buyers from a transaction CSV and produce a cited rationale
for each. Python computes the ranking and financial facts; a tool-using analyst
writes the pages, with validation and bounded repair before rendering.

## Run it

Install [uv 0.12.17](https://docs.astral.sh/uv/getting-started/installation/), then
run from the repository root:

```sh
make run
```

This installs the locked dependencies and Python 3.12.14 if needed, then replays
recorded model responses **without an API key or provider calls**. Installation
needs internet. Use macOS, Linux, or WSL.

Open the printed `runs/ID/index.html`, or the committed
[sample report](sample_output/index.html). Each output directory contains ten buyer
pages, linked source evidence, Markdown copies, structured JSON, and replay traces.
Copy the whole directory to keep citation links working.

### Fresh generation and custom targets

Set `ANTHROPIC_API_KEY` in your environment, then explicitly select paid generation:

```sh
make run RUN_FLAGS=--fresh
uv run acquirers run --fresh --target examples/healthcare.yaml --ev 300 --margin 25
```

Target flags override YAML, which overrides defaults. `--ev` is USD millions;
`--margin` is percentage points. Other flags are `--sector`, `--geography`,
`--ownership`, and repeated `--tag`; [the example YAML](examples/healthcare.yaml)
shows the field names. The default archive only matches its recorded target and
policy: changed inputs fail replay explicitly, with no automatic paid fallback.
The application does not load `.env` files; [.env.example](.env.example) lists
credential names. Generation has a $10 reservation cap, not a promised bill.

### Compare, replay, and save preferences

```sh
# Free: compare rankings for two targets without drafting pages.
uv run acquirers compare examples/healthcare.yaml examples/healthcare_large.yaml

# Free: list saved runs and replay one with its original inputs.
uv run acquirers runs
uv run acquirers replay RUN_ID

# Exclude a buyer from subsequent rankings.
uv run acquirers flag "KKR" --reason "conflict"
```

Flags persist in ignored `state/feedback.json` and also discount similar same-type
buyers. Remove an entry to undo it, or move the file aside to restore defaults.
Changed feedback requires fresh generation; replaying a run ID uses its frozen
state. Use `uv run acquirers --help` or a command's `--help` for all options.

## How it works

1. **Select:** validate the CSV, derive historical buyer signals, score, and rank.
2. **Draft:** give each buyer its own evidence pack; the analyst chooses typed
   tools for additional evidence and writes a structured rationale.
3. **Validate and repair:** check citations, numeric claims, and selected prose
   patterns. Return errors for one repair; a failed page keeps an error banner.
4. **Render:** produce self-contained HTML and Markdown, with usage and replay data.

[`cli.py`](src/acquirer_engine/cli.py) → [`pipeline.py`](src/acquirer_engine/pipeline.py)
→ [`stages/`](src/acquirer_engine/stages). Pydantic AI supplies typed tool/output
contracts; Python owns scoring and recovery limits. The portfolio reviewer is
optional and disabled by default. [Architecture and decisions](docs/DECISIONS.md)
cover the execution flow, libraries, and alternatives.

## Results and limitations

| Measurement | Result |
| --- | --- |
| Selected live run | 10/10 pages, 54/54 final numeric claims; one repair |
| Time and returned usage | 48.18 seconds, $1.863930; under-$1 goal unmet |
| Keyless replay | 21 recorded responses, 10/10 pages, $0 new spend |
| Historical recall@10 | 38.0%, versus 40.8% global and 43.7% sector popularity |

The default target is a $200M regional healthcare-services company. Ranking uses
fixed, explainable rules on the supplied synthetic dataset and has not outperformed
popularity baselines. All ten default buyers receive Medium conviction. Numbers
and citations are checked automatically; banker-quality assessment remains
unmeasured. Rankings are repeatable, while fresh writing can vary. Replay reproduces
saved responses without API calls. [Evaluation results](docs/EVALS.md) contain the
methods and measurements; [design decisions](docs/DECISIONS.md) explain data policies.

## Development

```sh
uv sync --locked
uv run pre-commit install
make test
make lint
make eval RESULTS=/tmp/acquirer-eval
```

CI runs lint, types, size checks, the full test suite, keyless replay, and offline
eval layers 0–2. Tests reject network access. Settings, thresholds, model IDs, and
prices live in [`config/`](config/); prompts are versioned in [`prompts/`](prompts/).

Next: validate ranking on real transactions, collect independent banker labels,
and test quality/cost tradeoffs with matched runs. At higher volume, use queued
jobs and protected artifact storage, with identifier redaction and retention
controls for confidential traces. Structured JSON could support Salesforce;
Dagster and MCP are possible extensions once there is an actual workload.
