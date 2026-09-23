import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/agentos/skills/bundled/gmgn-wallet-score/scripts/score.py"


def _stats(*, realized_profit: float, bought_cost: float, roi: float | None) -> dict:
    return {
        "buy": 0,
        "sell": 10,
        "realized_profit": realized_profit,
        "bought_cost": bought_cost,
        "realized_profit_pnl": roi,
        "pnl": None,
        "pnl_stat": {
            "token_num": 8,
            "winrate": 0.7,
            "avg_holding_period": 500000,
            "pnl_gt_5x_num": 1,
            "pnl_2x_5x_num": 1,
            "pnl_0x_2x_num": 4,
            "pnl_nd5_0x_num": 1,
            "pnl_lt_nd5_num": 1,
        },
        "common": {"created_token_count": 0},
    }


def _run_score(monkeypatch, stats: dict) -> str:
    import contextlib
    import importlib.util
    import io

    seen = []

    class _FakeCompleted:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        assert cmd[0] == "gmgn-cli"
        argv = cmd[1:]
        if argv[:2] == ["portfolio", "stats"]:
            return _FakeCompleted(json.dumps(stats))
        if argv[:2] == ["portfolio", "activity"]:
            return _FakeCompleted(json.dumps({"activities": [], "next": None}))
        raise AssertionError(f"unexpected gmgn-cli invocation: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "0xWalletAddress", "bsc", "en"])

    spec = importlib.util.spec_from_file_location("gmgn_score_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        spec.loader.exec_module(module)
    return buf.getvalue()


def test_undefined_window_roi_shows_na_not_zero(monkeypatch):
    stdout = _run_score(monkeypatch, _stats(realized_profit=8000.0, bought_cost=0.0, roi=None))
    assert "ROI +0.0%" not in stdout
    assert "ROI n/a" in stdout
    assert "7-day ROI undefined" in stdout


def test_undefined_window_roi_does_not_claim_genuine_record(monkeypatch):
    stdout = _run_score(monkeypatch, _stats(realized_profit=8000.0, bought_cost=0.0, roi=None))
    assert "Genuine track record" not in stdout
