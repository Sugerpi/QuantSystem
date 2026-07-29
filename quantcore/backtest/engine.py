"""回測主迴圈（規格 §6.1，model-agnostic）。

**每日順序刻意偏離 §6.1 伪代碼**（設計文件 §2.1）：§6.1 的「執行 → 損益」順序在
回看報酬慣例下，會讓新權重賺到它生效之前的報酬，與 §1.2 的損益歸屬矛盾。
以 §1.2 為準：損益 → 漂移 → 執行 → 決策。

本模組不寫檔、不知道 runs/ 的存在（那是 experiments/ 的職責）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quantcore.backtest.accounting import CASH, apply_costs, apply_returns, trade_deltas
from quantcore.backtest.clock import EventClock
from quantcore.backtest.ptview import make_view
from quantcore.backtest.strategy import DecisionEvent, Strategy
from quantcore.config import QuantConfig

_RATES_SERIES = "DTB3"
_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class _Pending:
    target: dict[str, float]
    execution_day: pd.Timestamp


def _returns_wide(prices: pd.DataFrame) -> pd.DataFrame:
    """date × ticker 的日報酬（自 adj_close，即含息總報酬）。"""
    wide = prices.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    return wide.pct_change()


def _adj_close_wide(prices: pd.DataFrame) -> pd.DataFrame:
    """date × ticker 的 adj_close 面板（blotter 的成交價來源）。"""
    return prices.pivot(index="date", columns="ticker", values="adj_close").sort_index()


def _daily_rates(rates: pd.DataFrame, trading_days: pd.DatetimeIndex) -> pd.Series:
    """DTB3（年化百分比）→ 日利率，對齊交易日並 ffill 假日（§1.5）。"""
    s = rates.set_index("date")[_RATES_SERIES].sort_index()
    return s.reindex(trading_days).ffill().bfill() / 100.0 / _DAYS_PER_YEAR


def run_strategy(
    snapshot: dict, clock: EventClock, strategy: Strategy, cfg: QuantConfig
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """單一策略的完整回測，回傳 (nav, weights, decisions, trades) 四張長格式表。"""
    rets = _returns_wide(snapshot["prices"])
    adj = _adj_close_wide(snapshot["prices"])
    rates = _daily_rates(snapshot["rates"], clock.trading_days)

    nav = float(cfg.backtest.initial_nav)
    weights: dict[str, float] = {CASH: 1.0}
    pending: _Pending | None = None

    nav_rows, weight_rows, decision_rows, trade_rows = [], [], [], []

    for t in clock.active_days:
        row = rets.loc[t].dropna() if t in rets.index else pd.Series(dtype="float64")
        day_returns = {k: float(v) for k, v in row.items()}
        rate = float(rates.loc[t])

        nav, drifted = apply_returns(nav, weights, day_returns, rate)

        turnover_today, cost_today = 0.0, 0.0
        if pending is not None and pending.execution_day == t:
            nav_before = nav
            nav, turnover_today = apply_costs(nav, drifted, pending.target, cfg.costs.per_side_bps)
            cost_today = nav_before - nav
            bps = cfg.costs.per_side_bps
            for ticker, dw in trade_deltas(drifted, pending.target).items():
                if dw == 0.0:
                    continue
                price = float(adj.at[t, ticker])
                notional = dw * nav_before
                trade_rows.append(
                    {
                        "execution_date": t,
                        "strategy_id": strategy.strategy_id,
                        "ticker": ticker,
                        "drifted_weight": drifted.get(ticker, 0.0),
                        "target_weight": pending.target.get(ticker, 0.0),
                        "delta_weight": dw,
                        "side": "buy" if dw > 0 else "sell",
                        "notional": notional,
                        "fill_price": price,
                        "shares": notional / price,
                        "cost": abs(dw) * nav_before * bps / 10_000.0,
                    }
                )
            weights = dict(pending.target)
            pending = None
        else:
            weights = drifted

        if clock.is_decision_day(t):
            event = (
                DecisionEvent.SELECTION
                if clock.is_selection_day(t)
                else DecisionEvent.EXPOSURE_CHECK
            )
            decision = strategy.decide(make_view(snapshot, t), event)
            if decision is not None:
                exec_day = clock.execution_day(t)
                if exec_day is not None:
                    decision_rows.append(
                        {
                            "decision_date": t,
                            "execution_date": exec_day if decision.execute else None,
                            "strategy_id": strategy.strategy_id,
                            "event": str(event),
                            "diagnostics": decision.diagnostics,
                            "target_weights": dict(decision.target_weights),
                        }
                    )
                    if decision.execute:
                        if pending is not None:
                            raise RuntimeError(
                                f"{t:%Y-%m-%d} 產生新決策，但前次決策尚未執行——"
                                "時程間隔設定有誤（見 EventClock 的間隔 ≥ 2 檢查）"
                            )
                        pending = _Pending(
                            target=dict(decision.target_weights), execution_day=exec_day
                        )

        nav_rows.append(
            {
                "date": t,
                "strategy_id": strategy.strategy_id,
                "nav": nav,
                "turnover": turnover_today,
                "cost": cost_today,
            }
        )
        for ticker, w in weights.items():
            weight_rows.append(
                {"date": t, "strategy_id": strategy.strategy_id, "ticker": ticker, "weight": w}
            )

    return (
        pd.DataFrame(nav_rows),
        pd.DataFrame(weight_rows),
        pd.DataFrame(decision_rows),
        pd.DataFrame(trade_rows),
    )
