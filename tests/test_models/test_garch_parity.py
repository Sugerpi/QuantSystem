"""手刻 GARCH(1,1)-t vs arch 的 parity test（規格 §5.2、Phase 6 AC）。

本機閘門（需真實快照，CI 無 parquet 乾淨 skip，比照 Phase 2 AC-3）。
AC：≥5 檔真實 ETF 上，參數 (ω,α,β,ν) 相對誤差 <1%、21 步波動預測相對誤差 <0.5%。

方法：對快照每檔資產以「同一份報酬序列」同時 fit GarchArch 與 GarchOwn，逐檔比對。
任一模型退化（GarchDegenerateError）的資產不列入 parity 比對（那是 fallback 案例，
非 parity 案例）；要求「兩者皆收斂」的資產 ≥5 檔且全數通過門檻。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantcore.config import load_config
from quantcore.data.snapshot import load_snapshot
from quantcore.models.volatility.base import GarchDegenerateError
from quantcore.models.volatility.garch_arch import GarchArch
from quantcore.models.volatility.garch_own import GarchOwn

pytestmark = pytest.mark.requires_snapshot

CONFIG_YAML = "quantcore/config/default.yaml"
PARAM_REL_TOL = 0.01  # <1% 參數相對誤差（§5.2）
FORECAST_REL_TOL = 0.005  # <0.5% 21 步預測相對誤差（§5.2）
HORIZON = 21
MIN_ASSETS = 5


def _returns_by_ticker(snapshot: dict) -> dict[str, pd.Series]:
    prices = snapshot["prices"]
    out: dict[str, pd.Series] = {}
    for ticker, grp in prices.groupby("ticker"):
        s = grp.sort_values("date").set_index("date")["adj_close"].astype("float64")
        out[ticker] = s.pct_change().dropna()
    return out


def _annualized_forecast_vol(model, horizon: int) -> float:
    per_step_var = model.forecast(horizon)  # 已還原 ÷100²
    return float(np.sqrt(per_step_var.mean()) * np.sqrt(252))


def test_garch_own_parity_with_arch():
    cfg = load_config(CONFIG_YAML)
    rets = _returns_by_ticker(load_snapshot(cfg.snapshot))

    compared: list[str] = []
    for ticker in sorted(rets):
        r = rets[ticker]
        # 兩模型都要收斂才能 parity 比對；任一退化即為 fallback 案例，跳過
        try:
            arch_m = GarchArch().fit(r)
            own_m = GarchOwn().fit(r)
        except GarchDegenerateError:
            continue

        pa, po = arch_m.params, own_m.params
        for k in ("omega", "alpha", "beta", "nu"):
            rel = abs(po[k] - pa[k]) / abs(pa[k])
            assert rel < PARAM_REL_TOL, (
                f"{ticker} 參數 {k}: own={po[k]:.6g} arch={pa[k]:.6g} rel={rel:.4%}"
            )

        ann_a = _annualized_forecast_vol(arch_m, HORIZON)
        ann_o = _annualized_forecast_vol(own_m, HORIZON)
        rel_f = abs(ann_o - ann_a) / ann_a
        assert rel_f < FORECAST_REL_TOL, (
            f"{ticker} {HORIZON}步預測: own={ann_o:.6g} arch={ann_a:.6g} rel={rel_f:.4%}"
        )

        compared.append(ticker)

    assert len(compared) >= MIN_ASSETS, (
        f"僅 {len(compared)} 檔兩模型皆收斂並比對（{compared}），需 ≥{MIN_ASSETS}"
    )
