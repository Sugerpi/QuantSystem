"""頁 1 總覽：KPI 卡 + NAV 對數疊圖 + 回撤 + 曝險 E(t) + 指標表 + 子期間（§11.2）。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation import readers
from quantcore.presentation.web import cache, charts
from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()

_METRIC_COLS = (
    "annualized_return",
    "sharpe",
    "sortino",
    "max_drawdown",
    "calmar",
    "annualized_turnover",
    "average_exposure",
)


@router.get("/overview", response_class=HTMLResponse)
def overview(request: Request) -> HTMLResponse:
    ctrl = controls_for(request)
    ctx: dict = {"ctrl": ctrl, "error": None}
    if ctrl.run_dir is None:
        ctx["error"] = "runs/ 下無回測 run。"
    elif not readers.is_backtest_run(ctrl.run_dir):
        ctx["error"] = f"{ctrl.run} 非回測 run（無 nav/decisions）——請選 canonical/backtest run。"
    else:
        nav = cache.read(ctrl.run_dir / "nav.parquet", lambda p: readers.load_nav(p.parent))
        decisions = cache.read(
            ctrl.run_dir / "decisions.parquet", lambda p: readers.load_decisions(p.parent)
        )
        metrics = cache.read(
            ctrl.run_dir / "metrics.json", lambda p: readers.load_metrics(p.parent)
        )
        shown = ctrl.strategies or sorted(nav["strategy_id"].unique())
        rows = [
            {"strategy": s, **{c: metrics[s].get(c) for c in _METRIC_COLS}}
            for s in shown
            if s in metrics
        ]
        subperiods = None
        if shown and shown[0] in metrics and metrics[shown[0]].get("subperiods"):
            subperiods = metrics[shown[0]]["subperiods"]
        ctx.update(
            nav_fig=charts.to_fragment(charts.nav_log(nav, shown), "ov-nav"),
            dd_fig=charts.to_fragment(charts.drawdown(nav, shown), "ov-dd"),
            exp_fig=charts.to_fragment(charts.exposure(decisions, shown), "ov-exp"),
            metric_cols=_METRIC_COLS,
            metric_rows=rows,
            sub_strategy=shown[0] if shown else None,
            subperiods=subperiods,
        )
    return render_page(
        request,
        active="/overview",
        full_template="overview.html",
        content_template="overview_content.html",
        context=ctx,
    )
