"""Exercise CI checkout depth through Git's actual object availability.

Owns: The history required to verify a committed ranking baseline.
Does not own: Ranking policy or remote publication.
"""

import json
import subprocess
from pathlib import Path

import yaml


def test_ci_checkout_keeps_the_committed_baseline_revision(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((project / ".github/workflows/ci.yml").read_text())
    checkout_step = next(
        step
        for step in workflow["jobs"]["checks"]["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    depth = checkout_step.get("with", {}).get("fetch-depth", 1)
    checkout = tmp_path / "checkout"
    command = ["git", "clone", "--no-local", "--no-checkout"]
    if depth:
        command.extend(["--depth", str(depth)])
    subprocess.run([*command, project.as_uri(), str(checkout)], check=True, capture_output=True)
    card = next((project / "evals/results").glob("p1-*/scorecard.json"))
    baseline = json.loads(card.read_text())["run"]["git_sha"]
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{baseline}^{{commit}}"], cwd=checkout, capture_output=True
    )
    assert result.returncode == 0, "CI checkout omitted the committed baseline revision"
