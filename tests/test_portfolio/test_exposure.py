"""target_exposure：clip、更新帶、首次無帶、誠實失敗（規格 §1.6/§1.7）。"""

from __future__ import annotations

import pytest

from quantcore.portfolio.exposure import ExposureResult, target_exposure


def test_first_application_no_band():
    # e_current=None → 直接套用 clip 後值，band_blocked=False
    r = target_exposure(sigma_p=0.20, sigma_star=0.10, e_min=0.10, band=0.10, e_current=None)
    assert isinstance(r, ExposureResult)
    assert r.exposure_raw == pytest.approx(0.5)
    assert r.exposure_applied == pytest.approx(0.5)
    assert r.band_blocked is False


def test_clip_upper_bound():
    # σ̂_p < σ* → raw>1 → clip 到 1.0
    r = target_exposure(sigma_p=0.05, sigma_star=0.10, e_min=0.10, band=0.10, e_current=None)
    assert r.exposure_raw == pytest.approx(2.0)
    assert r.exposure_applied == pytest.approx(1.0)


def test_clip_lower_bound():
    # σ̂_p 很大 → raw<e_min → clip 到 e_min
    r = target_exposure(sigma_p=2.0, sigma_star=0.10, e_min=0.10, band=0.10, e_current=None)
    assert r.exposure_raw == pytest.approx(0.05)
    assert r.exposure_applied == pytest.approx(0.10)


def test_band_blocks_small_change():
    # |clipped − e_current| ≤ band → 沿用舊值、band_blocked=True
    # σ̂_p=0.20 → clipped=0.5；e_current=0.55，差 0.05 ≤ 0.10 → 擋
    r = target_exposure(sigma_p=0.20, sigma_star=0.10, e_min=0.10, band=0.10, e_current=0.55)
    assert r.exposure_applied == pytest.approx(0.55)
    assert r.band_blocked is True


def test_band_allows_large_change():
    # 差 > band → 套用新值
    # clipped=0.5；e_current=0.30，差 0.20 > 0.10 → 套新
    r = target_exposure(sigma_p=0.20, sigma_star=0.10, e_min=0.10, band=0.10, e_current=0.30)
    assert r.exposure_applied == pytest.approx(0.5)
    assert r.band_blocked is False


def test_nonpositive_sigma_p_raises():
    with pytest.raises(ValueError):
        target_exposure(sigma_p=0.0, sigma_star=0.10, e_min=0.10, band=0.10, e_current=None)
    with pytest.raises(ValueError):
        target_exposure(
            sigma_p=float("nan"), sigma_star=0.10, e_min=0.10, band=0.10, e_current=None
        )
