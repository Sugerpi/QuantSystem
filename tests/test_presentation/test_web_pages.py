from fastapi.testclient import TestClient

from quantcore.presentation.web.app import create_app


def _client(runs_root):
    return TestClient(create_app(runs_root=runs_root))


def test_overview_has_charts_and_metrics_table(runs_root):
    r = _client(runs_root).get("/overview")
    assert r.status_code == 200
    assert "NAV" in r.text
    assert "回撤" in r.text
    assert "曝險" in r.text
    assert "sharpe" in r.text  # 指標表欄
    assert "plotly" in r.text.lower()  # 圖片段已嵌入


def test_overview_backtest_guard_present(runs_root):
    # backtest run 正常渲染，不誤報「非回測 run」
    r = _client(runs_root).get("/overview")
    assert "非回測 run" not in r.text
