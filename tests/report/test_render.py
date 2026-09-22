"""Specify the portable report's public and private boundaries.

Owns: Evidence links, safe display, complete output, and archive immutability.
Does not own: Narrative generation or browser print pagination.
"""

import importlib
import json
import re
from pathlib import Path

import pytest

from acquirer_engine.deps import Deps
from acquirer_engine.errors import DataError
from acquirer_engine.llm.archive import RunSnapshot
from acquirer_engine.llm.results import AnalystRun
from tests.fixtures.rationale import rationale_payload
from tests.llm.test_run_archive import inputs


def report_inputs(deps: Deps) -> tuple[RunSnapshot, AnalystRun]:
    snapshot = inputs(deps, "a" * 32)
    payload = rationale_payload() | {
        "reasoning": "PRIVATE WORKING NOTES",
        "outside_dataset_notes": '<script>alert("outside")</script>',
    }
    report = AnalystRun.model_validate(
        dict(
            run_id=snapshot.run_id,
            mode="test",
            git_sha=snapshot.git_sha,
            prompt_version="fixture",
            latency_seconds=1,
            calls=[],
            pages=[
                dict(
                    acquirer=snapshot.packs[0].ranking.acquirer,
                    acquirer_type=snapshot.packs[0].ranking.acquirer_type,
                    status="verified",
                    errors=[],
                    tools=[],
                    latency_seconds=1,
                    rationale=payload,
                )
            ],
        ),
        context=deps.settings.evidence.validation,
    )
    return snapshot, report


def test_report_has_public_sections_resolvable_evidence_and_no_working_notes(
    deps: Deps, tmp_path: Path
) -> None:
    snapshot, report = report_inputs(deps)
    render = importlib.import_module("acquirer_engine.report.render")
    render.render_report(snapshot, report, tmp_path)
    html = (tmp_path / "index.html").read_text()
    markdown = (tmp_path / "buyers/01.md").read_text()
    assert "PRIVATE WORKING NOTES" not in html + markdown
    assert '<script>alert("outside")</script>' not in html + markdown
    assert "&lt;script&gt;" in html
    assert "Unverified model knowledge" in html and "Training cutoff" in html
    for anchor in re.findall(r'href="#([^"]+)"', html):
        assert f'id="{anchor}"' in html
    assert "MA-2020-0001" in html and "MA-2020-0010" in html
    assert "Financial Sponsor" in html and "Strategic" in html
    assert "13.64" in html and "Closed" in html
    assert "http://" not in html and "https://" not in html
    assert "../index.html#" in markdown
    assert json.loads((tmp_path / "run.json").read_text())["run_id"] == report.run_id


def test_failed_page_shows_errors_instead_of_unverified_draft(deps: Deps, tmp_path: Path) -> None:
    snapshot, report = report_inputs(deps)
    failed = report.pages[0].model_copy(update={"status": "failed", "errors": ["bad claim"]})
    render = importlib.import_module("acquirer_engine.report.render")
    render.render_report(snapshot, report.model_copy(update={"pages": [failed]}), tmp_path)
    html = (tmp_path / "index.html").read_text()
    assert "bad claim" in html and "Failed verification" in html
    assert failed.rationale is not None
    assert failed.rationale.strategic_fit_thesis not in html


def test_report_refuses_mismatched_identity_and_existing_output(deps: Deps, tmp_path: Path) -> None:
    snapshot, report = report_inputs(deps)
    render = importlib.import_module("acquirer_engine.report.render")
    with pytest.raises(DataError, match="identity"):
        render.render_report(snapshot, report.model_copy(update={"run_id": "b" * 32}), tmp_path)
    render.render_report(snapshot, report, tmp_path)
    saved = (tmp_path / "index.html").read_bytes()
    with pytest.raises(DataError, match="exists"):
        render.render_report(snapshot, report, tmp_path)
    assert (tmp_path / "index.html").read_bytes() == saved


def test_missing_reference_is_rejected_before_any_files_are_written(
    deps: Deps, tmp_path: Path
) -> None:
    snapshot, report = report_inputs(deps)
    render = importlib.import_module("acquirer_engine.report.render")
    with pytest.raises(DataError, match="evidence"):
        render.render_report(snapshot.model_copy(update={"history": ()}), report, tmp_path)
    assert list(tmp_path.iterdir()) == []
