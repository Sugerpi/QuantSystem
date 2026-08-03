from fastapi.testclient import TestClient

from quantcore.presentation.web.app import create_app


def _client(runs_root):
    return TestClient(create_app(runs_root=runs_root))


def test_index_redirects_to_overview(runs_root):
    r = _client(runs_root).get("/", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"] == "/overview"


def test_overview_returns_200_with_run_data(runs_root):
    r = _client(runs_root).get("/overview")
    assert r.status_code == 200
    assert "總覽" in r.text
    assert "full" in r.text  # 合成 run 有 bh_spy/full 策略


def test_sidebar_lists_nine_pages(runs_root):
    r = _client(runs_root).get("/overview")
    for label in [
        "總覽",
        "決策解剖",
        "GARCH",
        "相關結構",
        "組合與成本",
        "消融",
        "資料品質",
        "回測工作台",
        "價格與交易",
    ]:
        assert label in r.text


def test_default_run_is_a_backtest_run(runs_root):
    r = _client(runs_root).get("/overview")
    assert r.status_code == 200
    assert "無回測 run" not in r.text
