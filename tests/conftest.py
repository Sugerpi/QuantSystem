"""全域 pytest 設定。

snapshots/ 為 gitignore（規格 §2.1：hash 進版控而非資料本身），CI 上不存在真實快照。
標記 requires_snapshot 的測試在快照缺席時自動 skip，而非紅燈。

代價要說清楚：這使 Phase 2 的 AC-3（bh_spy 對外部來源的端到端體檢）成為**本機閘門**
而非 CI 閘門。INV-1/2/5/6 一律用 tests/fixtures/ 的合成迷你快照，故不受影響。
"""

from pathlib import Path

import pytest

from quantcore.config import load_config

CONFIG_YAML = "quantcore/config/default.yaml"


@pytest.fixture(scope="session")
def real_snapshot_dir() -> Path:
    return Path(load_config(CONFIG_YAML).snapshot)


def pytest_runtest_setup(item):
    if "requires_snapshot" in item.keywords:
        d = Path(load_config(CONFIG_YAML).snapshot)
        if not (d / "MANIFEST.json").exists():
            pytest.skip(f"無真實快照（{d}）——CI 環境預期如此")
