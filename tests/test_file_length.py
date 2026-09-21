"""Check repository size limits through the checker interface.

Owns: Boundary and discovery tests for maintained files.
Does not own: Product behavior or generated data validation.
"""

from pathlib import Path

from scripts.check_lengths import check_file, check_repository


def test_file_at_limit_passes_and_next_line_fails(tmp_path: Path) -> None:
    path = tmp_path / "example.md"
    path.write_text("text\n" * 300)
    assert check_file(path, 300, 50) == []
    path.write_text("text\n" * 301)
    assert "301 lines" in check_file(path, 300, 50)[0]


def test_decorated_async_function_counts_its_complete_span(tmp_path: Path) -> None:
    path = tmp_path / "example.py"
    source = "@decorator\nasync def example():\n" + "    pass\n" * 48
    path.write_text(source)
    assert check_file(path, 300, 50) == []
    path.write_text(source + "    pass\n")
    assert "example: 51 lines" in check_file(path, 300, 50)[0]


def test_repository_excludes_data_and_generated_artifacts(tmp_path: Path) -> None:
    for relative in ["data/source.csv", "uv.lock", "evals/results/p0-test/scorecard.json"]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("entry\n" * 501)
    maintained = tmp_path / "README.md"
    maintained.write_text("text\n" * 301)
    problems = check_repository(tmp_path, list(tmp_path.rglob("*")), 300, 50)
    assert len(problems) == 1
    assert "README.md" in problems[0]


def test_invalid_python_is_reported_as_a_failure(tmp_path: Path) -> None:
    path = tmp_path / "broken.py"
    path.write_text("def broken(:\n")
    assert "invalid Python" in check_file(path, 300, 50)[0]


def test_maintained_repository_files_obey_configured_limits() -> None:
    from scripts.check_lengths import repository_violations

    root = Path(__file__).resolve().parents[1]
    assert repository_violations(root) == []
