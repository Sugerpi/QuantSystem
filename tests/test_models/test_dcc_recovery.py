"""合成回收：模擬已知 (a*,b*,R̄*) 的 DCC(1,1) 過程，QMLE 應回收到容差內。

手寫 DCC 無 arch 那樣的 parity 參照，故以「已知真值 → 能否估回」建立正確性信心（§5a AC-2）。
"""

import numpy as np
import pandas as pd

from quantcore.models.correlation.dcc import estimate_dcc


def _simulate_dcc(a, b, R_bar, n, seed):
    """以 DCC(1,1) 動態生成標準化殘差 ε_t（單位條件變異數，相關由 R_t 驅動）。"""
    rng = np.random.default_rng(seed)
    k = R_bar.shape[0]
    Q = R_bar.copy()
    Qbar = R_bar.copy()
    E = np.empty((n, k), dtype="float64")
    e_prev = np.zeros((k, 1))
    for t in range(n):
        Q = (1 - a - b) * Qbar + a * (e_prev @ e_prev.T) + b * Q
        d = np.sqrt(np.diag(Q))
        R = Q / np.outer(d, d)
        L = np.linalg.cholesky(R + 1e-10 * np.eye(k))
        z = rng.standard_normal((k, 1))
        e = L @ z
        E[t] = e.ravel()
        e_prev = e
    idx = pd.date_range("2005-01-03", periods=n, freq="B")
    return pd.DataFrame(E, index=idx, columns=["A", "B", "C"])


def test_qmle_recovers_known_ab_within_tolerance():
    a_true, b_true = 0.05, 0.90
    R_bar = np.array([[1.0, 0.4, 0.2], [0.4, 1.0, 0.3], [0.2, 0.3, 1.0]])
    E = _simulate_dcc(a_true, b_true, R_bar, n=3000, seed=42)
    params = estimate_dcc(E, fixed_ab=(0.01, 0.96), shrink=0.10)
    # QMLE 於 3000 樣本的合理界；persistence (a+b) 通常較 a/b 個別更準
    assert abs(params.a - a_true) < 0.04
    assert abs(params.b - b_true) < 0.06
    assert abs((params.a + params.b) - (a_true + b_true)) < 0.03
    assert params.fell_back is False  # 良性合成資料應成功估計、不退回 fixed
