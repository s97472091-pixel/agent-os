---
name: portfolio-rebalancer
description: "Analyze, plan, and simulate multi-asset portfolio rebalancing. Use when the user asks to rebalance a crypto portfolio, check allocation drift, preview rebalance turnover and fees, or generate fee-minimized rebalance orders with SELLs-first sequencing, dust filtering, and configurable cash buffer."
homepage: https://github.com/use-agent-os/agent-os
triggers:
  - rebalance
  - portfolio allocation
  - drift analysis
  - rebalance plan
  - diversification
  - rebalance simulation
provenance:
  origin: agentos-original
  license: MIT
  maintained_by: AgentOS
metadata:
  agentos:
    emoji: "⚖️"
    category: crypto
    risk: low
    capabilities: [read-only]
    requires:
      anyBins: [python3, python]
entrypoint:
  command: python3 {baseDir}/scripts/rebalancer.py
  args:
    - "{{ with.command | default(drift) }}"
    - --portfolio
    - "{{ with.portfolio | default(inputs.user_message) }}"
    - --targets
    - "{{ with.targets }}"
    - --prices
    - "{{ with.prices | default('') }}"
    - --tolerance
    - "{{ with.tolerance | default(0.05) }}"
    - --min-trade
    - "{{ with.min_trade | default(0) }}"
    - --fee-bps
    - "{{ with.fee_bps | default(0) }}"
    - --cash-buffer
    - "{{ with.cash_buffer | default(0) }}"
    - --json
  parse: json
  timeout: 15
---

# Portfolio Rebalancer

A bundled skill for analyzing multi-asset portfolio drift, planning
fee-minimized rebalance orders, and simulating the outcome — all in
pure read-only mode by default.

## Commands

### `drift` — Analyse allocation drift

Evaluate holdings against target weights and identify positions
exceeding the configurable relative tolerance.

```bash
# From files
python3 {baseDir}/scripts/rebalancer.py drift \
  --portfolio portfolio.json \
  --targets targets.json

# With optional prices (portfolio values are quantities)
python3 {baseDir}/scripts/rebalancer.py drift \
  --portfolio portfolio.json \
  --targets targets.json \
  --prices prices.json \
  --json
```

### `plan` — Generate rebalance orders

Produces a SELL-first order sequence with dust filtering, fee
modelling, and configurable cash buffer. SELL orders are sorted
by size descending (biggest first) to raise liquidity efficiently.

```bash
python3 {baseDir}/scripts/rebalancer.py plan \
  --portfolio portfolio.json \
  --targets targets.json \
  --min-trade 50 \
  --fee-bps 30 \
  --cash-buffer 0.05 \
  --json
```

### `simulate` — Dry-run simulation

Preview turnover, estimated fees, and post-rebalance maximum drift
before executing any trades.

```bash
python3 {baseDir}/scripts/rebalancer.py simulate \
  --portfolio portfolio.json \
  --targets targets.json \
  --fee-bps 30 \
  --json
```

## Input format

### Portfolio (`--portfolio`)

```json
{
  "BTC": 1.5,
  "ETH": 20,
  "USDC": 5000,
  "SOL": 100
}
```

When `--prices` is provided, values are treated as **token quantities**
and multiplied by prices. Without `--prices`, values are treated as
**USD amounts**.

### Targets (`--targets`)

```json
{
  "BTC": 0.40,
  "ETH": 0.25,
  "USDC": 0.20,
  "SOL": 0.15
}
```

Weights are automatically normalized to sum to 1.0.

### Prices (`--prices`, optional)

```json
{
  "BTC": 62000.0,
  "ETH": 3400.0,
  "SOL": 145.0
}
```

## Output (JSON)

Every command outputs a typed JSON dictionary with `--json`:

**`drift`** includes per-asset entries with `current_weight`, `target_weight`,
`drift`, `relative_drift`, and `in_tolerance` flag, plus a top-level list
of symbols `out_of_tolerance`.

**`plan`** returns `orders` (array of `{symbol, side, value, estimated_fee}`),
`total_sell`, `total_buy`, `estimated_fees`, `dust_skipped`, `cash_buffer`,
and `cash_buffer_value`.

**`simulate`** returns `turnover`, `estimated_fees`, `max_drift_before`,
`max_drift_after`, `orders`, and `post_rebalance_weights`.

## Safety

- **Read-only by default.** All commands only analyse portfolio data;
  no transactions, signatures, or network calls are made.
- **Dry-run simulation.** Uses `--dry-run` semantics (default) — the
  `simulate` command never executes anything.
- **Deterministic.** Pure Python math, no external data sources, cached
  prices, or randomisation.