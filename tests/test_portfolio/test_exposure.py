"""target_exposure：clip、更新帶、首次無帶、誠實失敗（規格 §1.6/§1.7）。"""

from __future__ import annotations

import math

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
    assert r.exposure_raw == pytest.approx(0.5)  # 擋下時 raw 仍為真實原始目標 σ*/σ̂_p


def test_band_boundary_equal_is_blocked():
    # |clipped − e_current| == band exactly → 擋（嚴格 >，等於帶寬不動作）
    # σ̂_p=0.20 → clipped=0.5；e_current=0.40，差恰 0.10 == band → blocked
    r = target_exposure(sigma_p=0.20, sigma_star=0.10, e_min=0.10, band=0.10, e_current=0.40)
    assert r.exposure_applied == pytest.approx(0.40)
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


def test_log_band_blocks_small_relative_change():
    # σ̂_p=0.20 → clipped=0.5；e_current=0.55；|ln0.5−ln0.55|=0.0953 < band 0.15 → 擋
    r = target_exposure(0.20, 0.10, 0.10, 0.15, 0.55, band_mode="log")
    assert r.band_blocked is True
    assert r.exposure_applied == pytest.approx(0.55)
    assert r.exposure_raw == pytest.approx(0.5)


def test_log_band_allows_large_relative_change():
    # clipped=0.5；e_current=0.70；|ln0.5−ln0.70|=0.3365 > 0.15 → 套新值
    r = target_exposure(0.20, 0.10, 0.10, 0.15, 0.70, band_mode="log")
    assert r.band_blocked is False
    assert r.exposure_applied == pytest.approx(0.5)


def test_log_band_boundary_equal_is_blocked():
    # |ln(clipped)−ln(e_current)| 恰 == band → 擋（嚴格 >）
    # e_current=1.0、clipped=0.5 → |ln0.5|=0.6931；band=ln(2)=0.6931
    r = target_exposure(0.20, 0.10, 0.10, math.log(2), 1.0, band_mode="log")
    assert r.band_blocked is True
    assert r.exposure_applied == pytest.approx(1.0)


def test_log_band_uniform_across_sigma_levels():
    # 同一相對 σ̂_p 變動(+20%)在高/低 σ̂_p 兩處產生相同 |Δln E|=0.1823，
    # 故 band=0.15 兩處皆穿、band=0.20 兩處皆擋——容忍度與水準無關。
    # 低波動側：e_current=0.90（σ̂_p≈0.111）→ σ̂_p=0.1333 → clipped=0.75
    # 高波動側：e_current=0.30（σ̂_p≈0.333）→ σ̂_p=0.40   → clipped=0.25
    low_cross = target_exposure(0.10 / 0.75, 0.10, 0.10, 0.15, 0.90, band_mode="log")
    high_cross = target_exposure(0.10 / 0.25, 0.10, 0.10, 0.15, 0.30, band_mode="log")
    assert low_cross.band_blocked is False and high_cross.band_blocked is False
    low_block = target_exposure(0.10 / 0.75, 0.10, 0.10, 0.20, 0.90, band_mode="log")
    high_block = target_exposure(0.10 / 0.25, 0.10, 0.10, 0.20, 0.30, band_mode="log")
    assert low_block.band_blocked is True and high_block.band_blocked is True


def test_log_band_first_application_no_band():
    # e_current=None → 直接套用，不受帶約束
    r = target_exposure(0.20, 0.10, 0.10, 0.15, None, band_mode="log")
    assert r.band_blocked is False
    assert r.exposure_applied == pytest.approx(0.5)


def test_unknown_band_mode_raises():
    with pytest.raises(ValueError):
        target_exposure(0.20, 0.10, 0.10, 0.10, 0.5, band_mode="relative")


def test_absolute_mode_is_default_and_unchanged():
    # 不給 band_mode → absolute；|0.5−0.55|=0.05 ≤ 0.10 → 擋
    r = target_exposure(0.20, 0.10, 0.10, 0.10, 0.55)
    assert r.band_blocked is True
    assert r.exposure_applied == pytest.approx(0.55)
