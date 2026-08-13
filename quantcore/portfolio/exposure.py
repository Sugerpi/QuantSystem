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
    band_mode: str = "absolute",
) -> ExposureResult:
    """E(t) = clip(σ*/σ̂_p, e_min, 1)，含更新帶。

    band_mode:
      - "absolute"：|clipped − e_current| > band 才調整（現行）。
      - "log"：     |ln(clipped) − ln(e_current)| > band 才調整（相對/對數空間，
                    容忍度與 σ̂_p 水準無關）。需 clipped>0 且 e_current>0。
    e_current is None（首次 / 選擇日）→ 直接套用，不受帶約束。
    """
    if not math.isfinite(sigma_p) or sigma_p <= 0.0:
        raise ValueError(f"σ̂_p={sigma_p} 非正或非有限，曝險無定義")
    if band_mode not in ("absolute", "log"):
        raise ValueError(f"未知 band_mode={band_mode!r}（可用：absolute | log）")
    raw = sigma_star / sigma_p
    clipped = min(max(raw, e_min), 1.0)
    if e_current is None:
        return ExposureResult(raw, clipped, band_blocked=False)
    if band_mode == "absolute":
        moved = abs(clipped - e_current) > band
    else:  # log
        if clipped <= 0.0 or e_current <= 0.0:
            raise ValueError(
                f"band_mode='log' 需 clipped>0 且 e_current>0，"
                f"收到 clipped={clipped}, e_current={e_current}（e_min 應 >0）"
            )
        moved = abs(math.log(clipped) - math.log(e_current)) > band
    if moved:
        return ExposureResult(raw, clipped, band_blocked=False)
    return ExposureResult(raw, e_current, band_blocked=True)
