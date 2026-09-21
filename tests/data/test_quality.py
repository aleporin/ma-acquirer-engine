"""Verify documented discrepancies without correcting the dataset.

Owns: Measured quality counts and canonical-value preservation.
Does not own: Imputation or scoring.
"""

from acquirer_engine.data.loader import load_transactions
from acquirer_engine.data.quality import quality_report
from tests.data.test_loader import csv_path


def test_quality_report_matches_measured_counts() -> None:
    rows = load_transactions(csv_path())
    report = quality_report(rows, multiple_tolerance=0.1, margin_tolerance=1.5)
    assert report.multiple_mismatches == 403
    assert report.margin_mismatches == 362
    assert report.sponsor_deal_type_conflicts == 57
    assert report.strategic_deal_type_conflicts == 52
    assert report.rumored == 10
    assert report.null_days_to_close == 94
    assert report.rows == 500


def test_quality_report_preserves_stated_multiples() -> None:
    rows = load_transactions(csv_path())
    before = [row.ev_ebitda_multiple for row in rows]
    quality_report(rows, multiple_tolerance=0.1, margin_tolerance=1.5)
    assert [row.ev_ebitda_multiple for row in rows] == before
