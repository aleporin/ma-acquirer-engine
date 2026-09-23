UV ?= uv
RESULTS ?=
EVAL_FLAGS ?=
RUN_FLAGS ?= --replay
JUDGE_FLAGS ?=
WEIGHT_PROPOSAL ?= evals/results/p7-47f238dc8605d755ee5c8554e6e2220cd940e8de/weight-experiment/proposals/b5a7158e6d824521a98424aef5694b68

.PHONY: test lint eval eval-judges eval-diff eval-weights run

test:
	$(UV) run --locked pytest

lint:
	$(UV) run --locked ruff check .
	$(UV) run --locked ruff format --check .
	$(UV) run --locked mypy
	$(UV) run --locked python -m scripts.check_lengths

eval:
	$(UV) run --locked acquirers eval --replay $(if $(RESULTS),--results "$(RESULTS)") $(EVAL_FLAGS)

eval-judges:
	$(UV) run --locked acquirers eval-judges $(JUDGE_FLAGS)

eval-diff:
	$(UV) run --locked acquirers eval-diff "$(A)" "$(B)"

eval-weights:
	$(UV) run --locked acquirers experiment-weights "$(WEIGHT_PROPOSAL)"

run:
	$(UV) run --locked acquirers run $(RUN_FLAGS)
