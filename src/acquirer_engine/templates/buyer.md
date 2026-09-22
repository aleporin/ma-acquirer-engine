# {{ rank }}. {{ ranking.acquirer|md }}

{{ ranking.acquirer_type|md }} · Score {{ '%.3f'|format(ranking.score) }} · {{ ranking.conviction }} conviction
{% if feedback.flags %}
Base score before feedback: {{ '%.3f'|format(ranking.signals.values()|sum(attribute='contribution')) }}. Displayed score includes the saved sector-profile similarity penalty.
{% endif %}
{% set rationale = page.rationale %}
{% macro cite(id) -%}[{{ id|md }}](../index.html#{{ id|anchor }}){%- endmacro %}
{% if page.status == 'verified' and rationale %}
Schema and numeric checks passed; these checks do not establish complete qualitative accuracy. Historical activity does not establish current interest or financing capacity.

## Acquirer overview

{{ rationale.acquirer_overview|md }}

## Strategic fit

{{ rationale.strategic_fit_thesis|md }}

## Precedent activity

{% for item in rationale.precedent_activity %}- {{ item.description|md }} {{ cite(item.transaction_id) }}
{% endfor %}
{% with deals = facts.precedents %}{% include 'deals.md' %}{% endwith %}

## Valuation context · Closed transactions

{{ rationale.valuation_context.summary|md }}

Comparable evidence: {% for comp in rationale.valuation_context.comps %}{% if not loop.first %} {% endif %}{{ cite(comp.evidence_id) }}{% endfor %}

{% with deals = facts.comparables %}{% include 'deals.md' %}{% endwith %}

Tables show the dataset's stated financials. Deal EV is enterprise value, not the buyer's equity contribution. Prior ownership does not establish post-deal ownership.

## Risks

{% for risk in rationale.risk_flags %}- **{{ risk.category|replace('_', ' ')|capitalize }} · {{ risk.basis }}**: {{ risk.description|md }}{% for id in risk.evidence_ids %} {{ cite(id) }}{% endfor %}
{% endfor %}
## Conviction · {{ ranking.conviction }}

{{ rationale.conviction.justification|md }}
{% if rationale.outside_dataset_notes %}
## Unverified model knowledge

{{ rationale.outside_dataset_notes|md }}

Outside the supplied dataset. Training cutoff: not recorded in the archived model metadata.
{% endif %}
## Numeric claim sources

{% for claim in rationale.claims %}- {{ claim.metric|md }}: {{ '%g'|format(claim.value) }} — {{ cite(claim.evidence_id) }}
{% endfor %}
{% else %}
## Failed verification

{{ (page.banner or 'This page is unavailable.')|md }}

{% for error in page.errors %}- {{ error|md }}
{% endfor %}{% endif %}
---

Run {{ report.run_id }} · {{ report.mode }} · {{ report.prompt_version|md }}
