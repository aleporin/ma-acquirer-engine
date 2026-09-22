"""Export blind reading packets and validate completed human labels.

Owns: Human-facing page order, blank CSV templates, and exact label coverage.
Does not own: Inventing ratings or displaying model judgments before labeling.
"""

import csv
import re
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from acquirer_engine.errors import EvaluationError
from evals.judges.schema import Case, Corpus, Dimension, HumanLabel


def _literal(text: str) -> str:
    fence = "`" * (max((len(x) for x in re.findall(r"`+", text)), default=0) + 3)
    return f"{fence}text\n{text}\n{fence}\n"


def _page(case: Case) -> str:
    sections = (("Target", case.target), ("Page", case.page), ("Evidence", case.evidence))
    return f"# {case.case_id}\n\n" + "\n".join(
        f"## {name}\n\n{_literal(text)}" for name, text in sections
    )


def export_packet(corpus: Corpus, directory: Path) -> Path:
    """Write final pages in shuffled order without exposing run/model metadata.

    Args:
        corpus: Frozen source cases; only after-review pages receive human labels.
        directory: New destination; existing human work is never replaced.
    Returns:
        The reading packet directory.
    Raises:
        EvaluationError: Destination already exists or cannot be written.
    """
    if directory.exists():
        raise EvaluationError("Blind packet already exists")
    cases = [case for case in corpus.cases if case.stage == "after_review"]
    Random(corpus.seed).shuffle(cases)
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=directory.parent, prefix=".labels-") as temporary:
            staging = Path(temporary) / "packet"
            (staging / "pages").mkdir(parents=True)
            lines = [
                "# Blind page labels",
                "",
                "Read [the labeling guide](RUBRIC.md), then each page before any judge output.",
                "Enter Pass, Fail, or Unknown for each dimension; leave no blanks.",
                "",
            ]
            for i, case in enumerate(cases, 1):
                name = f"{i:02d}-{case.case_id}.md"
                (staging / "pages" / name).write_text(_page(case), encoding="utf-8")
                lines.append(f"{i}. [{case.case_id}](pages/{name})")
            lines.extend(["", f"Corpus digest: {corpus.digest}", ""])
            (staging / "RUBRIC.md").write_text(Path(__file__).with_name("rubric.md").read_text())
            (staging / "README.md").write_text("\n".join(lines), encoding="utf-8")
            with (staging / "human_labels.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["case_id", *Dimension])
                writer.writeheader()
                writer.writerows({"case_id": case.case_id} for case in cases)
            staging.rename(directory)
    except OSError as error:
        raise EvaluationError("Could not write blind packet") from error
    return directory


def read_labels(path: Path, corpus: Corpus) -> list[HumanLabel]:
    """Require one complete human row per final page before paid calibration.

    Args:
        path: Human-completed CSV, with the exact template columns.
        corpus: Source identity against which labels will be compared.
    Returns:
        Validated labels without substituting votes for missing answers.
    Raises:
        EvaluationError: Labels are incomplete, duplicated, or misidentified.
    """
    expected = {case.case_id for case in corpus.cases if case.stage == "after_review"}
    seen: set[str] = set()
    labels: list[HumanLabel] = []
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != ["case_id", *Dimension]:
                raise EvaluationError("Human labels require the original template columns")
            for row in reader:
                identity = row.get("case_id", "")
                if identity in seen:
                    raise EvaluationError("Duplicate human label row")
                if identity not in expected or None in row:
                    raise EvaluationError("Human label row is not in this corpus")
                seen.add(identity)
                labels.extend(
                    HumanLabel.model_validate(
                        {"case_id": identity, "dimension": dimension, "vote": row[dimension]}
                    )
                    for dimension in Dimension
                )
    except (OSError, csv.Error, ValidationError) as error:
        raise EvaluationError(
            "Human labels must be readable and complete: Pass/Fail/Unknown"
        ) from error
    if seen != expected:
        raise EvaluationError("Human labels must be complete for every final page")
    return labels
