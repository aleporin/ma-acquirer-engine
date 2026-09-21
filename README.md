# M&A Acquirer Engine

Rank likely acquirers from transaction history and measure the ranking against
held-out deals. The current scope is **Phase 1: data, deterministic ranking, and
offline evaluation**. Rationale generation and live judging are not implemented.

The initial ranker has recall@10 of 38.0%, versus 40.8% for global popularity,
43.7% for sector popularity, and 12.7% for a seeded random baseline. Its recall
lift over both popularity baselines has a 95% interval containing zero. These
are measurements on synthetic data, not a claim of predictive superiority.

The assignment top ten are stable across five runs, but all receive Medium
conviction under the initial fixed thresholds. The intermediate requirement of
two unforced levels is **not met**. Default evaluation writes its results and
exits nonzero to expose that unmet gate.

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
| `make eval` | Write measured layers 0, 1, and ranking stability in 5; fail on unmet gates |
| `make eval EVAL_FLAGS=--ci RESULTS=/tmp/ci-results` | Select layers 0–2 for offline CI |
| `make eval-diff A=before.json B=after.json` | Show metric changes and flag regressions |
| `make eval-judges` | Report unavailable without making calls |
| `make run` | Report that rationale generation is unavailable |

The installed `acquirers` command exposes these commands. `eval --fresh` is
unavailable. To repeat an evaluation at the same revision, supply a new `RESULTS`
directory; existing baseline directories are never overwritten.

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
using a configurable prior strength. Weighted contributions sum to the score.
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

Layer 0 executes isolated data, feature, ranking, and ranking-config tests and
reads their JUnit/coverage artifacts. `make test` covers the complete suite.
Layer 1 passing means its measurements completed; it does not mean positive lift.
Layer 5 measures ranking identity and conviction agreement across five runs, plus
the intermediate two-level gate. Rationale stability remains unimplemented.
Layers 2, 3, 4, and 6 retain explicit `not_implemented` statuses and empty metrics.

Each result bundle under [evals/results](evals/results/) contains:

- `scorecard.json` and `summary.md`: provenance, selected layers, metrics, and statuses.
- `backtest.json`: split counts, per-query ranks, baselines, paired intervals, and ablations.
- `data_quality.json`: measured source discrepancies.
- `top10.json`: ordered buyers, conviction, and each score's arithmetic.

Source revision, dirty state, run ID, UTC time, configuration digest, and seed are
recorded. Committed baselines come from clean source; their source commit precedes
the separate `eval(pN):` artifact commit. Logs stay local under `runs/`.
CI checks the latest tracked ranking snapshot; intentional identity changes need
a `ranking:` marker in an intervening commit message. CI selects layers 0–2, so
green CI does not imply the separate Phase 1 conviction exit criterion passed.

## Structure and configuration

`data/` owns validation and quality counts; `features/` owns fitted history;
`ranking/` owns target profiles, signals, priors, and ordering. `evals/ranking/`
owns holdout measurement. `evals/phase1.py` composes graders and companion artifacts.
The CLI builds one settings snapshot and logger, passed through minimal `Deps`.
No provider clients exist in this phase.

PyYAML parses the three configuration files and Pydantic validates them:
`models.yaml` records dated provider metadata; `scoring.yaml` contains all tunable
ranking policy and target assumptions; `eval.yaml` selects layers and controls
splits, uncertainty, and size limits. Model metadata does not establish account
access or tested live behavior. Provider SDKs are deferred until used.

Maintained files stay below 300 lines and Python functions below 50. Generated
artifacts, lockfiles, and the unchanged transaction CSV are exempt. GitHub Actions
runs lint, tests, and offline CI evaluation and uploads the generated scorecard.
