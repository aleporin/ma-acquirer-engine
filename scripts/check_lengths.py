"""Enforce maintained-file and Python-function size limits.

Owns: File discovery, physical line counting, and violation reporting.
Does not own: Formatting, type checking, or generated artifact validation.
"""

import ast
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, PositiveInt


class Limits(BaseModel):
    """Validated size limits from evaluation configuration."""

    model_config = ConfigDict(extra="forbid", strict=True)
    max_file_lines: PositiveInt
    max_function_lines: PositiveInt


def check_file(path: Path, file_limit: int, function_limit: int) -> list[str]:
    """Return size or syntax violations for one maintained file.

    Args:
        path: File to inspect.
        file_limit: Maximum physical lines per file.
        function_limit: Maximum span including decorators and docstrings.
    Returns:
        Human-readable violations.
    Raises:
        OSError: The file cannot be read.
    """
    source = path.read_text(encoding="utf-8")
    problems = []
    count = len(source.splitlines())
    if count > file_limit:
        problems.append(f"{path}: {count} lines (maximum {file_limit})")
    if path.suffix != ".py":
        return problems
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        return [*problems, f"{path}: invalid Python at line {error.lineno}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            start = min([node.lineno, *[item.lineno for item in node.decorator_list]])
            span = (node.end_lineno or node.lineno) - start + 1
            if span > function_limit:
                problems.append(f"{path}:{start}: {node.name}: {span} lines")
    return problems


def check_repository(
    root: Path, paths: Iterable[Path], file_limit: int, function_limit: int
) -> list[str]:
    """Check maintained text files, excluding data and generated artifacts.

    Args:
        root: Repository root.
        paths: Candidate paths within the repository.
        file_limit: Maximum physical lines.
        function_limit: Maximum Python function span.
    Returns:
        All violations in deterministic path order.
    """
    problems = []
    for path in sorted(set(paths)):
        relative = path.relative_to(root)
        if path.is_symlink() or not path.is_file():
            continue
        if relative.parts[0] in {"cache", "runs", ".venv", ".worktrees", "sample_output"}:
            continue
        if relative.parts[:2] == ("evals", "results"):
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        if path.suffix not in {".py", ".md", ".toml", ".yaml", ".yml"} and path.name not in {
            "Makefile",
            ".gitignore",
            ".env.example",
            ".python-version",
        }:
            continue
        problems.extend(check_file(path, file_limit, function_limit))
    return problems


def repository_violations(root: Path) -> list[str]:
    """Discover tracked and unignored files and apply configured limits.

    Args:
        root: Repository root containing config/eval.yaml.
    Returns:
        All size violations.
    Raises:
        OSError: Configuration is unreadable.
        ValueError: Configuration is invalid.
        subprocess.CalledProcessError: Git discovery fails.
    """
    config = yaml.safe_load((root / "config/eval.yaml").read_text(encoding="utf-8"))
    limits = Limits.model_validate(config["quality"])
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = [root / name for name in result.stdout.split("\0") if name]
    return check_repository(root, paths, limits.max_file_lines, limits.max_function_lines)


if __name__ == "__main__":
    violations = repository_violations(Path.cwd())
    sys.stderr.write("\n".join(violations) + ("\n" if violations else ""))
    raise SystemExit(bool(violations))
