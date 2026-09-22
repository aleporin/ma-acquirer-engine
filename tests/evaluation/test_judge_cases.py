"""Specify blind labels and identification without answer leakage.

Owns: Case identity, reproducible shuffles, masking, and human label boundaries.
Does not own: Live judgments or narrative generation.
"""

import csv
import json
from pathlib import Path

import pytest

from acquirer_engine.errors import EvaluationError
from evals.judges.cases import identify_input, mask_page, seal_corpus
from evals.judges.labels import export_packet, read_labels
from evals.judges.schema import Candidate, Case, Dimension


def example_case(index: int = 1) -> Case:
    return Case(
        case_id=f"case-{index:016x}",
        source_run_id=f"{index:032x}",
        source_git_sha="a" * 40,
        generation_prompt="example_v1",
        buyer="Buyer A",
        stage="after_review",
        reviewer_enabled=False,
        page="Buyer A acquired $200M. [stat:deal_count:Buyer%20A] MA-2020-0001",
        evidence="Closed Services precedent: $200M; 4 recorded deals.",
        target="Services target at $200M.",
        candidates=(
            Candidate(name="Buyer A", summary="4 Services deals."),
            Candidate(name="Buyer B", summary="2 Device deals."),
        ),
    )


def test_identification_removes_names_and_identity_bearing_references() -> None:
    page = "BUYER A and Buyer%20A, Buyer+A. stat:count:Buyer%20A MA-2020-0001"
    masked = mask_page(page, ["Buyer A"])
    for leak in ("BUYER A", "Buyer%20A", "Buyer+A", "stat:", "MA-2020-0001"):
        assert leak not in masked
    assert "$200M" in mask_page(example_case().page, ["Buyer A"])


def test_identification_shuffles_and_records_the_answer_outside_the_input() -> None:
    case = example_case()
    inputs = [identify_input(case, seed=seed) for seed in range(20)]
    assert {item.expected_choice for item in inputs} == {1, 2}
    for item in inputs:
        assert item == identify_input(case, seed=item.seed)
        payload = json.loads(item.payload)
        assert "Buyer A" not in payload["page"]
        assert "expected_choice" not in payload and "source_run_id" not in payload
        assert payload["candidates"][item.expected_choice - 1]["name"] == "Buyer A"


def test_corpus_digest_binds_content_and_rejects_duplicate_case_ids() -> None:
    case = example_case()
    first = seal_corpus([case], seed=9)
    assert first == seal_corpus([case], seed=9)
    changed = seal_corpus([case.model_copy(update={"page": "Changed text"})], seed=9)
    assert first.digest != changed.digest
    with pytest.raises(EvaluationError, match="Duplicate"):
        seal_corpus([case, case], seed=9)


def test_blind_packet_hides_run_and_judge_metadata_and_never_overwrites(tmp_path: Path) -> None:
    corpus = seal_corpus([example_case(1), example_case(2)], seed=9)
    path = export_packet(corpus, tmp_path / "packet")
    pages = sorted((path / "pages").glob("*.md"))
    assert len(pages) == 2
    for page in pages:
        text = page.read_text()
        assert "example_v1" not in text and "source_run_id" not in text
        assert "Services target" in text and "Closed Services precedent" in text
    with (path / "human_labels.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert all(row[dimension] == "" for row in rows for dimension in Dimension)
    with pytest.raises(EvaluationError, match="already exists"):
        export_packet(corpus, path)


def test_incomplete_duplicate_or_unknown_label_rows_are_rejected(tmp_path: Path) -> None:
    corpus = seal_corpus([example_case()], seed=9)
    path = export_packet(corpus, tmp_path / "packet") / "human_labels.csv"
    with pytest.raises(EvaluationError, match="complete"):
        read_labels(path, corpus)
    with path.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=["case_id", *Dimension])
        writer.writeheader()
        row: dict[str, str] = {
            "case_id": example_case().case_id,
            **dict.fromkeys(Dimension, "Pass"),
        }
        writer.writerow(row)
    labels = read_labels(path, corpus)
    assert len(labels) == 5 and all(label.vote == "Pass" for label in labels)
    with path.open("a") as stream:
        csv.DictWriter(stream, fieldnames=["case_id", *Dimension]).writerow(row)
    with pytest.raises(EvaluationError, match="Duplicate"):
        read_labels(path, corpus)
