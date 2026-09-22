"""Render public rationale pages with facts from their frozen evidence.

Owns: Safe HTML and Markdown, canonical fact tables, citations, and output identity.
Does not own: Narrative generation, claim acceptance, or changing model prose.
"""

import html
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from acquirer_engine.data import Transaction
from acquirer_engine.errors import DataError
from acquirer_engine.evidence.pack import Statistic
from acquirer_engine.llm.results import AnalystRun, PageResult
from acquirer_engine.llm.tools import EvidenceTools
from acquirer_engine.replay import RunSnapshot


def anchor(identifier: str) -> str:
    """Return an HTML identifier independent of untrusted evidence text."""
    return "evidence-" + sha256(identifier.encode()).hexdigest()


def cited_ids(report: AnalystRun) -> set[str]:
    """Collect every visible reference from verified pages only."""
    ids: set[str] = set()
    for page in report.pages:
        rationale = page.rationale
        if page.status != "verified" or rationale is None:
            continue
        ids.update(item.transaction_id for item in rationale.precedent_activity)
        ids.update(item.evidence_id for item in rationale.valuation_context.comps)
        ids.update(item.evidence_id for item in rationale.claims)
        ids.update(ref for risk in rationale.risk_flags for ref in risk.evidence_ids)
    return ids


def appendix(
    snapshot: RunSnapshot, report: AnalystRun
) -> tuple[list[Transaction], list[Statistic]]:
    """Resolve displayed citations before writing any report files.

    Args:
        snapshot: Frozen history and code-computed core statistics.
        report: Verified pages or explicit failed outcomes.
    Returns:
        Referenced transactions and computed facts in identity order.
    Raises:
        DataError: A citation is absent from the archived evidence.
    """
    rows = {row.transaction_id: row for row in snapshot.history}
    stats = {s.evidence_id: s for pack in snapshot.packs for s in pack.statistics}
    tools = EvidenceTools(snapshot.history, snapshot.settings.analyst)
    for sector in sorted({row.sector for row in snapshot.history}):
        stats.update({s.evidence_id: s for s in tools.sector_stats(sector).statistics})
    ids = cited_ids(report)
    if missing := ids - rows.keys() - stats.keys():
        raise DataError(f"Report evidence is missing: {', '.join(sorted(missing))}")
    return (
        [rows[key] for key in sorted(ids & rows.keys())],
        [stats[key] for key in sorted(ids & stats.keys())],
    )


@dataclass(frozen=True)
class DealFacts:
    """Public source rows, kept separate from model-written narrative."""

    precedents: tuple[Transaction, ...]
    comparables: tuple[Transaction, ...]


def deal_facts(snapshot: RunSnapshot, page: PageResult) -> DealFacts:
    """Resolve rows after the report's evidence appendix has checked references.

    Args:
        snapshot: Frozen transaction history for this run.
        page: A page whose citations were checked by the renderer.
    Returns:
        Cited source rows, or empty tables for unavailable pages.
    """
    if page.status != "verified" or page.rationale is None:
        return DealFacts((), ())
    rows = {row.transaction_id: row for row in snapshot.history}
    return DealFacts(
        tuple(rows[item.transaction_id] for item in page.rationale.precedent_activity),
        tuple(rows[item.evidence_id] for item in page.rationale.valuation_context.comps),
    )


def _markdown(value: object) -> str:
    escaped = html.escape(str(value), quote=False)
    return re.sub(r"([\\`*{}\[\]()#+.!_|>~-])", r"\\\1", escaped)


def _environment() -> Environment:
    environment = Environment(
        loader=PackageLoader("acquirer_engine", "templates"),
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
