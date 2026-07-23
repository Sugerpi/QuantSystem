"""Phase 0 AC：config 能載入並驗證 default.yaml。"""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from quantcore.config import QuantConfig, load_config

DEFAULT_YAML = Path(__file__).resolve().parents[1] / "quantcore" / "config" / "default.yaml"


def test_default_yaml_loads_and_validates():
    cfg = load_config(DEFAULT_YAML)
    assert isinstance(cfg, QuantConfig)
    # 抽查數值與規格 §7.2 一致
    assert cfg.seed == 42
    assert cfg.signal.top_k == 5
    assert cfg.signal.momentum_lookback == 252
    assert cfg.signal.momentum_skip == 21
    assert cfg.risk.vol_target_annual == 0.10
    assert cfg.risk.vol_model == "garch_arch"
    assert cfg.backtest.start == date(2005, 1, 3)
    assert len(cfg.universe.menu) == 20  # DBC 於 Phase 1 移除（§4.5 三源皆不一致）


def _valid_dict() -> dict:
    """從 default.yaml 取一份可用的 dict 作為修改基底。"""
    import yaml

    with DEFAULT_YAML.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_unknown_key_rejected():
    raw = _valid_dict()
    raw["unexpected_field"] = 123
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)


def test_top_k_cannot_exceed_menu_size():
    raw = _valid_dict()
    raw["signal"]["top_k"] = len(raw["universe"]["menu"]) + 1
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)


def test_momentum_skip_must_be_less_than_lookback():
    raw = _valid_dict()
    raw["signal"]["momentum_skip"] = raw["signal"]["momentum_lookback"]
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)


def test_duplicate_ticker_rejected():
    raw = _valid_dict()
    raw["universe"]["menu"].append(raw["universe"]["menu"][0])
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)


def test_invalid_vol_model_rejected():
    raw = _valid_dict()
    raw["risk"]["vol_model"] = "not_a_real_model"
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)


def test_data_quality_loaded():
    cfg = load_config(DEFAULT_YAML)
    assert cfg.data_quality.discrepancy_bps == 50
    assert cfg.data_quality.window_days == 30
    assert cfg.data_quality.window_max_hits == 3
    assert cfg.data_quality.max_consecutive_nan == 5


def test_data_quality_rejects_bad_extreme_return():
    raw = _valid_dict()
    raw["data_quality"]["extreme_return"] = 1.5  # 必須 < 1
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)


def test_backtest_initial_nav_loaded_and_positive():
    cfg = load_config(DEFAULT_YAML)
    assert cfg.backtest.initial_nav == 1.0


def test_backtest_initial_nav_rejects_non_positive(tmp_path):
    import yaml

    raw = _valid_dict()
    raw["backtest"]["initial_nav"] = 0.0
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(p)


def test_vol_model_and_window_load():
    cfg = load_config(DEFAULT_YAML)
    assert cfg.risk.vol_model == "garch_arch"
    assert cfg.risk.vol_window == 63


def test_vol_window_must_be_positive():
    raw = _valid_dict()
    raw["risk"]["vol_window"] = 0
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)


def test_vol_window_exceeding_available_history_rejected():
    raw = _valid_dict()
    raw["risk"]["vol_model"] = "rolling_std"  # 此約束僅 rolling_std 適用
    floor = max(raw["universe"]["min_history_days"], raw["signal"]["momentum_lookback"] + 1)
    raw["risk"]["vol_window"] = floor  # vol_window+1 > floor → 無法滿窗
    with pytest.raises(ValidationError):
        QuantConfig.model_validate(raw)


def test_vol_window_at_available_floor_accepted():
    raw = _valid_dict()
    raw["risk"]["vol_model"] = "rolling_std"  # 此約束僅 rolling_std 適用
    floor = max(raw["universe"]["min_history_days"], raw["signal"]["momentum_lookback"] + 1)
    raw["risk"]["vol_window"] = floor - 1  # 剛好滿窗 → 應通過
    QuantConfig.model_validate(raw)  # 不應拋錯


def test_vol_window_constraint_only_applies_to_rolling_std():
    from tests.fixtures.synthetic import make_cfg

    # garch_arch + 大 vol_window（超過 momentum floor）應通過——vol_window 對 garch_arch 無意義
    make_cfg(["SPY", "TLT"], risk={"vol_model": "garch_arch", "vol_window": 10_000})


def test_risk_ewma_lambda_and_horizon_loaded():
    cfg = load_config(DEFAULT_YAML)
    assert cfg.risk.ewma_lambda == 0.94
    assert cfg.risk.forecast_horizon == 21


def test_risk_ewma_lambda_must_be_open_unit_interval():
    from tests.fixtures.synthetic import make_cfg

    with pytest.raises(ValidationError):
        make_cfg(["SPY", "TLT"], risk={"ewma_lambda": 1.0})
    with pytest.raises(ValidationError):
        make_cfg(["SPY", "TLT"], risk={"ewma_lambda": 0.0})


def test_risk_forecast_horizon_must_be_positive():
    from tests.fixtures.synthetic import make_cfg

    with pytest.raises(ValidationError):
        make_cfg(["SPY", "TLT"], risk={"forecast_horizon": 0})


def test_risk_garch_window_loaded():
    cfg = load_config(DEFAULT_YAML)
    assert cfg.risk.garch_window == 1000


def test_risk_garch_window_must_be_at_least_min_obs():
    from tests.fixtures.synthetic import make_cfg

    with pytest.raises(ValidationError):
        make_cfg(["SPY", "TLT"], risk={"garch_window": 50})  # < 100


def test_risk_corr_window_loaded():
    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.risk.corr_window == 252


def test_default_vol_model_is_garch_arch():
    cfg = load_config("quantcore/config/default.yaml")
    assert cfg.risk.vol_model == "garch_arch"
