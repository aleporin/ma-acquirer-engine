# M&A Acquirer Engine

A command-line project for dataset-grounded acquirer analysis.

**Current scope: Phase 0, scaffold and evaluation harness.** All seven evaluation
layers report `not_implemented`. There is no ranking or rationale generation yet,
and a successful evaluation process is not a claim that product quality passes.

## Setup and commands

Install [uv 0.12.17](https://docs.astral.sh/uv/getting-started/installation/), then
run these commands from the repository root:

```sh
uv sync --locked
make lint
make test
make eval
```

The pinned Python 3.12.14 interpreter is downloaded by uv if needed. Python
dependencies are locked in `uv.lock`. Initial dependency installation needs
internet access; the tests and evaluations make no provider calls and need no keys.

For development, activate the environment and install standard pre-commit checks:

```sh
source .venv/bin/activate
pre-commit install
pre-commit run --all-files
```

Checks include Ruff, strict mypy, file/function size limits, and private-key
detection. Tests block socket connections in their process.

| Command | Phase 0 behavior |
| --- | --- |
| `make test` | Run offline behavioral tests |
| `make lint` | Check formatting, lint, types, and size limits |
| `make eval` | Write the seven-layer stub baseline |
| `make eval EVAL_FLAGS=--ci RESULTS=/tmp/ci-results` | Select layers 0–2 for offline CI |
| `make eval-diff A=before.json B=after.json` | Print metric changes; exit nonzero for regressions |
| `make eval-judges` | Report unavailable and fail without making calls |
| `make run` | Report unavailable and fail without making calls |

The installed `acquirers` command provides the same `eval`, `eval-diff`,
`eval-judges`, and `run` commands. Run `uv run acquirers --help` for options.
Phase 0 rejects `acquirers eval --fresh`.

## Evaluation artifacts

An evaluation writes:

```text
evals/results/p0-<full evaluated git SHA>/scorecard.json
evals/results/p0-<full evaluated git SHA>/summary.md
runs/<run ID>/log.jsonl
```

JSON scorecards include the evaluated revision, whether the checkout was dirty,
run ID, UTC timestamp, configuration digest, seed, prompt version, model metadata,
layer selection, and results. A scorecard made from dirty source is exploratory;
committed baselines are generated from clean source.

Results are written together and existing revision directories are never
overwritten. For another run at the same revision, choose a different output root:

```sh
make eval RESULTS=/tmp/acquirer-eval-repeat
```

Every scorecard retains all seven layer identities. `selected` distinguishes
requested offline layers from layers not requested. The default selection is
0–3 and 5–6; CI selects 0–2. Layer 4 is never called in Phase 0, but remains
visible as `not_implemented`. Layer 0 is also a stub; actual scaffold tests run
through `make test`.

Unimplemented layers have empty metric dictionaries. Comparisons do not
interpret missing measurements as zero: they distinguish newly added metrics,
removed metrics, changed statuses, and direction-aware numeric deltas.
Configuration changes are labeled so deltas are not mistaken for causal evidence.

Baseline history lives under [evals/results](evals/results/). Each baseline has a
separate `eval(p0):` commit; its source revision precedes the artifact commit.

## Structure

| Module | Responsibility |
| --- | --- |
| `src/acquirer_engine/cli.py` | Arguments, run identity, dependency construction, and exit status |
| `settings.py` | Safe YAML loading and typed configuration |
| `logging_setup.py` | Isolated JSON logging to stderr and a run file |
| `deps.py` | Shared settings and logger references |
| `errors.py` | Typed application failures |
| `evals/harness.py` | Offline layer selection and scorecard assembly |
| `evals/graders/` | One explicit placeholder per evaluation layer |
| `evals/scorecard.py` | Artifact schemas, validated reads, and publication |
| `evals/diff.py` | Metric and status comparison |
| `scripts/check_lengths.py` | Maintained-file and Python-function size checks |

State is constructed at the command boundary and passed through `Deps`.
There are no provider clients in this phase. Harness inputs supply run metadata,
so grading does not read the clock or generate random identifiers.

## Configuration and limits

PyYAML 6.0.3 safely parses YAML; Pydantic validates each boundary and rejects
unknown configuration keys. The three configuration files are loaded once per run:

- `config/models.yaml`: provider IDs, standard USD token prices, context bands,
  cache rates, verification dates, and vendor source URLs.
- `config/scoring.yaml`: explicitly unset ranking weights.
- `config/eval.yaml`: layer identities, selections, seed, and size limits.

Model metadata is a dated reference, not proof of account access or stable model
behavior. One judge identifier is a preview version. No credentials are loaded,
and no live model behavior has been tested. Provider SDKs and the agent framework
will be added only when their stages use them.

Maintained text files are limited to 300 physical lines and Python functions to
50, including decorators and docstrings. Generated artifacts, lockfiles, and
the transaction CSV are exempt. The dataset is copied unchanged; its schema,
quality checks, ranking assumptions, and backtests belong to the data phase.

GitHub Actions runs lint, tests, and offline evaluation on pushes and pull
requests. The workflow uploads its scorecard as an artifact. Runtime logs are
local and ignored by Git; scorecard baselines are committed deliberately.
