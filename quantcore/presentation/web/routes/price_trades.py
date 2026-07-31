"""頁 9 價格與交易（旗艦）：走勢+進出場標記、標的持有列表、blotter、持倉堆疊。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()

_PAGE = 50


def _focus_trades(request: Request):
    """(strat, tr) —— 焦點策略的成交明細（若有 ?ftk 再篩標的）。無 trades 回 (None, None)。"""
    ctrl = controls_for(request)
    trades = cache.read(ctrl.run_dir, readers.load_trades) if ctrl.run_dir else None
    if trades is None:
        return None, None
    tr_strats = sorted(trades["strategy_id"].unique())
    strat = ctrl.focus if ctrl.focus in tr_strats else tr_strats[0]
    tr = trades[trades["strategy_id"] == strat].sort_values("execution_date")
    ftk = request.query_params.get("ftk") or ""
    if ftk:
        tr = tr[tr["ticker"] == ftk]
    return strat, tr


@router.get("/price-trades/export.csv")
def export_csv(request: Request) -> Response:
    """匯出焦點策略（+可選標的篩選）的成交明細為 CSV。utf-8-sig（含 BOM）讓 Excel 正確辨識中文。"""
    strat, tr = _focus_trades(request)
    if tr is None:
        return Response(
            "本次未儲存（無 trades.parquet）。", media_type="text/plain", status_code=404
        )
    ftk = request.query_params.get("ftk") or ""
    fname = f"blotter_{strat}{('_' + ftk) if ftk else ''}.csv"
    return Response(
        content=tr.to_csv(index=False).encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _render(request: Request, ctx: dict) -> HTMLResponse:
    return render_page(
        request,
        active="/price-trades",
        full_template="price_trades.html",
        content_template="price_trades_content.html",
        context=ctx,
    )


@router.get("/price-trades", response_class=HTMLResponse)
def price_trades(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    trades = cache.read(ctrl.run_dir, readers.load_trades) if ctrl.run_dir else None
    if trades is None:
        ctx["error"] = "本次未儲存（無 trades.parquet）。"
        return _render(request, ctx)
    tr_strats = sorted(trades["strategy_id"].unique())
    strat = ctrl.focus if ctrl.focus in tr_strats else tr_strats[0]
    tr = trades[trades["strategy_id"] == strat].sort_values("execution_date")
    tickers = sorted(tr["ticker"].unique())
    tk = request.query_params.get("tk") or (tickers[0] if tickers else None)
    if tk not in tickers:
        tk = tickers[0] if tickers else None

    snap_dir = readers.snapshot_dir_for_run(ctrl.run_dir)
    panel = readers.load_adj_close_panel(snap_dir) if snap_dir.exists() else None
    price = panel[tk] if (panel is not None and tk in panel.columns) else None
    price_fig = charts.to_fragment(
        charts.price_with_trades(price, tr[tr["ticker"] == tk], tk), "pt-price"
    )

    weights = cache.read(ctrl.run_dir / "weights.parquet", lambda p: readers.load_weights(p.parent))
    w = weights[weights["strategy_id"] == strat]
    last_w = (
        w[w["date"] == w["date"].max()].set_index("ticker")["weight"].to_dict()
        if not w.empty
        else {}
    )
    ticker_rows = [
        {"ticker": t, "weight": last_w.get(t)} for t in sorted(set(tickers) | set(last_w))
    ]

    ftk = request.query_params.get("ftk") or ""
    blot = tr[tr["ticker"] == ftk] if ftk else tr
    try:
        page = int(request.query_params.get("page", 0))
    except ValueError:
        page = 0
    npages = max(1, (len(blot) + _PAGE - 1) // _PAGE)
    page = max(0, min(page, npages - 1))
    view = blot.iloc[page * _PAGE : (page + 1) * _PAGE]

    ctx.update(
        strategy=strat,
        tickers=tickers,
        tk=tk,
        price_fig=price_fig,
        ticker_rows=ticker_rows,
        stack_fig=charts.to_fragment(charts.weight_stack(weights, strat), "pt-stack"),
        blot_cols=list(tr.columns),
        blot_rows=view.to_dict("records"),
        ftk=ftk,
        page=page,
        npages=npages,
        n_trades=len(tr),
    )
    return _render(request, ctx)
