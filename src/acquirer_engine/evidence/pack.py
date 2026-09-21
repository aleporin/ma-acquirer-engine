"""Build bounded core evidence from a buyer's fitted history.

Owns: Deterministic core rows, computed facts, and conservative context caps.
Does not own: Market comps, model token accounting, or claim verification.
"""

from hashlib import sha256

from pydantic import BaseModel, ConfigDict, FiniteFloat

from acquirer_engine.data.schema import Transaction
from acquirer_engine.errors import EvidenceError
from acquirer_engine.evidence.config import PackConfig
from acquirer_engine.evidence.ids import stat_id
from acquirer_engine.features.acquirer import AcquirerHistory
from acquirer_engine.ranking.scorer import RankedAcquirer
from acquirer_engine.ranking.target import TargetProfile


class Statistic(BaseModel):
    """A computed number with a stable identity and explicit metric."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str
    metric: str
    value: FiniteFloat


class CorePack(BaseModel):
    """Only the buyer's own rows, ranking explanation, and target profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    target: TargetProfile
    ranking: RankedAcquirer
    deals: tuple[Transaction, ...]
    statistics: tuple[Statistic, ...]
    total_rows: int
    truncated: bool

    @property
    def token_upper_bound(self) -> int:
        """Bound byte-tokenized content tokens by its UTF-8 byte length."""
        return len(self.model_dump_json().encode("utf-8"))


def _statistic(name: str, scope: str, value: float) -> Statistic:
    return Statistic(evidence_id=stat_id(name, scope), metric=name, value=value)


def _statistics(
    history: AcquirerHistory, ranking: RankedAcquirer, target: TargetProfile
) -> tuple[Statistic, ...]:
    values = {
        "deal_count": history.deal_count,
        "size_min_mm": history.size_min,
        "size_max_mm": history.size_max,
        "completion_rate": history.completion_rate,
        "median_ev_ebitda_multiple": history.median_ev_ebitda,
        "median_ev_revenue_multiple": history.median_ev_revenue,
        "score": ranking.score,
        "relevant_deals": ranking.relevant_deals,
    }
    stats = [_statistic(k, history.name, v) for k, v in values.items() if v is not None]
    target_scope = "target-" + sha256(target.model_dump_json().encode()).hexdigest()
    stats.extend(
        _statistic(metric, target_scope, value)
        for metric, value in (
            ("deal_size_mm", target.deal_size_mm),
            ("ebitda_margin_pct", target.ebitda_margin_pct),
        )
    )
    for name, signal in sorted(ranking.signals.items()):
        stats.extend(
            _statistic(f"{name}.{metric}", history.name, value)
            for metric, value in signal.model_dump().items()
        )
    return tuple(stats)


def build_core_pack(
    history: AcquirerHistory, ranking: RankedAcquirer, target: TargetProfile, config: PackConfig
) -> CorePack:
    """Keep recent own-history rows until either context budget is reached.

    Args:
        history: Already fitted eligible buyer history.
        ranking: Code-computed score and conviction for that buyer.
        target: Query assumptions used by the ranker.
        config: Independent row and conservative token caps.
    Returns:
        Deterministic pack; aggregate facts retain the full history scope.
    Raises:
        EvidenceError: Buyer identities disagree or fixed context exceeds budget.
    """
    if history.name != ranking.acquirer or any(r.acquirer != history.name for r in history.rows):
        raise EvidenceError("Ranking and core history must describe the same acquirer")
    rows = sorted(history.rows, key=lambda r: (-r.deal_year, r.transaction_id))
    pack = CorePack(
        target=target,
        ranking=ranking,
        deals=(),
        statistics=_statistics(history, ranking, target),
        total_rows=len(rows),
        truncated=bool(rows),
    )
    if pack.token_upper_bound > config.max_tokens:
        raise EvidenceError("Core pack fixed context exceeds token cap")
    for row in rows[: config.max_rows]:
        candidate = pack.model_copy(
            update={
                "deals": (*pack.deals, row),
                "truncated": len(pack.deals) + 1 < len(rows),
            }
        )
        if candidate.token_upper_bound > config.max_tokens:
            break
        pack = candidate
    return pack
