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

VolModel = Literal["garch_arch", "garch_own", "ewma", "rolling_std"]
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
    vol_window: int = Field(
        gt=0
    )  # rolling_std 的滾動窗（交易日）；Phase 4 GARCH 取代後仍保留供 EWMA/基線
    ewma_lambda: float = Field(gt=0, lt=1)  # §5.3 RiskMetrics EWMA 衰減；也是 GARCH fallback
    forecast_horizon: int = Field(gt=0)  # §1.6 Step 1 的 H，對齊 selection_interval
    garch_window: int = Field(ge=100)  # GARCH 估計滾動窗上限（交易日）；≥ GarchArch._min_obs
    corr_window: int = Field(ge=2)  # 滾動樣本相關窗（交易日）；實務 ≫ top_k 保 R 滿秩


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
    """回測範圍與初始狀態（規格 §6）。"""

    start: date
    initial_nav: float = Field(gt=0)
    # NAV 為尺度不變：Sharpe/MaxDD/Calmar/換手率皆不受此值影響，僅 nav.parquet 的
    # 數字大小改變。仍入 config 以維持「參數只在 config」這條明線。


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
                f"signal.top_k ({self.signal.top_k}) 不可大於選單檔數 ({len(self.universe.menu)})"
            )
        return self

    @model_validator(mode="after")
    def _vol_window_fits_available_history(self) -> QuantConfig:
        # 入選資產至少有 max(min_history_days, momentum_lookback+1) 根 bar
        # （須同時通過 eligibility 與動量計分）。滿窗需 vol_window+1 根，
        # 此約束確保滾動波動窗永遠為滿窗、不致靜默退化為較少樣本。
        floor = max(self.universe.min_history_days, self.signal.momentum_lookback + 1)
        if self.risk.vol_window + 1 > floor:
            raise ValueError(
                f"risk.vol_window ({self.risk.vol_window}) 過大：入選資產最少 {floor} 根 bar，"
                f"滾動波動窗需 vol_window+1 根，將無法滿窗"
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
