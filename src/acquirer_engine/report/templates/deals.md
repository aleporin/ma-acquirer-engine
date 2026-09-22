| Transaction / year / sector | Deal EV | Structure / prior ownership | Outcome | EBITDA margin | EV/EBITDA | EV/Revenue |
| --- | ---: | --- | --- | ---: | ---: | ---: |
{% for row in deals %}| {{ row.target_company|md }} / {{ row.deal_year }} / {{ row.sector|md }} {{ cite(row.transaction_id) }} | ${{ '%.1f'|format(row.deal_size_mm) }}M | {{ row.deal_type|md }} / {{ row.target_ownership_pre|md }} | {{ row.outcome|md }} | {{ '%.2f'|format(row.ebitda_margin_pct) }}% | {{ '%.2f'|format(row.ev_ebitda_multiple) }}x | {{ '%.2f'|format(row.ev_revenue_multiple) }}x |
{% endfor %}
