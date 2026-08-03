"""頁 6 消融：指標表、敏感度熱圖（?metric）、配對 bootstrap CI 表。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()

_METRICS = ("sharpe", "calmar", "max_drawdown", "annualized_return")


def _render(request: Request, ctx: dict) -> HTMLResponse:
    return render_page(
        request,
        active="/ablation",
        full_template="ablation.html",
        content_template="ablation_content.html",
        context=ctx,
    )


@router.get("/ablation", response_class=HTMLResponse)
def ablation(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    comp = cache.read(ctrl.run_dir, readers.load_comparison) if ctrl.run_dir else None
    if comp is None:
        ctx["error"] = "本 run 無消融表（comparison.parquet）——請選一個消融 run。"
        return _render(request, ctx)
    metric = request.query_params.get("metric", "sharpe")
    if metric not in _METRICS:
        metric = "sharpe"
    piv = comp.pivot_table(index="cell_label", columns="strategy_id", values=metric)
    bs = readers.load_bootstrap(ctrl.run_dir)
    ctx.update(
        comp_cols=list(comp.columns),
        comp_rows=comp.to_dict("records"),
        metrics=_METRICS,
        metric=metric,
        heat_fig=charts.to_fragment(
            charts.heatmap(piv.values, list(piv.columns), list(piv.index), colorscale="Viridis"),
            "ab-heat",
        ),
        bs_cols=list(bs.columns) if bs is not None else None,
        bs_rows=bs.to_dict("records") if bs is not None else None,
    )
    return _render(request, ctx)
