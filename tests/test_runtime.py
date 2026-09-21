"""Verify structured run logging and injected dependencies.

Owns: Observable logging destinations, context isolation, and shared references.
Does not own: Provider calls or pipeline retries.
"""

import io
import json
from pathlib import Path

from acquirer_engine.deps import Deps
from acquirer_engine.errors import AcquirerEngineError, ValidationFailure
from acquirer_engine.logging_setup import run_logger
from acquirer_engine.settings import load_settings


def test_json_logs_reach_stderr_and_disk_with_bound_context(tmp_path: Path) -> None:
    stream = io.StringIO()
    with run_logger(tmp_path, "run-one", "a" * 40, "not_implemented", stream) as logger:
        logger.bind(stage="eval", acquirer="example").info("evaluation_started")
    event = json.loads(stream.getvalue())
    assert event == json.loads((tmp_path / "run-one/log.jsonl").read_text())
    assert event["run_id"] == "run-one"
    assert event["git_sha"] == "a" * 40
    assert event["mode"] == "replay"
    assert event["stage"] == "eval"
    assert event["acquirer"] == "example"
    assert event["level"] == "info"


def test_runs_do_not_share_context_or_duplicate_handlers(tmp_path: Path) -> None:
    stream = io.StringIO()
    for run_id in ("first", "second"):
        with run_logger(tmp_path, run_id, "b" * 40, "not_implemented", stream) as logger:
            logger.info("evaluation_started")
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [event["run_id"] for event in events] == ["first", "second"]
    assert "second" not in (tmp_path / "first/log.jsonl").read_text()


def test_deps_keeps_supplied_instances(tmp_path: Path) -> None:
    settings = load_settings(Path(__file__).resolve().parents[1] / "config")
    with run_logger(tmp_path, "injection", "c" * 40, "not_implemented", io.StringIO()) as log:
        deps = Deps(settings=settings, logger=log)
        assert deps.settings is settings
        assert deps.logger is log


def test_validation_failure_preserves_specific_errors() -> None:
    failure = ValidationFailure(["missing evidence", "invalid claim"])
    assert isinstance(failure, AcquirerEngineError)
    assert failure.errors == ("missing evidence", "invalid claim")
