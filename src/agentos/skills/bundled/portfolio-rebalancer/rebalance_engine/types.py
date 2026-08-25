"""Typed data structures for the portfolio-rebalancer engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AssetValue:
    """Market value of one asset in the portfolio."""

    symbol: str
    value: float


@dataclass(frozen=True)
class DriftEntry:
    """Per-asset drift analysis result."""

    symbol: str
    value: float
    current_weight: float
    target_weight: float
    drift: float
    relative_drift: float | None
    in_tolerance: bool


@dataclass(frozen=True)
class DriftReport:
    """Full drift analysis output."""

    entries: list[DriftEntry]
    total_value: float
    tolerance: float
    max_relative_drift: float
    out_of_tolerance: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "total_value": round(self.total_value, 6),
            "tolerance": self.tolerance,
            "max_relative_drift": round(self.max_relative_drift, 6),
            "entries": [
                {
                    "symbol": e.symbol,
                    "value": round(e.value, 6),
                    "current_weight": round(e.current_weight, 6),
                    "target_weight": round(e.target_weight, 6),
                    "drift": round(e.drift, 6),
                    "relative_drift": (
                        round(e.relative_drift, 6) if e.relative_drift is not None else None
                    ),
                    "in_tolerance": e.in_tolerance,
                }
                for e in self.entries
            ],
            "out_of_tolerance": self.out_of_tolerance,
        }


@dataclass(frozen=True)
class Order:
    """A single planned rebalance order."""

    symbol: str
    side: str  # "SELL" | "BUY"
    value: float
    estimated_fee: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "value": round(self.value, 6),
            "estimated_fee": round(self.estimated_fee, 6),
        }


@dataclass(frozen=True)
class PlanReport:
    """Planned rebalance orders plus summary metrics."""

    orders: list[Order]
    total_sell: float
    total_buy: float
    estimated_fees: float
    dust_skipped: list[str]
    cash_buffer: float
    cash_buffer_value: float

    def to_dict(self) -> dict[str, object]:
        return {
            "orders": [o.to_dict() for o in self.orders],
            "total_sell": round(self.total_sell, 6),
            "total_buy": round(self.total_buy, 6),
            "estimated_fees": round(self.estimated_fees, 6),
            "dust_skipped": self.dust_skipped,
            "cash_buffer": self.cash_buffer,
            "cash_buffer_value": round(self.cash_buffer_value, 6),
        }


@dataclass(frozen=True)
class SimReport:
    """Dry-run simulation result."""

    turnover: float
    estimated_fees: float
    max_drift_before: float
    max_drift_after: float
    orders: list[Order]
    post_rebalance_weights: dict[str, float]

    def to_dict(self) -> dict[str, object]:
        return {
            "turnover": round(self.turnover, 6),
            "estimated_fees": round(self.estimated_fees, 6),
            "max_drift_before": round(self.max_drift_before, 6),
            "max_drift_after": round(self.max_drift_after, 6),
            "orders": [o.to_dict() for o in self.orders],
            "post_rebalance_weights": {
                k: round(v, 6) for k, v in self.post_rebalance_weights.items()
            },
        }


@dataclass(frozen=True)
class PortfolioInput:
    """Parsed and validated portfolio input."""

    values: dict[str, float] = field(default_factory=dict)
    targets: dict[str, float] = field(default_factory=dict)
    prices: dict[str, float] = field(default_factory=dict)
