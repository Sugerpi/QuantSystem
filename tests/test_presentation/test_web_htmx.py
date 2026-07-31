from fastapi.testclient import TestClient

from quantcore.presentation.web.app import create_app


def _client(runs_root):
    return TestClient(create_app(runs_root=runs_root))


def test_hx_request_returns_content_only(runs_root):
    r = _client(runs_root).get("/overview", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "總覽" in r.text
    assert '<nav class="sidebar"' not in r.text  # 片段不含骨架
    assert "<!doctype html>" not in r.text.lower()


def test_full_request_includes_shell(runs_root):
    r = _client(runs_root).get("/overview")
    assert '<nav class="sidebar"' in r.text


def test_stub_pages_reachable(runs_root):
    client = _client(runs_root)
    for path in [
        "/ablation",
        "/run-lab",
        "/price-trades",
    ]:
        r = client.get(path)
        assert r.status_code == 200
        assert "建置中" in r.text


def test_stub_hx_fragment_excludes_shell(runs_root):
    r = _client(runs_root).get("/garch", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert '<nav class="sidebar"' not in r.text
