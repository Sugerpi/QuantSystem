"""Phase 5b AC 本機閘門（需真實快照，CI 無快照乾淨 skip）。

驗收：full（inverse_vol）與 full_erc（ERC）皆跑完整回測、
產出比較表 + full vs full_erc 配對 bootstrap。
ERC vs inverse-vol 的消融結論寫入 PROGRESS（非此斷言）。
"""

from __future__ import annotations

import pandas as pd
import pytest

pytestmark = pytest.mark.requires_snapshot


def test_full_and_full_erc_ablation(tmp_path):
    from quantcore.config import load_config
    from quantcore.data.snapshot import load_snapshot
    from quantcore.experiments.ablation import run_ablation

    cfg = load_config("quantcore/config/default.yaml")
    snapshot = load_snapshot(cfg.snapshot)
    run_dir = run_ablation(cfg, snapshot, ["full", "full_erc"], {}, tmp_path, "phase5b")
    table = pd.read_parquet(run_dir / "comparison.parquet")
    assert set(table["strategy_id"]) == {"full", "full_erc"}
    bootstrap = pd.read_parquet(run_dir / "bootstrap.parquet")
    assert set(bootstrap["vs"]) == {"full_erc"}  # full 為 anchor
    assert set(bootstrap["metric"]) == {"sharpe", "calmar"}
