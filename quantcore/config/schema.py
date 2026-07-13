"""型別化 config（規格 §2.1、§7.2）。

全系統唯一的參數來源。任何魔術數字出現在 config 以外即視為 bug（附錄 A）。
所有模型使用 ``extra="forbid"``：config 出現未知鍵（多為打字錯誤）直接報錯。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

VolModel = Literal["garch_arch", "garch_own", "ewma"]
CorrModel = Literal["dcc", "ewma"]


class _Strict(BaseModel):
    """禁止未知欄位的基底。"""

    model_config = ConfigDict(extra="forbid")


class UniverseConfig(_Strict):
    """資產選單（規格 §1.1）。"""

    menu: list[str] = Field(min_length=1)
    min_history_days: int = Field(gt=0)

    @model_validator(mode="after")
    def _menu_unique(self) -> UniverseConfig:
        if len(set(self.menu)) != len(self.menu):
            raise ValueError("universe.menu 含重複 ticker")
        return self


class SignalConfig(_Strict):
    """橫斷面動量參數（規格 §1.3）。"""

    momentum_lookback: int = Field(gt=0)
    momentum_skip: int = Field(ge=0)
    top_k: int = Field(gt=0)

    @model_validator(mode="after")
    def _skip_lt_lookback(self) -> SignalConfig:
        if self.momentum_skip >= self.momentum_lookback:
            raise ValueError("signal.momentum_skip 必須小於 momentum_lookback")
        return self


class RiskConfig(_Strict):
    """波動率/相關模型與曝險控制（規格 §1.6、§5）。"""

    vol_model: VolModel
    corr_model: CorrModel
    vol_target_annual: float = Field(gt=0)
    exposure_band: float = Field(ge=0, le=1)
    exposure_min: float = Field(ge=0, le=1)


class ScheduleConfig(_Strict):
    """再平衡時程（規格 §1.7）。"""

    selection_interval: int = Field(gt=0)
    exposure_check_interval: int = Field(gt=0)


class CostsConfig(_Strict):
    """交易成本模型（規格 §1.8）。"""

    per_side_bps: float = Field(ge=0)


class DataQualityConfig(_Strict):
    """資料品質門檻（設計文件 §7a、規格 §4.3/§4.5）。"""

    discrepancy_bps: float = Field(gt=0)  # §4.5 跨源日報酬差異門檻
    window_days: int = Field(gt=0)  # §4.5 滾動窗（交易日）
    window_max_hits: int = Field(gt=0)  # §4.5 窗內差異筆數上限（達到即失敗）
    extreme_return: float = Field(gt=0, lt=1)  # §4.3-2 單日 |r| 極端值門檻
    max_consecutive_nan: int = Field(gt=0)  # §4.3-3 連續缺值上限（超過即拒絕）
    total_return_tol_bps: float = Field(gt=0)  # §4.3-1 總報酬抽查容差


class BacktestConfig(_Strict):
    """回測範圍（規格 §6）。"""

    start: date


class QuantConfig(_Strict):
    """全系統設定根物件（規格 §7.2）。"""

    snapshot: str
    seed: int
    universe: UniverseConfig
    signal: SignalConfig
    risk: RiskConfig
    schedule: ScheduleConfig
    costs: CostsConfig
    data_quality: DataQualityConfig
    backtest: BacktestConfig

    @model_validator(mode="after")
    def _top_k_within_menu(self) -> QuantConfig:
        if self.signal.top_k > len(self.universe.menu):
            raise ValueError(
                f"signal.top_k ({self.signal.top_k}) 不可大於選單檔數 "
                f"({len(self.universe.menu)})"
            )
        return self


def load_config(path: str | Path) -> QuantConfig:
    """從 YAML 載入並驗證 config。

    驗證失敗會 raise ``pydantic.ValidationError``。
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if raw is None:
        raise ValueError(f"config 檔為空：{path}")
    return QuantConfig.model_validate(raw)
