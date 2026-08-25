"""Offline regression tests for the portfolio-rebalancer skill.

Pure math, no network, deterministic.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parents[1] / "src/agentos/skills/bundled/portfolio-rebalancer"
sys.path.insert(0, str(_SKILL_DIR))

# We test the engine directly; the CLI is thin.
from rebalance_engine.engine import (  # noqa: E402
    analyze_drift,
    plan_rebalance,
    simulate_rebalance,
)
from rebalance_engine.types import PortfolioInput  # noqa: E402

# ── Example data ─────────────────────────────────────────────────────


def _equity_pf() -> PortfolioInput:
    return PortfolioInput(
        values={"AAPL": 5000, "GOOG": 3000, "MSFT": 1500, "AMZN": 500},
        targets={"AAPL": 0.40, "GOOG": 0.30, "MSFT": 0.20, "AMZN": 0.10},
    )


def _crypto_pf() -> PortfolioInput:
    return PortfolioInput(
        values={"BTC": 2.0, "ETH": 30, "SOL": 500, "USDC": 2000},
        targets={"BTC": 0.45, "ETH": 0.25, "SOL": 0.15, "USDC": 0.15},
        prices={"BTC": 60000, "ETH": 3300, "SOL": 140, "USDC": 1},
    )


# ── Drift ─────────────────────────────────────────────────────────────


class TestDrift:
    def test_equal_weights_no_drift(self) -> None:
        pf = PortfolioInput(
            values={"A": 500, "B": 300, "C": 200},
            targets={"A": 0.5, "B": 0.3, "C": 0.2},
        )
        rep = analyze_drift(pf)
        assert all(e.in_tolerance for e in rep.entries)
        assert len(rep.out_of_tolerance) == 0

    def test_drifting_portfolio_detected(self) -> None:
        pf = PortfolioInput(
            values={"A": 700, "B": 200, "C": 100},
            targets={"A": 0.5, "B": 0.3, "C": 0.2},
        )
        rep = analyze_drift(pf)
        # Relative tolerance 5%: every position drifts far more than 5% of
        # its target weight, so all three are flagged.
        #   A: 70% vs 50% → rel 40% | B: 20% vs 30% → rel 33% | C: 10% vs 20% → rel 50%
        assert set(rep.out_of_tolerance) == {"A", "B", "C"}
        assert rep.max_relative_drift == 0.5

    def test_zero_target_asset(self) -> None:
        """An asset with no target weight is always out of tolerance."""
        pf = PortfolioInput(
            values={"A": 400, "B": 300, "C": 200, "D": 100},
            targets={"A": 0.4, "B": 0.3, "C": 0.2, "E": 0.1},  # D has no target, E not held
        )
        rep = analyze_drift(pf)
        assert "D" in rep.out_of_tolerance

    def test_equity_pf(self) -> None:
        pf = _equity_pf()
        rep = analyze_drift(pf)
        assert abs(rep.total_value - 10000) < 0.01
        # GOOG is exactly at its 30% target; every other holding is far past
        # the 5% relative tolerance.
        assert set(rep.out_of_tolerance) == {"AAPL", "MSFT", "AMZN"}

    def test_crypto_pf(self) -> None:
        pf = _crypto_pf()
        rep = analyze_drift(pf)
        btc_qty = 2.0
        btc_val = btc_qty * 60000  # 120000
        total = btc_val + 30 * 3300 + 500 * 140 + 2000 * 1
        assert abs(rep.total_value - total) < 0.01


# ── Plan ──────────────────────────────────────────────────────────────


class TestPlan:
    def test_no_rebalance_needed(self) -> None:
        pf = PortfolioInput(
            values={"A": 50, "B": 30, "C": 20},
            targets={"A": 0.5, "B": 0.3, "C": 0.2},
        )
        plan = plan_rebalance(pf, tolerance=0.05)  # no drift > 5%
        assert len(plan.orders) == 0

    def test_sells_first(self) -> None:
        """SELL orders must precede BUY orders."""
        pf = PortfolioInput(
            values={"A": 700, "B": 200, "C": 100},
            targets={"A": 0.5, "B": 0.3, "C": 0.2},
        )
        plan = plan_rebalance(pf, min_trade=0)
        seen_buy = False
        for o in plan.orders:
            if o.side == "BUY":
                seen_buy = True
            if o.side == "SELL":
                assert not seen_buy, "BUY before SELL"

    def test_dust_filter(self) -> None:
        pf = PortfolioInput(
            values={"A": 600, "B": 300, "C": 100},
            targets={"A": 0.5, "B": 0.3, "C": 0.2},
        )
        # A over by ~100, C under by ~100. At min_trade=90, C's 100 trade stays.
        plan = plan_rebalance(pf, min_trade=90)
        assert len(plan.orders) > 0
        # At min_trade=110, C's 100 trade is dust
        plan2 = plan_rebalance(pf, min_trade=110)
        assert len(plan2.orders) == 0 or "C" in plan2.dust_skipped

    def test_fees(self) -> None:
        pf = PortfolioInput(
            values={"A": 600, "B": 400},
            targets={"A": 0.5, "B": 0.5},
        )
        plan = plan_rebalance(pf, min_trade=0, fee_bps=30)  # 30 bps = 0.3%
        # A sells 100, B buys 100 (approx). fee = 100 * 0.003 = 0.3
        assert plan.estimated_fees > 0
        for o in plan.orders:
            assert o.estimated_fee > 0

    def test_cash_buffer(self) -> None:
        pf = PortfolioInput(
            values={"A": 1000, "B": 0},
            targets={"A": 0.5, "B": 0.5},
        )
        plan = plan_rebalance(pf, min_trade=0, cash_buffer=0.1)
        # A sells ~500, B buys ~450 (10% of 1000 = 100 buffer)
        assert plan.cash_buffer_value > 0
        assert plan.cash_buffer_value == 100.0


# ── Simulate ──────────────────────────────────────────────────────────


class TestSimulate:
    def test_sim_improves_drift(self) -> None:
        pf = PortfolioInput(
            values={"A": 700, "B": 200, "C": 100},
            targets={"A": 0.5, "B": 0.3, "C": 0.2},
        )
        plan = plan_rebalance(pf, min_trade=0)
        sim = simulate_rebalance(pf, plan)
        assert sim.max_drift_after <= sim.max_drift_before

    def test_turnover(self) -> None:
        pf = PortfolioInput(
            values={"A": 500, "B": 500},
            targets={"A": 0.3, "B": 0.7},
        )
        plan = plan_rebalance(pf, min_trade=0)
        sim = simulate_rebalance(pf, plan)
        # A sells 200, B buys 200 → turnover = 400/1000 = 0.4
        assert abs(sim.turnover - 0.4) < 0.01


# ── CLI smoke ─────────────────────────────────────────────────────────


class TestCLI:
    def test_cli_drift_json(self) -> None:
        pf_data = json.dumps({"A": 50, "B": 30, "C": 20})
        tg_data = json.dumps({"A": 0.5, "B": 0.3, "C": 0.2})
        result = subprocess.run(
            [
                sys.executable,
                str(_SKILL_DIR / "scripts" / "rebalancer.py"),
                "drift",
                "--portfolio-inline",
                pf_data,
                "--targets-inline",
                tg_data,
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_value"] == 100.0

    def test_cli_plan_json(self) -> None:
        pf_data = json.dumps({"A": 700, "B": 200, "C": 100})
        tg_data = json.dumps({"A": 0.5, "B": 0.3, "C": 0.2})
        result = subprocess.run(
            [
                sys.executable,
                str(_SKILL_DIR / "scripts" / "rebalancer.py"),
                "plan",
                "--portfolio-inline",
                pf_data,
                "--targets-inline",
                tg_data,
                "--min-trade",
                "0",
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "orders" in data
        assert len(data["orders"]) > 0
