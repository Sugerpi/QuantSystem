"""波動目標 + 更新帶（規格 §1.6 Step 3、§1.7）。全系統唯一曝險出口。純函數。

依賴方向：portfolio 上游於 backtest，只認基本型別。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ExposureResult:
    exposure_raw: float  # σ*/σ̂_p（clip 與帶寬判定前）
    exposure_applied: float  # 實際 E(t)
    band_blocked: bool  # 本次調整是否被更新帶擋下


def target_exposure(
    sigma_p: float,
    sigma_star: float,
    e_min: float,
    band: float,
    e_current: float | None,
) -> ExposureResult:
    """E(t) = clip(σ*/σ̂_p, e_min, 1)，含更新帶。

    e_current is None（首次 / 選擇日）→ 直接套用，不受帶約束。
    否則（曝險檢查日）：|clipped − e_current| > band 才調整，否則沿用 e_current。
    """
    if not math.isfinite(sigma_p) or sigma_p <= 0.0:
        raise ValueError(f"σ̂_p={sigma_p} 非正或非有限，曝險無定義")
    raw = sigma_star / sigma_p
    clipped = min(max(raw, e_min), 1.0)
    if e_current is None or abs(clipped - e_current) > band:
        return ExposureResult(raw, clipped, band_blocked=False)
    return ExposureResult(raw, e_current, band_blocked=True)
