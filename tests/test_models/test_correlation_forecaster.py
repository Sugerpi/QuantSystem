import numpy as np
import pandas as pd

from quantcore.models.correlation.forecaster import CorrelationForecaster


def _resid(cols, n=200, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(rng.standard_normal((n, len(cols))), index=idx, columns=cols)


def _make(corr_model, refit_interval):
    return CorrelationForecaster(
        corr_model,
        ewma_lambda=0.94,
        refit_interval=refit_interval,
        fixed_ab=(0.01, 0.96),
        selection_interval=21,
        qbar_shrink=0.10,
    )


def test_ewma_mode_returns_valid_correlation():
    fc = _make("ewma", refit_interval=63)
    R = fc.refit(_resid(["A", "B", "C"]))
    assert np.allclose(np.diag(R.to_numpy()), 1.0)
    assert np.min(np.linalg.eigvalsh(R.to_numpy())) >= -1e-10
    assert fc.last_params() is None  # ewma 無 (a,b)


def test_fixed_mode_never_reestimates():
    fc = _make("dcc", refit_interval=0)
    fc.refit(_resid(["A", "B"], seed=1))
    assert fc.last_params().a == 0.01 and fc.last_params().b == 0.96
    fc.refit(_resid(["A", "B"], seed=2))
    assert fc.last_params().a == 0.01 and fc.last_params().b == 0.96  # a,b 恆不變


def test_reestimate_cadence_every_third_selection():
    # refit_interval=63, selection_interval=21 → 每 3 次選擇重估 (a,b)
    fc = _make("dcc", refit_interval=63)
    fc.refit(_resid(["A", "B"], seed=1))  # 第 1 次：估
    ab1 = (fc.last_params().a, fc.last_params().b)
    fc.refit(_resid(["A", "B"], seed=2))  # 第 2 次：沿用
    ab2 = (fc.last_params().a, fc.last_params().b)
    assert ab2 == ab1
    fc.refit(_resid(["A", "B"], seed=3))  # 第 3 次：沿用
    fc.refit(_resid(["A", "B"], seed=4))  # 第 4 次：重估
    assert fc.last_params().q_bar.shape == (2, 2)


def test_filter_reuses_cached_params():
    fc = _make("dcc", refit_interval=63)
    fc.refit(_resid(["A", "B"], seed=1))
    ab = (fc.last_params().a, fc.last_params().b)
    R = fc.filter(_resid(["A", "B"], seed=9))
    assert (fc.last_params().a, fc.last_params().b) == ab  # filter 不重估
    assert np.allclose(np.diag(R.to_numpy()), 1.0)


def test_selection_rebuilds_qbar_for_rotated_universe():
    fc = _make("dcc", refit_interval=63)
    fc.refit(_resid(["A", "B"], seed=1))
    assert fc.last_params().q_bar.shape == (2, 2)
    fc.refit(_resid(["A", "B", "C"], seed=2))  # 換入新資產
    assert fc.last_params().q_bar.shape == (3, 3)  # Q̄ 隨新集合重建


def test_reestimate_cadence_and_fell_back_preserved(monkeypatch):
    import quantcore.models.correlation.forecaster as fc_mod
    from quantcore.models.correlation.dcc import DccParams

    calls = {"n": 0}
    real = fc_mod.estimate_dcc

    def spy(std_resid, fixed_ab, shrink):
        calls["n"] += 1
        p = real(std_resid, fixed_ab, shrink)
        # 回傳 fell_back=True，驗證 reuse 分支保留旗標（否則會被重置為 False）
        return DccParams(p.a, p.b, p.q_bar, fell_back=True)

    monkeypatch.setattr(fc_mod, "estimate_dcc", spy)
    fc = _make("dcc", refit_interval=63)

    fc.refit(_resid(["A", "B"], seed=1))  # 選擇 1：重估（call 1）
    assert calls["n"] == 1
    assert fc.last_params().fell_back is True

    fc.refit(_resid(["A", "B"], seed=2))  # 選擇 2：沿用，不重估
    assert calls["n"] == 1
    assert fc.last_params().fell_back is True  # 保留旗標（Fix 1）

    fc.refit(_resid(["A", "B"], seed=3))  # 選擇 3：沿用
    assert calls["n"] == 1

    fc.refit(_resid(["A", "B"], seed=4))  # 選擇 4：重估（call 2）
    assert calls["n"] == 2
