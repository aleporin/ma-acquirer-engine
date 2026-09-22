# Execution-flow cleanup

Measured source: `cecd319d846cd480817cf6e940ec43eb52519f81` (clean).
Base: `62364902c216cc582c44de303d0353f0a2e6f7f4`.
Environment: Python 3.12.14, uv 0.12.17, locked dependencies.

The goal was easier code navigation. Application modules excluding package
initializers fell from 68 to 51; the LLM package fell from 22 to 13. Evaluation
modules fell from 38 to 37 and preparation stages now use responsibility names.
Routing, retry, and analyst execution are together; related domain helpers sit
with the workflow that uses them. This is not a runtime-performance claim.

## Verification

- `make test`: 326 passed in 6.80s at runtime source `2d328ab`; subsequent source
  changes only updated documentation. The evaluation separately ran its configured
  196-test subset; it is not the full 326-test suite.
- `make lint`: Ruff and format passed; strict mypy passed for 181 source files;
  file/function size checks passed. No runtime changes followed that check.
- `make run`: 10/10 verified pages, 21 recorded responses, $0 new spend.
- `make eval EVAL_FLAGS="--analyst-run runs/b6976a22ede94a9cb0de4a7e61c623af/run.json"`:
  layers 0, 1, 2, 3, 5, and 6 passed; layer 4 remains unmeasured.
- 113 maintained documentation links resolve. Report-template links are checked
  in their generated context, not against the source-template directory.

`replay_parity.json` records an exact comparison against the shipped sample.
All ten page payloads match after excluding measured latency; all ten Markdown
bodies match after excluding the run-provenance footer. All 21 call records match
excluding timing. Configuration, prompts, replay archives, and sample output
are unchanged. New characterization tests cover successful and exhausted
repair replay, zero new spend, and preservation of original archives.

## Interpretation

These checks demonstrate behavior preservation for the recorded sample and
tested failure paths. They do not establish new live quality, cost, or speed.
Human/judge calibration remains unmeasured. Ranking has not demonstrated lift
over popularity. The selected live generation remains $1.863930; current matched
live ablations are still absent. Replay layer 6 does not replace those controls.
