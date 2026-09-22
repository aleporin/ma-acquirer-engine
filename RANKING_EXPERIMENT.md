# Testing alternative ranking weights

The product uses fixed shared feature weights, with buyer-specific historical
signals shrunk toward buyer-type priors. This optional experiment asks whether
different final weights for sponsors and strategics, or small buyer-specific
adjustments, improve historical buyer retrieval. It never edits product scoring
configuration or regenerates buyer pages.

## The protocol

The protocol is frozen in [ranking_experiment.yaml](config/ranking_experiment.yaml).

```text
Eligible history through 2018
    → anonymous aggregate packet
    → one recorded model request, at most three weight hypotheses
    → unchanged control + type-only and buyer-adjusted variants
    → chronological selection on 2019, 2020, 2021
    → freeze the winner before measuring 2022–2024
    → compare with shared weights and three popularity/random baselines
```

The proposal request contains 133 non-Rumored transactions summarized across all
60 observed buyers. There are no source rows, buyer or target names, transaction
IDs, or statistics from later years. Single-buyer summaries include sparse
histories; zero observed dispersion for a singleton does not establish a stable
preference. The request is a hypothesis-generation step, not learned optimal
weights or a claim about real investment mandates.

Every proposal specifies all eight feature multipliers for both buyer types.
Multipliers are bounded to 0.5–2 times the shipped weights, then normalized to
sum to one within each type. The unchanged shared control is always included.
Up to three proposals plus that control produce up to eight variants; this is
one bounded search, not eight independent ordinary runs.

For the buyer-adjusted variants, sector concentration, log-EV dispersion, and
margin dispersion modestly tilt the corresponding type weights. Reliability is
`n / (n + 20)`, and maximum tilt strength is 0.5 before renormalization. A buyer
with little history stays close to its type default. These are deliberately
constrained heuristics; they do not infer causal preferences or rejected deals.

Each selection fold trains strictly before its query year. Pooled recall@10
selects the winner, then full-list MRR breaks ties. Exact metric ties favor no
buyer adjustment, then the unchanged control, then lexical name. Type-only and
buyer-adjusted winners are also retained for comparison. Their final benchmark
results cannot change the selected winner.

All methods use the same historical candidate universe. An observed buyer absent
from training still counts as a miss. Reported metrics include recall@10, MRR,
nDCG@10, all selection trials, per-query ranks, and paired bootstrap intervals.
Intervals resample transactions and do not correct for buyer dependence or the
broader development process.

The 2022–2024 benchmark has already been inspected during development. Calling it
an untouched test set would be misleading. Results are exploratory and cannot
establish generalization to real deal data. Historical completed or announced
purchases also do not reveal the full set of considered or rejected buyers.

## Run and replay

```sh
# Paid: one proposal request, at most $0.50 reserved; zero retries.
uv run acquirers propose-weights --fresh

# Free: reproduce the exact saved proposal request from its recorded trace.
uv run acquirers propose-weights --source runs/weight-proposals/PROPOSAL_ID

# Free: chronological selection and frozen benchmark measurement.
uv run acquirers experiment-weights runs/weight-proposals/PROPOSAL_ID
```

The default proposal command requires `--source`; it has no paid fallback.
Fresh requests need the existing analyst provider credential in the environment.
Invalid model output fails without asking again. Request timeouts, cost limits,
raw responses, returned usage, and uncertain charges use the product's existing
recording boundary. Each attempt creates a new artifact directory.

`input.json` freezes configuration, prompt, aggregate packet, and source revision.
`proposal.json` records hypotheses, input hashes, usage, and failure status;
`trace.jsonl` retains the request and response for replay, including replay chains;
fresh requests also populate `cache/`. Experiments
write `experiment.json`, `provenance.json`, and `summary.md`. Changed history,
scoring configuration, experiment policy, or damaged input hashes are rejected.
These local integrity checks catch accidental mismatch; they are not signatures
against deliberate tampering.

## Follow the implementation

| Module under `evals/ranking/` | Responsibility |
| --- | --- |
| `packet.py` | Build reproducible anonymous statistics using early history only |
| `weighting.py` | Validate policy and complete profiles; normalize type and buyer weights |
| `proposals.py` | Request one typed hypothesis set using injected recorded resources |
| `experiment.py` | Fit chronological folds, select by a fixed objective, measure a frozen winner |
| `weight_command.py` | Assemble resources, check saved inputs, and write immutable artifacts |

Production `ranking/scorer.py` supplies the same feature signals to every
variant. The experiment changes only final weights. At larger scale, compute
feature matrices once per chronological fold and retain independent datasets
before considering a richer learned model. More parameters are not evidence of
better ranking.
