"""AC-2：決策 diagnostics 完整落盤（規格 §6.2）。

本測試共同定義「落盤契約」：dict/list diagnostics 欄以 JSON 字串存
（見 experiments/runner.py::_diagnostics_row）。日後若出現 decisions reader
抽象，應遷移為走真實讀取路徑，而非直接 json.loads 欄位。
"""

import json

import pandas as pd
import pytest

from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_cfg, make_dates, make_snapshot

_JSON_DIAG = ["momentum_scores", "absmom", "sigma_hat", "w_risky", "eligible", "selected"]
_PHASE4_EXPOSURE = ["sigma_p", "exposure_raw", "exposure_applied", "band_blocked"]


def test_mom_ivol_decisions_have_full_diagnostics(tmp_path):
    dates = make_dates(30)
    prices = {
        "WIN": [10.0 + i * 0.6 for i in range(30)],
        "MID": [10.0 + i * 0.3 for i in range(30)],
        "LOSE": [40.0 - i * 0.3 for i in range(30)],
        "SPY": [100.0 + i * 0.2 for i in range(30)],
        "IEF": [50.0 + i * 0.05 for i in range(30)],
    }
    snap = make_snapshot(prices, dates)
    cfg = make_cfg(
        ["WIN", "MID", "LOSE", "SPY", "IEF"],
        signal={"momentum_lookback": 4, "momentum_skip": 1, "top_k": 2},
        universe={"min_history_days": 5},
        risk={"vol_model": "rolling_std", "vol_window": 3},
        schedule={"selection_interval": 3, "exposure_check_interval": 2},
        backtest={"start": dates[0].date().isoformat(), "initial_nav": 1.0},
    )
    run_dir = run_experiment(
        cfg=cfg, snapshot=snap, out_root=tmp_path, label="t", strategy_ids=["mom_ivol"]
    )
    dec = pd.read_parquet(run_dir / "decisions.parquet")
    assert len(dec) > 0

    # 完整落盤：每一列（不只首列）的 Phase-3 diagnostics 欄皆為非空 JSON
    for col in _JSON_DIAG:
        assert dec[col].notna().all()
        assert dec[col].map(lambda s: bool(json.loads(s))).all()

    # key 完整性（§6.2）：scores 只涵蓋合格者、selected 取自有分數者、
    # w_risky/absmom 對齊 selected，且 w_risky 和為 1
    for _, row in dec.iterrows():
        eligible = set(json.loads(row["eligible"]))
        selected = set(json.loads(row["selected"]))
        scores = set(json.loads(row["momentum_scores"]))
        assert scores <= eligible
        assert selected <= scores
        assert set(json.loads(row["w_risky"])) == selected
        assert set(json.loads(row["absmom"])) == selected
        assert sum(json.loads(row["w_risky"]).values()) == pytest.approx(1.0)

    # Phase 3 不得洩漏任何 Phase 4 曝險欄：全數列皆為缺值
    for col in _PHASE4_EXPOSURE:
        assert dec[col].isna().all()
