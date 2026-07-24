"""Phase 4 AC 本機閘門（需真實快照，CI 無快照乾淨 skip，比照 Phase 2 AC-3）。

驗收：
- σ*±2% 條件式量測：voltarget_only 全期落 8-12%、full 在 absmom 大致全過期間落 8-12%。
- 七策略消融比較表（baseline 格）+ full vs 各消融版配對 bootstrap 產出。

§7.3 的完整敏感度格（top_k/vol_target/momentum_lookback/cost_bps）為研究交付物，
以 run_ablation 的 param_grid 產出（~30-45 分），非此閘門的例行斷言——本閘門用
baseline 格（空 grid）快速守護 AC 不回歸。

實測（快照 2026-07-16_20ed09）：voltarget_only 9.64%、full 閾值 9.86%；full 對每個
消融版的 Sharpe/Calmar 配對 CI 皆含 0（優勢不顯著，§6.3 合格結論——見 PROGRESS）。
"""

from __future__ import annotations

import pandas as pd
import pytest

pytestmark = pytest.mark.requires_snapshot

SEVEN = ["bh_spy", "ew_menu", "sixty_forty", "mom_only", "voltarget_only", "mom_ivol", "full"]


def test_seven_strategy_ablation_and_vol_target_ac(tmp_path):
    from quantcore.config import load_config
    from quantcore.data.snapshot import load_snapshot
    from quantcore.experiments.ablation import run_ablation
    from quantcore.experiments.runner import run_experiment
    from quantcore.experiments.vol_target_ac import measure_vol_target_ac

    cfg = load_config("quantcore/config/default.yaml")
    snapshot = load_snapshot(cfg.snapshot)

    # AC-1：七策略消融比較表（baseline 格）+ 配對 bootstrap
    run_dir = run_ablation(cfg, snapshot, SEVEN, {}, tmp_path, "phase4")
    table = pd.read_parquet(run_dir / "comparison.parquet")
    assert set(table["strategy_id"]) == set(SEVEN)
    bootstrap = pd.read_parquet(run_dir / "bootstrap.parquet")
    assert set(bootstrap["vs"]) == {s for s in SEVEN if s != "full"}
    assert set(bootstrap["metric"]) == {"sharpe", "calmar"}

    # AC-2：σ*±2% 條件式量測（需完整 run 的 decisions/nav）
    exp_dir = run_experiment(cfg, snapshot, tmp_path, "phase4_full", SEVEN)
    ac = measure_vol_target_ac(exp_dir, cfg.stats.absmom_cash_threshold)
    # voltarget_only（無 absmom）= 波動目標乾淨測：全期實現波動落 8-12%
    assert ac["voltarget_only"]["passes"], ac["voltarget_only"]
    # full = 條件式：absmom 大致全過期間實現波動落 8-12%（隔離波動目標層）
    assert ac["full_threshold"]["passes"], ac["full_threshold"]
