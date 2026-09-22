# Four-stage structure verification

Source: clean `17d6c26f335f62d37a908dced00f1e7889a73b0c` on Python 3.12.14,
uv 0.12.17, with locked dependencies. This is a structural follow-up to
`8e4c9dac38f1c610a4af75f323eeda4c28e109b2`.

## Change and checks

The product workflow now reads select → draft → review → render under `stages/`.
Related data, ranking, evidence, replay, and judge helpers are grouped together.
Model stages require assembled `RuntimeDeps`; preparation retains settings and
logger only. Application modules decreased from 51 to 40; evaluation modules
decreased from 37 to 33, excluding package initializers.

The test-first characterization in `1fd40b2` checks identical rendering from a
working directory outside the project before moving packaged templates.

```text
$ make test
327 passed in 6.66s
$ make lint
All checks passed!
303 files already formatted
Success: no issues found in 164 source files
python -m scripts.check_lengths: exit 0
$ make run
Verified pages: 10/10
$ make eval -- [analyst-run: a5ab0b696acd44bdb215db81da2f3deb]
Layer 0: passed
Layer 1: passed
Layer 2: passed
Layer 3: passed
Layer 4: not_implemented
Layer 5: passed
Layer 6: passed
```

Actual evaluation invocation:
`make eval EVAL_FLAGS="--analyst-run runs/a5ab0b696acd44bdb215db81da2f3deb/run.json"`.
The layer-0 grader runs its configured 196-test subset, distinct from the full
327-test suite. Coverage targets follow the moved code, including draft, review,
and replay; the resulting 95.7379% is not evidence of improved coverage quality.

`replay_parity.json` records identical structured pages and 21 recorded responses
excluding timing, plus ten identical Markdown bodies excluding provenance
footers. Configuration, prompts, source archives, and `sample_output` are unchanged.
The replay made no provider calls and incurred zero new model cost.

An offline wheel build succeeded. `wheel_verification.json` records importing
application code from the installed wheel outside the repository, rendering all
12 report files identically, and rendering the comparison template. It reused
locked development dependencies: a separate offline dependency installation
could not resolve an uncached pandas wheel. This checks package resources, not
a fresh dependency installation.

## Proof boundary

This verifies behavior preservation on the selected archived run. It is not a
new live generation, latency, cost, ranking-lift, or independent quality result.
Historical failed measurements remain intact. Judge/human calibration remains
unmeasured; the selected live sample still exceeded the original $1 target.
