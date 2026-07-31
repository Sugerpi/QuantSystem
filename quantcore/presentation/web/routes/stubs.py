"""其餘 8 頁佔位。計畫 2 逐頁以真實內容取代。共用 render_page + controls_for。

HTMX 片段自動生效（render_page 依 HX-Request 回片段 vs 整頁）。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quantcore.presentation.web.rendering import controls_for, render_page

router = APIRouter()

_STUBS = [
    ("/correlation", "相關結構"),
    ("/ablation", "消融"),
    ("/run-lab", "回測工作台"),
    ("/price-trades", "價格與交易"),
]


def _make(path: str, title: str):
    def handler(request: Request) -> HTMLResponse:
        return render_page(
            request,
            active=path,
            full_template="stub.html",
            content_template="stub_content.html",
            context={"ctrl": controls_for(request), "title": title},
        )

    return handler


for _path, _title in _STUBS:
    router.add_api_route(_path, _make(_path, _title), methods=["GET"], response_class=HTMLResponse)
