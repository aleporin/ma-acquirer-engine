# Recorded replay walkthrough

This demonstration uses the shipped response archive. It makes no provider calls,
and its speed is replay speed. The original live run took 72.65 seconds.

## Reproduce the same flow

~~~sh
make run
uv run acquirers compare examples/healthcare.yaml examples/healthcare_large.yaml
~~~

Open the paths printed by those commands. The ten-buyer report and comparison
table are self-contained HTML files.

## What to notice

1. The run finishes with ten verified pages and a saved run ID.
2. The report index has ten ranked buyers, their scores, and code-computed conviction.
3. One buyer page includes its thesis, named precedents, valuation context,
   at least two risks, and a conviction explanation.
4. Citation links lead to transaction or computed-statistic evidence.
5. The footer separates replay's zero new spend from historical live cost and latency.
6. Comparison computes overlap and rank movements without another draft request.

## A short spoken explanation

“The ranking is computed from the CSV, so the model cannot invent a buyer's score.
Each analyst starts with that buyer's own history and chooses tools for additional
evidence. The verifier checks its references and numeric claims; failures receive
specific feedback for a bounded repair. This report reproduces a saved model
conversation without needing a key.”

“The latest live run completed ten pages, but took 72.65 seconds. The ranker has
not beaten popularity on the synthetic holdout, and independent human/judge
calibration is still unfinished. Those limits are in the scorecards.”

## Follow-up questions to practice

- Why shrink sparse buyer signals toward a type prior?
- Which data can affect ranking, and how does the temporal split prevent leakage?
- What happens when a provider times out or a draft invents a number?
- Why are tool results required for valuation rather than supplied in the core pack?
- What exactly does replay reproduce, and what can change under a new verifier?
- Why is the portfolio reviewer opt-in?
- Why can numeric validation pass while the economic thesis remains weak?
- How would you isolate users, redact identifiers, and store traces at higher volume?

Use [the execution map](../EXECUTION.md), [decision records](DECISIONS.md),
and [evaluation evidence](EVALS.md) to check each answer against the implementation.
