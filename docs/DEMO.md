# Recorded replay walkthrough

[Watch the silent screen demonstration](demo/replay.webm) (about one minute).
It uses the shipped response archive, makes no provider calls, and shows replay
speed. The source live run took 48.18 seconds and cost $1.863930.

| Approximate time | What is shown |
| --- | --- |
| 0:00 | Actual run output and replay mode |
| 0:07 | Ranked buyer list |
| 0:15 | Francisco Partners rationale |
| 0:23 | Risks and conviction |
| 0:29 | Linked transaction evidence |
| 0:35 | Replay versus original live cost and latency |
| 0:42 | Free target comparison |
| 0:50 | Measured limitations |

The selected page shows the corrected sample and visible source financials.
It is not presented as independent banker-quality proof; see [EVALS.md](EVALS.md).
The [recording manifest](demo/manifest.json) identifies source, runs, and chapters.

## Reproduce the same flow

~~~sh
make run
uv run acquirers compare examples/healthcare.yaml examples/healthcare_large.yaml
~~~

Open the paths printed by those commands. The ten-buyer report and comparison
table are self-contained HTML files.
