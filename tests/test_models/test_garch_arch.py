"""GARCH(1,1)-t：生成器自檢（Task 5）、估計器回收與多步（Task 6）。"""

from __future__ import annotations

import numpy as np

from tests.fixtures.synthetic import make_garch_t_returns


def test_generator_is_deterministic_and_stationary():
    a = make_garch_t_returns(1000, omega=1e-6, alpha=0.1, beta=0.85, nu=7, seed=42)
    b = make_garch_t_returns(1000, omega=1e-6, alpha=0.1, beta=0.85, nu=7, seed=42)
    assert np.allclose(a.to_numpy(), b.to_numpy())  # 同 seed 決定性
    assert len(a) == 1000
    assert np.all(np.isfinite(a.to_numpy()))
    # 樣本波動叢聚：|r| 的一階自相關為正（GARCH 特徵）
    absr = np.abs(a.to_numpy())
    ac1 = np.corrcoef(absr[:-1], absr[1:])[0, 1]
    assert ac1 > 0.05
