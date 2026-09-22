"""Require canonical financial facts beside the rationale that uses them.

Owns: Public precedent and comparable tables in both output formats.
Does not own: Generating or silently correcting narrative text.
"""

from pathlib import Path

from acquirer_engine.deps import Deps
from acquirer_engine.stages.render import render_report
from tests.report.test_render import report_inputs


def test_deal_facts_are_visible_without_opening_numeric_claim_ledger(
    deps: Deps, tmp_path: Path
) -> None:
    snapshot, report = report_inputs(deps)
    render_report(snapshot, report, tmp_path)
    markdown = (tmp_path / "buyers/01.md").read_text().split("## Numeric claim sources")[0]
    html = (tmp_path / "index.html").read_text().split("<details>")[0]
    for text in (markdown, html):
        assert "EV/EBITDA" in text and "EV/Revenue" in text
        assert "13.64x" in text and "2.00x" in text
        assert "Strategic Acquisition" in text and "2020" in text
        assert "Private" in text and "Closed" in text
        assert "Deal EV" in text and "$200.0M" in text
        assert "Schema and numeric checks" in text
        assert "qualitative accuracy" in text
