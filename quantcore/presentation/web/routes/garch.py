"""頁 3 GARCH：參數軌跡、fallback 頻率、QLIKE/MZ-R²、殘差 QQ/ACF。

參數軌跡資產以 ?tk=、殘差資產以 ?rtk= 選（預設第一個）。
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()


def _render(request: Request, ctx: dict) -> HTMLResponse:
    return render_page(
        request,
        active="/garch",
        full_template="garch.html",
        content_template="garch_content.html",
        context=ctx,
    )


# GJR 平穩條件係數：對稱條件分布下負向報酬指標 E[I(ε<0)]=0.5。此值必須與引擎端
# models/volatility/base.py 的 _GJR_NEG_INDICATOR_EXPECTATION 同步；presentation 依架構
# 規則不 import 引擎（§2.2），故此處為必要的本地複寫，改動時兩處須一起改。
_GJR_PERSISTENCE_GAMMA_COEF = 0.5


def _param_rows(sub: pd.DataFrame) -> list[dict]:
    rows = []
    for _, r in sub.iterrows():
        gp = r["garch_params"]
        if not gp:
            continue
        for t, p in gp.items():
            if p:
                rows.append(
                    {
                        "date": r["decision_date"],
                        "ticker": t,
                        **p,
                        "persistence": p["alpha"]
                        + p["beta"]
                        + _GJR_PERSISTENCE_GAMMA_COEF * p.get("gamma", 0.0),
                    }
                )
    return rows


def _param_chart_cols(columns) -> list[str]:
    """參數軌跡圖的系列欄位。GJR run（含 gamma 欄）多畫 γ，插在 α 後、β 前，
    呼應參數向量順序 [omega, alpha, gamma, beta, nu]；純 GARCH run 不含 γ。"""
    cols = ["omega", "alpha", "beta", "nu", "persistence"]
    if "gamma" in columns:
        cols.insert(2, "gamma")
    return cols


@router.get("/garch", response_class=HTMLResponse)
def garch(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    if ctrl.run_dir is None or not readers.is_backtest_run(ctrl.run_dir):
        ctx["error"] = "此頁需回測 run（含 decisions）。"
        return _render(request, ctx)
    dec = cache.read(ctrl.run_dir / "decisions.parquet", lambda p: readers.load_decisions(p.parent))
    dec_strats = sorted(dec["strategy_id"].unique())
    strat = ctrl.focus if ctrl.focus in dec_strats else dec_strats[0]
    sub = dec[dec["strategy_id"] == strat].sort_values("decision_date")
    ctx["strategy"] = strat

    prows = _param_rows(sub)
    ctx["param_tickers"] = []
    ctx["param_fig"] = None
    ctx["tk"] = None
    if prows:
        pt = pd.DataFrame(prows)
        tickers = sorted(pt["ticker"].unique())
        tk = request.query_params.get("tk") or tickers[0]
        if tk not in tickers:
            tk = tickers[0]
        tp = pt[pt["ticker"] == tk].sort_values("date")
        named = {c: (tp["date"], tp[c]) for c in _param_chart_cols(tp.columns)}
        ctx["param_tickers"] = tickers
        ctx["tk"] = tk
        ctx["param_fig"] = charts.to_fragment(charts.line_series(named), "g-param")

    fb = []
    for _, r in sub.iterrows():
        for t, v in (r["vol_fell_back"] or {}).items():
            fb.append({"ticker": t, "fb": bool(v)})
    ctx["fb_fig"] = None
    if fb:
        fbdf = pd.DataFrame(fb).groupby("ticker")["fb"].mean().reset_index()
        ctx["fb_fig"] = charts.to_fragment(
            charts.heatmap(
                [list(fbdf["fb"])],
                list(fbdf["ticker"]),
                ["fallback 比例"],
                zmin=0,
                zmax=1,
                colorscale="Reds",
            ),
            "g-fb",
        )

    ve = readers.load_vol_eval(ctrl.runs_root / "vol_eval")
    ctx["vol_eval_rows"] = ve.to_dict("records") if ve is not None else None
    ctx["vol_eval_cols"] = list(ve.columns) if ve is not None else None

    resid = readers.load_residuals(ctrl.run_dir)
    ctx["resid_tickers"] = []
    ctx["qq_fig"] = None
    ctx["acf_fig"] = None
    ctx["rtk"] = None
    if resid is not None and not resid.empty:
        rs = resid[resid["strategy_id"] == strat] if "strategy_id" in resid.columns else resid
        resid_tickers = sorted(rs["ticker"].unique())
        ctx["resid_tickers"] = resid_tickers
        if resid_tickers:
            rtk = request.query_params.get("rtk") or resid_tickers[0]
            if rtk not in resid_tickers:
                rtk = resid_tickers[0]
            ctx["rtk"] = rtk
            s = rs[rs["ticker"] == rtk]["std_resid"].dropna().to_numpy()
            if len(s) > 1:
                ctx["qq_fig"] = charts.to_fragment(charts.resid_qq(s), "g-qq")
                ctx["acf_fig"] = charts.to_fragment(charts.resid_acf(s, lags=20), "g-acf")
    return _render(request, ctx)
