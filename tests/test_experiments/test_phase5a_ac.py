"""Phase 5a AC 本機閘門（需真實快照，CI 無快照乾淨 skip）。

驗收：波動目標層在 corr_model ∈ {ewma, dcc} 兩者下皆運作——voltarget_only 全期、
full 在 absmom 大致全過期間，實現波動皆落 σ*=10%±2%（8-12%）。相關模型只影響
σ̂_p→曝險純量（權重仍 inverse-vol，ERC 為 5b），故此閘門確認換相關來源不破波動目標。

DCC vs EWMA 的消融結論（風險預測品質 + 績效）寫入 PROGRESS，非此閘門斷言。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.requires_snapshot


@pytest.mark.parametrize("corr_model", ["ewma", "dcc"])
def test_vol_target_ac_holds_under_corr_model(tmp_path, corr_model):
    from quantcore.config import load_config
    from quantcore.data.snapshot import load_snapshot
    from quantcore.experiments.runner import run_experiment
    from quantcore.experiments.vol_target_ac import measure_vol_target_ac

    cfg = load_config("quantcore/config/default.yaml")
    cfg = cfg.model_copy(update={"risk": cfg.risk.model_copy(update={"corr_model": corr_model})})
    snapshot = load_snapshot(cfg.snapshot)

    exp_dir = run_experiment(
        cfg, snapshot, tmp_path, f"phase5a_{corr_model}", ["voltarget_only", "full"]
    )
    ac = measure_vol_target_ac(exp_dir, cfg.stats.absmom_cash_threshold)
    assert ac["voltarget_only"]["passes"], (corr_model, ac["voltarget_only"])
    assert ac["full_threshold"]["passes"], (corr_model, ac["full_threshold"])
