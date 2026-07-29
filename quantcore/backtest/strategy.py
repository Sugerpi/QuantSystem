"""Strategy 介面（規格 §6.2）。

**與 §6.2 的偏離**：§6.2 的簽章為 `decide(self, view)`，但 §1.7 定義了兩種決策日
（選擇日重跑完整權重、曝險檢查日只重算 E(t)），策略必須分辨自己被哪一種叫到，
否則 ew_menu 會在每個曝險檢查日也做月再平衡、full 無法實作 §1.6 的分頻。
`decide(view)` 沒有管道傳此資訊，故加入 `event` 參數。cfg 於 __init__ 綁定。

Diagnostics 不是可選的 debug 資訊，是 Decision Explorer（§11.2）的正式資料合約——
引擎在決策當下就記錄，事後補記錄等於重跑回測。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd

from quantcore.backtest.ptview import PointInTimeView
from quantcore.config import QuantConfig


class DecisionEvent(StrEnum):
    """決策日的兩種類型（§1.7）。一天同時符合兩者時，引擎發 SELECTION。"""

    SELECTION = "selection"
    EXPOSURE_CHECK = "exposure_check"


@dataclass(frozen=True)
class Diagnostics:
    """每一層的完整中間結果（§6.2）。Phase 3-4 的欄位在 Phase 2 為 None。"""

    eligible: list[str]
    selected: list[str]
    momentum_scores: dict[str, float] | None = None
    absmom: dict[str, bool] | None = None
    sigma_hat: dict[str, float] | None = None
    w_risky: dict[str, float] | None = None
    sigma_p: float | None = None
    exposure_raw: float | None = None
    exposure_applied: float | None = None
    band_blocked: bool | None = None
    vol_fell_back: dict[str, bool] | None = None  # 每檔 GARCH 是否退回 EWMA（決策當下記，§6.2）
    garch_params: dict[str, dict[str, float] | None] | None = (
        None  # 每檔 {omega,alpha,beta,nu}；EWMA/None
    )
    # corr_matrix 為 pd.DataFrame：compare=False 讓 frozen dataclass 的 __eq__/__hash__ 不碰它
    # （DataFrame 真值歧義 + unhashable，比照 Phase 5a DccParams 的 eq=False 處置）。
    corr_matrix: pd.DataFrame | None = field(default=None, compare=False, repr=False)
    corr_fell_back: bool | None = None  # DCC (a,b) 是否退回 fixed_ab（鏡射 vol_fell_back）


@dataclass(frozen=True)
class Decision:
    """一次決策的產出。target_weights 含 'CASH' 鍵。"""

    target_weights: dict[str, float]
    diagnostics: Diagnostics
    execute: bool = True  # False = 只落診斷、不 rebalance（band-blocked 曝險檢查，§1.7）


class Strategy(ABC):
    """策略基底。strategy_id 為穩定識別碼，取代名稱字串過濾（§6.2）。"""

    strategy_id: str

    def __init__(self, cfg: QuantConfig) -> None:
        self._cfg = cfg

    @property
    @abstractmethod
    def warmup_days(self) -> int:
        """本策略需要幾個交易日的歷史才能決策。引擎取全策略最大值（設計文件 §2.3）。"""

    @abstractmethod
    def decide(self, view: PointInTimeView, event: DecisionEvent) -> Decision | None:
        """回傳下一交易日要執行的目標權重；本次不動作則回 None。"""
