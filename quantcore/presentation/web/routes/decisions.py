"""頁 2 決策解剖（AC① UI）：六層垂直瀑布，讀 readers.decision_layers。

決策日以 query param ?didx=N 選（預設最後一個）。
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page


def _render(request: Request, ctx: dict) -> HTMLResponse:
    return render_page(
        request,
        active="/decisions",
        full_template="decisions.html",
        content_template="decisions_content.html",
        context=ctx,
    )


router = APIRouter()


@router.get("/decisions", response_class=HTMLResponse)
def decisions(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    if ctrl.run_dir is None or not readers.is_backtest_run(ctrl.run_dir):
        ctx["error"] = "此頁需回測 run（含 decisions）。"
        return _render(request, ctx)
    dec = cache.read(ctrl.run_dir / "decisions.parquet", lambda p: readers.load_decisions(p.parent))
    dec_strats = sorted(dec["strategy_id"].unique())
    strat = ctrl.focus if ctrl.focus in dec_strats else dec_strats[0]
    sub = dec[dec["strategy_id"] == strat].sort_values("decision_date")
    if sub.empty:
        ctx["error"] = f"{strat} 無決策紀錄。"
        return _render(request, ctx)
    dates = list(sub["decision_date"])
    ddate_q = request.query_params.get("ddate")
    if ddate_q:
        want = pd.Timestamp(ddate_q)
        le = [i for i, d in enumerate(dates) if pd.Timestamp(d) <= want]
        didx = le[-1] if le else 0
    else:
        try:
            didx = int(request.query_params.get("didx", len(dates) - 1))
        except ValueError:
            didx = len(dates) - 1
    didx = max(0, min(didx, len(dates) - 1))
    ddate = dates[didx]
    layer = readers.decision_layers(ctrl.run_dir, strat, ddate)
    prev = sub[sub["decision_date"] < ddate]
    prev_sigma = (
        readers.decision_layers(ctrl.run_dir, strat, prev["decision_date"].iloc[-1]).sigma_hat
        if not prev.empty
        else None
    )
    mom_fig = None
    if layer.momentum_scores:
        mom_fig = charts.to_fragment(
            charts.momentum_bar(layer.momentum_scores, layer.selected or []), "dec-mom"
        )
    sigma_rows = None
    if layer.sigma_hat:
        sigma_rows = [
            {"ticker": t, "sigma": v, "sigma_prev": (prev_sigma or {}).get(t)}
            for t, v in layer.sigma_hat.items()
        ]
    ctx.update(
        strategy=strat,
        dates=[pd.Timestamp(d).date().isoformat() for d in dates],
        didx=didx,
        ddate=pd.Timestamp(ddate).date().isoformat(),
        layer=layer,
        mom_fig=mom_fig,
        sigma_rows=sigma_rows,
        exposure=(
            {
                "sigma_p": layer.sigma_p,
                "exposure_raw": layer.exposure_raw,
                "exposure_applied": layer.exposure_applied,
                "band_blocked": bool(layer.band_blocked),
            }
            if layer.sigma_p is not None
            else None
        ),
    )
    return _render(request, ctx)
