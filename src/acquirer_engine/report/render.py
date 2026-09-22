"""Write a self-contained HTML report and one Markdown file per buyer.

Owns: Safe templates, public display fields, and output identity checks.
Does not own: Generation, validation, or changing narrative wording.
"""

import html
import re
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from acquirer_engine.errors import DataError
from acquirer_engine.llm.archive import RunSnapshot
from acquirer_engine.llm.results import AnalystRun
from acquirer_engine.report.evidence import anchor, appendix
from acquirer_engine.report.facts import deal_facts


def _markdown(value: object) -> str:
    escaped = html.escape(str(value), quote=False)
    return re.sub(r"([\\`*{}\[\]()#+.!_|>~-])", r"\\\1", escaped)


def _environment() -> Environment:
    environment = Environment(
        loader=PackageLoader("acquirer_engine.report", "templates"),
        autoescape=select_autoescape(("html",)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    environment.filters.update(anchor=anchor, md=_markdown)
    return environment


def _context(snapshot: RunSnapshot, report: AnalystRun) -> dict[str, object]:
    if snapshot.run_id != report.run_id or not snapshot.packs:
        raise DataError("Report identity differs from its input snapshot")
    by_name = {page.acquirer: page for page in report.pages}
    names = [pack.ranking.acquirer for pack in snapshot.packs]
    if len(by_name) != len(report.pages) or set(names) != by_name.keys():
        raise DataError("Report buyer identity differs from its ranking")
    rows, statistics = appendix(snapshot, report)
    buyers = [
        dict(
            rank=i,
            ranking=pack.ranking,
            page=by_name[pack.ranking.acquirer],
            facts=deal_facts(snapshot, by_name[pack.ranking.acquirer]),
        )
        for i, pack in enumerate(snapshot.packs, 1)
    ]
    return dict(
        feedback=snapshot.feedback,
        buyers=buyers,
        report=report,
        target=snapshot.packs[0].target,
        rows=rows,
        statistics=statistics,
        cost=sum(call.cost_usd for call in report.calls),
        models=sorted({call.model for call in report.calls}),
        sponsors=sum(p.ranking.acquirer_type == "Financial Sponsor" for p in snapshot.packs),
        strategics=sum(p.ranking.acquirer_type == "Strategic" for p in snapshot.packs),
        verified=sum(p.status == "verified" for p in report.pages),
    )


def render_report(
    snapshot: RunSnapshot,
    report: AnalystRun,
    directory: Path,
    *,
    source_report: AnalystRun | None = None,
) -> Path:
    """Render only public prose, with escaped text and resolvable citations.

    Args:
        snapshot, report: Matching archived inputs and execution results.
        directory: New output location, or this run's existing artifact directory.
        source_report: Optional original execution for replay cost comparison.
    Returns:
        The HTML entry point.
    Raises:
        DataError: Identity, evidence, or existing output would be overwritten.
        OSError: Output cannot be written.
    """
    context = _context(snapshot, report)
    if source_report and report.replay_of != source_report.run_id:
        raise DataError("Replay source identity differs from the report")
    context.update(
        source=source_report,
        source_cost=sum(call.cost_usd for call in source_report.calls) if source_report else None,
    )
    environment = _environment()
    files = {"index.html": environment.get_template("index.html").render(**context)}
    template = environment.get_template("buyer.md")
    for rank, pack in enumerate(snapshot.packs, 1):
        page = next(p for p in report.pages if p.acquirer == pack.ranking.acquirer)
        files[f"buyers/{rank:02d}.md"] = template.render(
            rank=rank,
            ranking=pack.ranking,
            page=page,
            facts=deal_facts(snapshot, page),
            report=report,
            feedback=snapshot.feedback,
        )
    _write_outputs(directory, files, report)
    return directory / "index.html"


def _write_outputs(directory: Path, files: dict[str, str], report: AnalystRun) -> None:
    run_json = report.model_dump_json(indent=2) + "\n"
    existing = directory / "run.json"
    if existing.exists():
        if existing.read_text(encoding="utf-8") != run_json:
            raise DataError("Run output already exists with different content")
    else:
        files["run.json"] = run_json
    if any((directory / name).exists() for name in files):
        raise DataError("Report output already exists; choose a new directory")
    for name, content in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
