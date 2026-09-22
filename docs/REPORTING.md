# Reports and target inputs

From the repository root, run:

```sh
make run
```

This installs the locked environment if needed and replays the committed ten-buyer
archive without an API key. Open the printed `runs/ID/index.html` path in a browser.
The report is a single HTML file with inline styles, no scripts, fonts, CDN, or
server dependency. Browser Print can save a PDF; pagination depends on browser and
paper settings. The deliverable contains ten buyer sections, an index, and an
appendix, not a promise of exactly ten printed sheets.

Each run also writes `buyers/01.md` through `buyers/10.md`, plus `run.json`,
`snapshot.json`, `trace.jsonl`, and diagnostics. Markdown citations link back to the
HTML appendix. Copy the entire output directory to preserve those links. The
[committed sample](../sample_output/index.html) opens directly after cloning.

The visible pages omit internal working notes. `run.json` remains the full
structured contract, including those notes; it is intended for inspection or a
future API adapter. Failed pages display their errors instead of draft prose.
Outside-dataset notes are labeled unverified. The archived metadata has no recorded
training cutoff, so the report says so rather than inventing a date. The footer
separates this replay's zero new spend and measured execution time from the
original live run's spend and latency.

## Change the target

Use a partial YAML file, command-line flags, or both. Precedence is configured
defaults, then YAML, then explicitly supplied flags:

```sh
uv run acquirers run --target examples/healthcare.yaml --ev 300 --margin 25
```

Available flags: `--sector`, `--ev` (USD millions), `--margin` (percentage points),
`--geography`, `--ownership`, and repeated `--tag`. YAML uses the `TargetProfile`
field names: `sector`, `deal_size_mm`, `ebitda_margin_pct`, `geography`, `ownership`,
and `tags`. `tags: []` explicitly clears the default tags. Omitted margin uses the
configured quantile of eligible transactions in the selected sector. A sector
with no observations requires an explicit margin. No buyer identity is inferred
from an unfamiliar sector label.

The bundled archive matches the default target only. Changing the target,
feedback, prompt, or execution policy causes a clear replay mismatch; it never
silently shows old pages or falls back to a paid request. The command above thus
illustrates target input and will fail against the bundled cache. To draft a new
profile, explicitly add `--fresh` and supply `ANTHROPIC_API_KEY` in the environment.
That makes paid requests. To replay an existing local run's original assumptions,
use `uv run acquirers replay RUN_ID`; it ignores current target and feedback state.

## Save buyer feedback

```sh
uv run acquirers flag "KKR" --reason "conflict"
```

Names match dataset identities without case sensitivity. Feedback lives in ignored
`state/feedback.json`, survives commands, and is saved atomically under a local
file lock. Repeating a flag updates its reason. Unknown names and malformed saved
state fail explicitly. Remove a flag from the JSON's `flags` list to undo it, or
move the state file aside to return to the unfiltered default.

Flagged buyers are excluded before the top ten are chosen. For the remaining
buyers, same-type sector activity profiles are compared with cosine similarity.
The score becomes `base_score * (1 - similarity_penalty * closest_similarity)`;
`config/feedback.yaml` sets the maximum discount. This is a transparent preference
heuristic, not a trained feedback model or a demonstrated predictive improvement.
The run freezes flags, policy, base score, and multiplier. Conviction is recomputed
from the adjusted score using the existing thresholds. The report displays the
feedback and base score; evaluation continues to measure the unchanged base ranker.
Portable replays require the recorded feedback policy whenever it was saved or
feedback flags were present; legacy archives without either remain compatible.

## Compare two profiles

```sh
uv run acquirers compare examples/healthcare.yaml examples/healthcare_large.yaml
```

This computes two rankings and saves `comparison.html` and `comparison.json` under
a new run ID. It costs nothing and works for arbitrary targets without drafting
buyer pages. Shared names determine overlap; a positive rank delta means the buyer
ranks higher for the second target. A missing rank means outside that shortlist.

An optional short narrative uses one recorded model request, with no evidence
tools or output retries:

```sh
# Paid; requires the analyst provider key and explicit intent to spend.
uv run acquirers compare examples/healthcare.yaml examples/healthcare_large.yaml --summary --fresh

# Free; requires a matching previously cached summary response.
uv run acquirers compare examples/healthcare.yaml examples/healthcare_large.yaml --summary
```

The summary is labeled an interpretation, not verified evidence. It has not been
live-evaluated. Its prompt, inputs, policy, responses, usage, and errors are saved.
If the optional summary fails, the computed table is still saved and the command
exits nonzero. No summary response is bundled with the sample.
