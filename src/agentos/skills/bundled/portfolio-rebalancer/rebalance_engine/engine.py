"""Core portfolio-rebalancer engine.

Pure-Python, deterministic, offline. All math is done in float USD
values; no network, no external deps.
"""

from __future__ import annotations

from collections.abc import Mapping

from rebalance_engine.types import (
    AssetValue,
    DriftEntry,
    DriftReport,
    Order,
    PlanReport,
    PortfolioInput,
    SimReport,
)


def _resolve_values(
    values: Mapping[str, float],
    prices: Mapping[str, float],
) -> list[AssetValue]:
    """Convert raw holdings to USD values, applying prices when present."""
    out: list[AssetValue] = []
    for symbol, qty in values.items():
        price = prices.get(symbol)
        value = qty * price if price is not None else qty
        out.append(AssetValue(symbol=symbol, value=value))
    return out


def _weights(values: list[AssetValue], total: float) -> dict[str, float]:
    return {a.symbol: a.value / total if total else 0.0 for a in values}


def analyze_drift(pf: PortfolioInput) -> DriftReport:
    """Evaluate holdings against target weights with a relative tolerance."""
    values = _resolve_values(pf.values, pf.prices)
    total = sum(a.value for a in values)
    if total <= 0:
        raise ValueError("portfolio total value must be positive")

    tolerance = 0.05  # default ±5% relative tolerance
    entries: list[DriftEntry] = []
    out_of_tolerance: list[str] = []
    max_rel = 0.0

    for a in values:
        current = a.value / total
        target = pf.targets.get(a.symbol, 0.0)
        drift = current - target
        # Relative drift vs the TARGET weight (or vs current when target is 0).
        if target != 0:
            rel = abs(drift) / target
        elif current != 0:
            rel = float("inf")
        else:
            rel = 0.0
        in_tol = rel <= tolerance
        if not in_tol:
            out_of_tolerance.append(a.symbol)
        if rel != float("inf"):
            max_rel = max(max_rel, rel)
        else:
            max_rel = max(max_rel, tolerance + 1.0)  # marks out-of-tolerance
        entries.append(
            DriftEntry(
                symbol=a.symbol,
                value=a.value,
                current_weight=current,
                target_weight=target,
                drift=drift,
                relative_drift=None if rel == float("inf") else rel,
                in_tolerance=in_tol,
            )
        )

    return DriftReport(
        entries=entries,
        total_value=total,
        tolerance=tolerance,
        max_relative_drift=max_rel,
        out_of_tolerance=out_of_tolerance,
    )


def plan_rebalance(
    pf: PortfolioInput,
    *,
    tolerance: float = 0.05,
    min_trade: float = 0.0,
    fee_bps: float = 0.0,
    cash_buffer: float = 0.0,
) -> PlanReport:
    """Generate fee-minimized rebalance orders, SELLs first."""
    values = _resolve_values(pf.values, pf.prices)
    total = sum(a.value for a in values)
    if total <= 0:
        raise ValueError("portfolio total value must be positive")

    targets = pf.targets
    # Normalize targets to sum to 1.0 (if they don't already).
    target_sum = sum(targets.values())
    norm = {k: v / target_sum for k, v in targets.items()} if target_sum else {}

    cash_buffer_value = total * cash_buffer
    # Buying power available = cash held (value not in a target) minus buffer.
    # We model "cash" as the residual: total - sum(target values).
    # Simpler and safer: available buy budget = sell proceeds - fees - cash buffer.
    sells: list[tuple[str, float]] = []
    buys: list[tuple[str, float]] = []
    dust: list[str] = []

    for a in values:
        target_w = norm.get(a.symbol, 0.0)
        desired = target_w * total
        delta = desired - a.value
        if abs(delta) < min_trade:
            dust.append(a.symbol)
            continue
        if delta < 0:
            sells.append((a.symbol, -delta))
        elif delta > 0:
            buys.append((a.symbol, delta))

    # SELLs first: liquidity sequencing. Order sells by size desc (biggest
    # first raises the most cash quickly); buys by size desc too.
    sells.sort(key=lambda t: t[1], reverse=True)
    buys.sort(key=lambda t: t[1], reverse=True)

    sell_total = sum(v for _, v in sells)
    sell_fees = sell_total * fee_bps / 10000.0
    buy_budget = sell_total - sell_fees - cash_buffer_value
    buy_total = sum(v for _, v in buys)
    # Scale buys down proportionally if they exceed available budget.
    scale = min(1.0, buy_budget / buy_total) if buy_total else 0.0

    orders: list[Order] = []
    est_fees = 0.0
    total_buy = 0.0
    for symbol, v in sells:
        fee = v * fee_bps / 10000.0
        orders.append(Order(symbol=symbol, side="SELL", value=v, estimated_fee=fee))
        est_fees += fee
    for symbol, v in buys:
        sv = v * scale
        fee = sv * fee_bps / 10000.0
        orders.append(Order(symbol=symbol, side="BUY", value=sv, estimated_fee=fee))
        est_fees += fee
        total_buy += sv

    return PlanReport(
        orders=orders,
        total_sell=sell_total,
        total_buy=total_buy,
        estimated_fees=est_fees,
        dust_skipped=dust,
        cash_buffer=cash_buffer,
        cash_buffer_value=cash_buffer_value,
    )


def simulate_rebalance(
    pf: PortfolioInput,
    plan: PlanReport,
) -> SimReport:
    """Preview turnover, fees, and post-rebalance max drift."""
    values = _resolve_values(pf.values, pf.prices)
    total = sum(a.value for a in values)
    if total <= 0:
        raise ValueError("portfolio total value must be positive")

    turnover = (plan.total_sell + plan.total_buy) / total

    # Apply orders to get post-rebalance weights.
    post = {a.symbol: a.value for a in values}
    for o in plan.orders:
        post[o.symbol] = post.get(o.symbol, 0.0) + (o.value if o.side == "BUY" else -o.value)
        # Fees reduce cash; approximate as a global cash deduction.
        post.setdefault("$CASH", 0.0)
        post["$CASH"] = post["$CASH"] - o.estimated_fee

    post_total = sum(max(v, 0.0) for v in post.values())
    target_sum = sum(pf.targets.values())
    norm = {k: v / target_sum for k, v in pf.targets.items()} if target_sum else {}

    max_before = 0.0
    max_after = 0.0
    weights_after: dict[str, float] = {}
    for a in values:
        target_w = norm.get(a.symbol, 0.0)
        before = a.value / total
        after = max(post.get(a.symbol, 0.0), 0.0) / post_total if post_total else 0.0
        weights_after[a.symbol] = after
        if target_w != 0:
            max_before = max(max_before, abs(before - target_w) / target_w)
            max_after = max(max_after, abs(after - target_w) / target_w)
        elif before != 0 or after != 0:
            max_before = max(max_before, tolerance_overflow(before, target_w))
            max_after = max(max_after, tolerance_overflow(after, target_w))

    return SimReport(
        turnover=turnover,
        estimated_fees=plan.estimated_fees,
        max_drift_before=max_before,
        max_drift_after=max_after,
        orders=plan.orders,
        post_rebalance_weights=weights_after,
    )


def tolerance_overflow(value: float, target: float) -> float:
    """Relative drift marker for zero-target assets."""
    if target == 0 and value > 0:
        return 1.0
    return abs(value - target) / target if target else 0.0
