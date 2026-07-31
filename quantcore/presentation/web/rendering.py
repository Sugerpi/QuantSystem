"""頁面渲染：整頁 vs HTMX 片段。HX-Request → 只回內容片段（不含骨架）。"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from quantcore.presentation.web.templating import templates

NAV = [
    ("/overview", "總覽"),
    ("/decisions", "決策解剖"),
    ("/garch", "GARCH"),
    ("/correlation", "相關結構"),
    ("/portfolio", "組合與成本"),
    ("/ablation", "消融"),
    ("/data-quality", "資料品質"),
    ("/run-lab", "回測工作台"),
    ("/price-trades", "價格與交易"),
]


def render_page(
    request: Request,
    *,
    active: str,
    full_template: str,
    content_template: str,
    context: dict,
) -> HTMLResponse:
    base_ctx = {"nav": NAV, "active": active, **context}
    is_hx = request.headers.get("HX-Request") == "true"
    name = content_template if is_hx else full_template
    return templates.TemplateResponse(request, name, base_ctx)
