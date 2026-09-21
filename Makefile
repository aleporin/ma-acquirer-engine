UV ?= uv
RESULTS ?=
EVAL_FLAGS ?=
RUN_FLAGS ?= --replay

.PHONY: test lint eval eval-judges eval-diff run

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
	$(UV) run --locked acquirers eval-judges

eval-diff:
	$(UV) run --locked acquirers eval-diff "$(A)" "$(B)"

run:
	$(UV) run --locked acquirers run $(RUN_FLAGS)
