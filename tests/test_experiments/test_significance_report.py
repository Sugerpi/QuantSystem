"""significance_report CLI 產物 + INV-6 測試。

注意：不用 default.yaml 的真實快照——那是 20 檔 2005-2026 全歷史，
「full」策略走生產參數（garch_window=1000、momentum_lookback=252），
單次 run_ablation 需數分鐘，不適合單元測試常跑的節奏。改採
tests/test_experiments/test_ablation.py 既有的合成快照慣例
（tests/fixtures/synthetic.py：小型 in-memory 快照 + ewma 波動模型），
只讓 build_significance_report 本體吃真實的 comparison/cell_returns/manifest 產物，
邏輯不動。
"""

import json

import numpy as np

from quantcore.experiments.ablation import run_ablation
from quantcore.experiments.significance_report import build_significance_report
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot


def _make_ablation_run(tmp_path):
    n = 300
    dates = make_dates(n)
    rng = np.random.default_rng(7)
    tickers = ["A", "B", "C", "D", "E", "F"]
    prices = {
        tk: list(100 * np.cumprod(1 + rng.normal(0.0003 * (i + 1), 0.01, n)))
        for i, tk in enumerate(tickers)
    }
    snap = make_snapshot(prices, dates)
    cfg = make_cfg(
        tickers,
        risk={"vol_model": "ewma", "vol_window": 10},
        signal={"top_k": 2, "momentum_lookback": 20, "momentum_skip": 2},
        universe={"min_history_days": 25},
        schedule={"selection_interval": 5, "exposure_check_interval": 2},
        stats={"pbo_n_splits": 4, "mc_permutations": 50},
    )
    run_dir = run_ablation(
        cfg, snap, ["full", "mom_ivol"], {"signal.top_k": [3, 5]}, tmp_path, "sig"
    )
    return cfg, snap, run_dir


def test_significance_json_schema(tmp_path):
    cfg, snap, run_dir = _make_ablation_run(tmp_path)
    out = build_significance_report(cfg, snap, run_dir)
    data = json.loads((run_dir / "significance.json").read_text(encoding="utf-8"))
    assert data == out
    assert set(data) == {"provenance", "dsr", "pbo", "permutation"}
    assert data["provenance"]["N"] >= 2
    assert data["dsr"]["strategy"] == "full"
    assert set(data["dsr"]) >= {"sr", "psr", "expected_max_sr", "dsr", "n_days", "skew", "kurt"}
    assert data["pbo"]["n_candidates"] == data["provenance"]["N"]
    assert isinstance(data["permutation"], list) and len(data["permutation"]) >= 1


def test_significance_reproducible(tmp_path):
    cfg, snap, run_dir = _make_ablation_run(tmp_path)
    build_significance_report(cfg, snap, run_dir)
    first = (run_dir / "significance.json").read_bytes()
    build_significance_report(cfg, snap, run_dir)
    second = (run_dir / "significance.json").read_bytes()
    assert first == second  # INV-6：同 seed 位元一致
