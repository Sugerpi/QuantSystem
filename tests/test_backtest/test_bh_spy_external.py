"""AC-3：bh_spy 與外部來源的端到端體檢（規格 §9 Phase 2）。

本測試需真實快照，CI 無快照故自動 skip（見 tests/conftest.py）——它是**本機閘門**。

兩層驗證，缺一不可：

1. test_bh_spy_reproduces_snapshot_spy_total_return（**緊**，容差 0.5 bps/年）
   引擎自身正確性。自建倉執行日起算、同一組交易日，引擎 bh_spy 的複利報酬必須
   等於同一份快照 SPY 的含息總報酬——成本只影響執行日當天的水位、不影響其後的
   報酬複利，故兩者應到浮點級一致。這條用我們自己的資料把引擎釘死，與外部無關。
   **這才是 spec 所謂「對整個引擎的端到端體檢」的真正載體。**

2. test_bh_spy_cagr_matches_portfoliovisualizer（**鬆**，容差 25 bps/年）
   對外部來源的體檢。引擎 CAGR 對照 PV 的 SPY 含息 CAGR。此差異含一個**引擎外**
   的資料源項，故容差較寬；它擋的是總體性引擎錯誤，不是精密比對。

外部參照（使用者於 2026-07-18 查 portfoliovisualizer 取得）：
    期間：2006-01-03 → 2026-07-15
    標的：SPY，含息（total return）
    CAGR：11.02 %

容差推導（設計文件 §6.3——先跑出實際數字再逐項估算，不憑空指定一個剛好會過的數）：

  對快照（緊）：
    引擎自身誤差（自執行日、同窗，apples-to-apples）  = 0.0000 bps/年（實測）
    浮點/平台變異保留餘裕                              < 0.5  bps/年
    → TOL_VS_SNAPSHOT = 0.5 bps/年
    實測：引擎 11.098118 % vs 快照 11.098118 % → 0.0000 bps/年，通過。

  對 PV（鬆）：
    一次性成本（5 bps ÷ 20.49 年）                    = 0.24  bps/年（使引擎偏低）
    建倉執行延遲（INV-2 首日持現金）                  ≈ 2.5   bps/年（使引擎偏低，設計內）
    資料源差異（自建含息調整 vs PV 資料源，20 年每日
      總報酬微差複利；Phase 1 已記錄跨源單日差異可達
      數十 bps）                                       = 10.15 bps/年（實測，使引擎偏高）
    a-priori 上界（兩 provider 20 年 CAGR 分歧）       ≈ 20    bps/年
    → TOL_VS_EXTERNAL = 25 bps/年（引擎項 ~2.7 + 資料源 a-priori ~20，取整）
    實測：引擎 11.094 % vs PV 11.02 % → 7.40 bps/年，通過（遠小於容差，無總體性引擎錯誤）。

結論：引擎對自家資料精確到 0.0000 bps/年（自執行日），完全由設計內的成本與執行延遲
解釋其對總報酬的偏移；對 PV 的 7.40 bps/年殘差由引擎外的資料源差異主導。AC-3 通過。
詳見 docs/phase2-bh-spy-external-check.md。
"""

import pandas as pd
import pytest

from quantcore.config import load_config
from quantcore.data.snapshot import load_snapshot
from quantcore.experiments.runner import run_experiment

PV_CAGR = 0.1102
PERIOD = ("2006-01-03", "2026-07-15")

TOL_VS_SNAPSHOT = 0.5e-4  # 0.5 bps/年（實測 0.0000）
TOL_VS_EXTERNAL = 25e-4  # 25 bps/年（實測 7.40）

_DAYS_PER_YEAR = 252


def _cagr(nav: pd.Series) -> float:
    return (nav.iloc[-1] / nav.iloc[0]) ** (_DAYS_PER_YEAR / (len(nav) - 1)) - 1.0


def _run_bh_spy(tmp_path):
    # 兩策略一起跑：warmup 全 run 統一取 max（設計文件 §2.3），ew_menu 的 252
    # 使窗成為 2006-01-03 → 2026-07-15——即使用者查 PV 的窗。bh_spy 單獨跑時
    # warmup=0 會從 2005-01-03 起，與外部參照的窗不符。
    cfg = load_config("quantcore/config/default.yaml")
    snap = load_snapshot(cfg.snapshot)
    run_dir = run_experiment(
        cfg=cfg,
        snapshot=snap,
        out_root=tmp_path,
        label="ac3",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T00:00:00"),
    )
    nav = (
        pd.read_parquet(run_dir / "nav.parquet")
        .query("strategy_id == 'bh_spy'")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return cfg, snap, run_dir, nav


@pytest.mark.requires_snapshot
def test_bh_spy_reproduces_snapshot_spy_total_return(tmp_path):
    """引擎自身正確性（緊）：自執行日起算，引擎 == 快照 SPY 含息總報酬（浮點級）。"""
    _, snap, run_dir, nav = _run_bh_spy(tmp_path)

    weights = pd.read_parquet(run_dir / "weights.parquet")
    exec_day = weights.query("strategy_id == 'bh_spy' and ticker == 'SPY' and weight == 1.0")[
        "date"
    ].min()

    eng = _cagr(nav[nav["date"] >= exec_day]["nav"].reset_index(drop=True))

    spy = snap["prices"].query("ticker == 'SPY'").sort_values("date")
    bench_win = spy[(spy["date"] >= exec_day) & (spy["date"] <= nav["date"].max())]
    bench = _cagr(bench_win["adj_close"].reset_index(drop=True))

    assert eng == pytest.approx(bench, abs=TOL_VS_SNAPSHOT)


@pytest.mark.requires_snapshot
def test_bh_spy_cagr_matches_portfoliovisualizer(tmp_path):
    """對外部來源的體檢（鬆）：引擎 CAGR ≈ PV 的 SPY 含息 CAGR。"""
    _, _, _, nav = _run_bh_spy(tmp_path)

    # 外部數字綁定於特定窗；warmup/start 若改動使窗位移，此比對即失效，須大聲失敗。
    assert nav["date"].min().strftime("%Y-%m-%d") == PERIOD[0]
    assert nav["date"].max().strftime("%Y-%m-%d") == PERIOD[1]

    eng = _cagr(nav["nav"])
    assert eng == pytest.approx(PV_CAGR, abs=TOL_VS_EXTERNAL)
