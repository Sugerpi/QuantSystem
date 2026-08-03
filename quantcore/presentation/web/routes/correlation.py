"""頁 4 相關結構：相關矩陣熱圖（時間 ?cidx）、資產對序列（?ti、?tj）、第二 run 疊圖（?r2）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()


def _render(request: Request, ctx: dict) -> HTMLResponse:
    return render_page(
        request,
        active="/correlation",
        full_template="correlation.html",
        content_template="correlation_content.html",
        context=ctx,
    )


@router.get("/correlation", response_class=HTMLResponse)
def correlation(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    corr = cache.read(ctrl.run_dir, readers.load_correlation) if ctrl.run_dir else None
    if corr is None or corr.empty:
        ctx["error"] = "本次未儲存（無 model_details/correlation；僅 full/full_erc 有相關矩陣）。"
        return _render(request, ctx)
    # 相關矩陣只有 full/full_erc 有；用焦點策略，若不在 corr（如 bh_spy）取第一個有的。
    corr_strats = sorted(corr["strategy_id"].unique())
    strat = ctrl.focus if ctrl.focus in corr_strats else corr_strats[0]
    csub = corr[corr["strategy_id"] == strat]
    dates = sorted(csub["decision_date"].unique())
    if len(dates) == 0:
        ctx["error"] = f"{strat} 無相關矩陣紀錄。"
        return _render(request, ctx)
    try:
        cidx = int(request.query_params.get("cidx", len(dates) - 1))
    except ValueError:
        cidx = len(dates) - 1
    cidx = max(0, min(cidx, len(dates) - 1))
    mat = readers.correlation_matrix_at(csub, strat, dates[cidx])
    tickers = sorted(mat.index)
    ti = request.query_params.get("ti") or (tickers[0] if tickers else None)
    tj = request.query_params.get("tj") or (tickers[1] if len(tickers) > 1 else tickers[0])
    if ti not in tickers:
        ti = tickers[0]
    if tj not in tickers:
        tj = tickers[min(1, len(tickers) - 1)]
    pair = csub[(csub["ticker_i"] == ti) & (csub["ticker_j"] == tj)].sort_values("decision_date")
    named = {f"{ti}-{tj}": (pair["decision_date"], pair["corr"])}
    others = [r["name"] for r in readers.list_runs(ctrl.runs_root) if r["name"] != ctrl.run]
    r2 = request.query_params.get("r2")
    if r2 and r2 in others:
        c2 = readers.load_correlation(ctrl.runs_root / r2)
        if c2 is not None and not c2.empty:
            s2 = (ctrl.strategies or sorted(c2["strategy_id"].unique()))[0]
            p2 = c2[
                (c2["strategy_id"] == s2) & (c2["ticker_i"] == ti) & (c2["ticker_j"] == tj)
            ].sort_values("decision_date")
            named[r2] = (p2["decision_date"], p2["corr"])
    ctx.update(
        strategy=strat,
        dates=[str(d)[:10] for d in dates],
        cidx=cidx,
        heat_fig=charts.to_fragment(
            charts.heatmap(
                mat.values, list(mat.columns), list(mat.index), zmin=-1, zmax=1, colorscale="RdBu"
            ),
            "c-heat",
        ),
        tickers=tickers,
        ti=ti,
        tj=tj,
        pair_fig=charts.to_fragment(charts.line_series(named), "c-pair"),
        others=others,
        r2=r2 or "",
    )
    return _render(request, ctx)
