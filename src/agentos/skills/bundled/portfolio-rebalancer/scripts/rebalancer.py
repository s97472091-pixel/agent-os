#!/usr/bin/env python3
"""portfolio-rebalancer CLI.

Pure read-only rebalance planning: drift analysis, order planning, and
dry-run simulation. Emits typed JSON on stdout for AgentOS runtime and
sub-agent ingestion.

Examples:
    python3 rebalancer.py drift --portfolio pf.json --targets tg.json
    python3 rebalancer.py plan --portfolio pf.json --targets tg.json --min-trade 50 --fee-bps 30
    python3 rebalancer.py simulate --portfolio pf.json --targets tg.json --cash-buffer 0.05 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure rebalance_engine is importable when the script is run directly.
_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPT_DIR.parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

from rebalance_engine.engine import (  # noqa: E402
    analyze_drift,
    plan_rebalance,
    simulate_rebalance,
)
from rebalance_engine.types import PortfolioInput  # noqa: E402


def _load_json(path: str | None, inline: str | None) -> dict[str, Any]:
    if inline:
        try:
            return json.loads(inline)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid inline JSON: {exc}") from exc
    if not path:
        raise ValueError("one of --portfolio-file/--inline or --targets-file/--inline is required")
    p = Path(path)
    if not p.exists():
        raise ValueError(f"file not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def _fmt(v: float) -> str:
    return f"{v:,.2f}"


def _print_drift(report: Any, json_out: bool) -> None:
    if json_out:
        print(json.dumps(report.to_dict(), indent=2))
        return
    print(f"Total value: ${_fmt(report.total_value)}")
    print(f"Tolerance: {report.tolerance * 100:.1f}% relative")
    print(f"Max relative drift: {report.max_relative_drift * 100:.1f}%")
    print()
    print(f"{'SYMBOL':<12}{'VALUE':>14}{'CURRENT':>10}{'TARGET':>10}{'DRIFT':>10}{'OK':>6}")
    for e in report.entries:
        print(
            f"{e.symbol:<12}{_fmt(e.value):>14}"
            f"{e.current_weight * 100:>9.1f}%{e.target_weight * 100:>9.1f}%"
            f"{e.drift * 100:>9.1f}%{'✓' if e.in_tolerance else '✗':>6}"
        )
    if report.out_of_tolerance:
        print(f"\nOut of tolerance: {', '.join(report.out_of_tolerance)}")
    else:
        print("\nAll positions within tolerance.")


def _print_plan(report: Any, json_out: bool) -> None:
    if json_out:
        print(json.dumps(report.to_dict(), indent=2))
        return
    print(f"{'SIDE':<6}{'SYMBOL':<12}{'VALUE':>14}{'FEE':>10}")
    for o in report.orders:
        print(f"{o.side:<6}{o.symbol:<12}{_fmt(o.value):>14}{_fmt(o.estimated_fee):>10}")
    print()
    print(f"Total SELL: ${_fmt(report.total_sell)}")
    print(f"Total BUY:  ${_fmt(report.total_buy)}")
    print(f"Est. fees:  ${_fmt(report.estimated_fees)}")
    print(f"Cash buffer: {report.cash_buffer * 100:.1f}% (${_fmt(report.cash_buffer_value)})")
    if report.dust_skipped:
        print(f"Dust skipped: {', '.join(report.dust_skipped)}")


def _print_sim(report: Any, json_out: bool) -> None:
    if json_out:
        print(json.dumps(report.to_dict(), indent=2))
        return
    print(f"Turnover:            {report.turnover * 100:.1f}%")
    print(f"Estimated fees:      ${_fmt(report.estimated_fees)}")
    print(f"Max drift before:    {report.max_drift_before * 100:.1f}%")
    print(f"Max drift after:     {report.max_drift_after * 100:.1f}%")
    print()
    print(f"{'SIDE':<6}{'SYMBOL':<12}{'VALUE':>14}{'FEE':>10}")
    for o in report.orders:
        print(f"{o.side:<6}{o.symbol:<12}{_fmt(o.value):>14}{_fmt(o.estimated_fee):>10}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rebalancer", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("drift", "evaluate holdings against target weights"),
        ("plan", "generate SELL-first rebalance orders"),
        ("simulate", "preview turnover, fees, and post-rebalance drift"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--portfolio", dest="portfolio_file", help="portfolio JSON file")
        p.add_argument("--portfolio-inline", dest="portfolio_inline", help="portfolio JSON inline")
        p.add_argument("--targets", dest="targets_file", help="target weights JSON file")
        p.add_argument("--targets-inline", dest="targets_inline", help="target weights JSON inline")
        p.add_argument("--prices", dest="prices_file", help="optional prices JSON file")
        p.add_argument(
            "--tolerance",
            type=float,
            default=0.05,
            help="relative tolerance (default 0.05)",
        )
        p.add_argument(
            "--min-trade",
            type=float,
            default=0.0,
            help="skip dust below this USD value",
        )
        p.add_argument(
            "--fee-bps",
            type=float,
            default=0.0,
            help="estimated fee in basis points",
        )
        p.add_argument(
            "--cash-buffer",
            type=float,
            default=0.0,
            help="cash buffer as fraction of total",
        )
        p.add_argument("--json", action="store_true", help="emit typed JSON on stdout")

    args = parser.parse_args(argv)

    try:
        portfolio = _load_json(args.portfolio_file, args.portfolio_inline)
        targets = _load_json(args.targets_file, args.targets_inline)
        prices = _load_json(args.prices_file, None) if args.prices_file else {}
        pf = PortfolioInput(
            values={str(k): float(v) for k, v in portfolio.items()},
            targets={str(k): float(v) for k, v in targets.items()},
            prices={str(k): float(v) for k, v in prices.items()},
        )
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.command == "drift":
            report = analyze_drift(pf)
            _print_drift(report, args.json)
        elif args.command == "plan":
            report = plan_rebalance(
                pf,
                tolerance=args.tolerance,
                min_trade=args.min_trade,
                fee_bps=args.fee_bps,
                cash_buffer=args.cash_buffer,
            )
            _print_plan(report, args.json)
        elif args.command == "simulate":
            plan = plan_rebalance(
                pf,
                tolerance=args.tolerance,
                min_trade=args.min_trade,
                fee_bps=args.fee_bps,
                cash_buffer=args.cash_buffer,
            )
            report = simulate_rebalance(pf, plan)
            _print_sim(report, args.json)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
