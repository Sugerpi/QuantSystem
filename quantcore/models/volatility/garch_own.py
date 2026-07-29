"""手刻 GARCH(1,1)-t（規格 §5.2，Phase 6 學習里程碑）。

不呼叫 arch 的 fit：自行實作變異數遞迴、Student-t log-likelihood、L-BFGS-B 數值優化、
多步解析預測。以 arch 為 parity 參照（tests/test_models/test_garch_parity.py）。

繼承 VolatilityModel（base.py）：×100/÷100² 縮放與 α+β<1 平穩性檢查由 base 統一把關，
本模組只在 ×100 尺度做估計與預測——與 GarchArch 走同一份 base 契約、對上層可互換。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln

from quantcore.models.volatility.base import GarchDegenerateError, VolatilityModel

# 參數順序固定：θ = (μ, ω, α, β, ν)
_BACKCAST_TAU = 75  # arch 慣例：backcast 用前 min(75, n) 筆
_BACKCAST_DECAY = 0.94  # arch 慣例：權重 0.94^i


def _backcast(resid: np.ndarray) -> float:
    """樣本前變異數的種子（比照 arch）：前 tau 筆殘差平方的 0.94^i 加權平均。

    ω 對此初值敏感（parity 的關鍵）；優化開始前算一次、全程固定（arch 亦然）。
    """
    tau = min(_BACKCAST_TAU, len(resid))
    w = _BACKCAST_DECAY ** np.arange(tau)
    w = w / w.sum()
    return float(np.sum(resid[:tau] ** 2 * w))


def _variance_recursion(
    resid: np.ndarray, omega: float, alpha: float, beta: float, backcast: float
) -> np.ndarray:
    """給定參數，把殘差序列滾成條件變異數序列（零件 1）。

    σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}

    純機械：給定 (ω,α,β) 與 backcast，路徑唯一確定。σ²_t 依賴 σ²_{t-1}，本質順序、
    不可向量化——這是手刻版比 arch（C 迴圈）慢的根源。MLE 期間被呼叫數千次，保持純函數。

    第一格比照 arch：把樣本前的 ε²_{-1} 與 σ²_{-1} 都當 backcast，
    故 σ²_0 = ω + (α+β)·backcast（非直接令 σ²_0 = backcast）。
    """
    n = len(resid)
    sigma2 = np.empty(n)
    sigma2[0] = omega + (alpha + beta) * backcast
    for t in range(1, n):
        sigma2[t] = omega + alpha * resid[t - 1] ** 2 + beta * sigma2[t - 1]
    return sigma2


def _neg_loglik_t(resid: np.ndarray, sigma2: np.ndarray, nu: float) -> float:
    """標準化 Student-t 的負 log-likelihood 總和（零件 2；INV-4 的 t 分配慣例）。

    模型：ε_t = σ_t · z_t，z_t ~ 單位變異數的標準化 Student-t(ν)（故密度含 ν-2，ν>2）。
    回「負」總和：優化器最小化負 logL ≡ 最大化 logL（MLE）。全程 log 空間相加避免 underflow；
    給定 σ² 路徑後各天分數獨立，故此步向量化（與零件 1 的順序遞迴相反）。
    """
    c = gammaln((nu + 1) / 2) - gammaln(nu / 2) - 0.5 * np.log((nu - 2) * np.pi)
    ll = c - 0.5 * np.log(sigma2) - ((nu + 1) / 2) * np.log1p(resid**2 / ((nu - 2) * sigma2))
    return -float(np.sum(ll))


def _neg_loglik_objective(theta: np.ndarray, returns: np.ndarray, backcast: float) -> float:
    """優化器眼中的世界：θ=(μ,ω,α,β,ν) → 一個分數（串零件 1+2）。

    均值模型在此接上：resid = returns − μ，μ 與波動參數一起被優化器估。
    backcast 由外部一次算定並固定傳入（比照 arch，非每次迭代重算）。
    """
    mu, omega, alpha, beta, nu = theta
    resid = returns - mu
    sigma2 = _variance_recursion(resid, omega, alpha, beta, backcast)
    return _neg_loglik_t(resid, sigma2, nu)


def _fit_garch_t(scaled_returns: np.ndarray) -> tuple[dict[str, float], float]:
    """在 ×100 尺度上跑 L-BFGS-B 估 (μ,ω,α,β,ν)（零件 3）。失敗拋 GarchDegenerateError。

    回 (params, backcast)：backcast 供 _estimate 以「與優化時一致」的種子重建狀態。

    L-BFGS-B 只吃箱型邊界，無法表達 α+β<1（跨參數線性不等式）——故此處只箱型約束
    α,β∈[0,1)，平穩性由 base 的 enforce_stationarity 事後檢查把關（≥1 → 退回 EWMA），
    與 GarchArch 同模式。這是忠於規格「L-BFGS-B」選擇的刻意簡化。
    """
    r = scaled_returns
    var = float(np.var(r))
    mu0 = float(np.mean(r))
    # backcast 一次算定、優化期間固定（比照 arch）：用起始 μ 的殘差
    backcast = _backcast(r - mu0)

    # 起始值：中庸持續性 ~0.95、中度厚尾——GARCH 估計的標準起手式
    x0 = np.array([mu0, var * 0.05, 0.05, 0.90, 8.0])
    bounds = [
        (None, None),  # μ：不設限
        (1e-8, None),  # ω > 0：嚴格正，避免 σ²=0
        (0.0, 1.0),  # α ∈ [0, 1)
        (0.0, 1.0),  # β ∈ [0, 1)
        (2.05, 100.0),  # ν > 2：下界略高於 2，避開零件 2 的 (ν-2) 爆炸
    ]

    # 參數尺度橫跨兩數量級（ω~0.04、β~0.9、ν~8），預設 gtol=1e-5 會在大尺度參數
    # 收斂後過早停手、留 ν 卡在起始值。收緊容差 + 提高迭代上限，逼優化到底（parity）。
    res = minimize(
        _neg_loglik_objective,
        x0,
        args=(r, backcast),
        method="L-BFGS-B",
        bounds=bounds,
        options={"ftol": 1e-12, "gtol": 1e-8, "maxiter": 1000, "maxfun": 20000},
    )
    if not res.success:
        raise GarchDegenerateError(f"手刻 GARCH 優化未收斂：{res.message}")

    mu, omega, alpha, beta, nu = (float(v) for v in res.x)
    params = {"mu": mu, "omega": omega, "alpha": alpha, "beta": beta, "nu": nu}
    if not all(np.isfinite(v) for v in params.values()):
        raise GarchDegenerateError("手刻 GARCH 參數含非有限值")
    return params, backcast


def _forecast_variance_path(
    omega: float,
    alpha: float,
    beta: float,
    last_resid: float,
    last_sigma2: float,
    horizon: int,
) -> np.ndarray:
    """GARCH(1,1) 解析多步變異數預測（零件 4；規格 §1.6 Step 1、§5.2）。

    1 步用真實 ε_T；≥2 步以 E[ε²]=σ² 代未知未來衝擊，α,β 併為持續性 (α+β)。
    α+β<1 時收斂到無條件變異數 ω/(1-α-β)；≥1 則發散——由 base 平穩性檢查擋下。
    回長度 horizon 的每步變異數（×100 尺度，base 再 ÷100² 還原）。
    """
    persistence = alpha + beta
    out = np.empty(horizon)
    out[0] = omega + alpha * last_resid**2 + beta * last_sigma2
    for h in range(1, horizon):
        out[h] = omega + persistence * out[h - 1]
    return out


class GarchOwn(VolatilityModel):
    """手刻 GARCH(1,1)-t（規格 §5.2、Phase 6）。與 GarchArch 走同一份 base 契約。"""

    enforce_stationarity = True  # 啟用 base 的 α+β<1 檢查（同 GarchArch）
    _min_obs = 100  # GARCH-t MLE 需足夠樣本（同 GarchArch）

    def _estimate(self, scaled_returns: pd.Series) -> None:
        r = scaled_returns.to_numpy()
        self._params, backcast = _fit_garch_t(r)  # 零件 3（內含 1+2）

        # 用估好的最佳參數 + 優化時的固定 backcast 重跑一次遞迴，取得預測要用的
        # 「最後狀態」ε_T、σ²_T 與整條 σ。_fit_garch_t 只回參數（介面乾淨），
        # 狀態重建在類別這層做（便宜，一趟 O(n)；種子與優化時一致）。
        resid = r - self._params["mu"]
        sigma2 = _variance_recursion(
            resid,
            self._params["omega"],
            self._params["alpha"],
            self._params["beta"],
            backcast,
        )
        self._last_resid = float(resid[-1])
        self._last_sigma2 = float(sigma2[-1])
        self._sigma = np.sqrt(sigma2)
        self._scaled = scaled_returns
        self._index = scaled_returns.index

    def _forecast_scaled(self, horizon: int) -> np.ndarray:
        return _forecast_variance_path(
            self._params["omega"],
            self._params["alpha"],
            self._params["beta"],
            self._last_resid,
            self._last_sigma2,
            horizon,
        )

    @property
    def params(self) -> dict[str, float]:
        return dict(self._params)

    @property
    def standardized_residuals(self) -> pd.Series:
        # r_t/σ_t（尺度不變）：用原始 scaled return（非去均值）除條件波動，與
        # GarchArch/Ewma「同定義」，確保 Phase 5 DCC 的殘差輸入三模型間一致。
        return pd.Series(self._scaled.to_numpy() / self._sigma, index=self._index)
