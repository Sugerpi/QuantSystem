"""dashboard AppTest 冒煙：入口 + 各頁對合成 run 渲染不拋例外。"""

from streamlit.testing.v1 import AppTest

_APP = "quantcore/presentation/app.py"


def _seed(at, runs_root, run_name, strategy="full"):
    at.session_state["runs_root"] = str(runs_root)
    at.session_state["selected_runs"] = [run_name]
    at.session_state["selected_strategies"] = [strategy]


def test_app_entry_renders(runs_root, run_dir):
    at = AppTest.from_file(_APP, default_timeout=30)
    _seed(at, runs_root, run_dir.name)
    at.run()
    assert not at.exception


def test_overview_renders(runs_root, run_dir):
    at = AppTest.from_file("quantcore/presentation/pages/1_Overview.py", default_timeout=30)
    _seed(at, runs_root, run_dir.name)
    at.run()
    assert not at.exception
    assert any("總覽" in t.value for t in at.title)


def test_overview_no_selection_is_graceful(runs_root):
    at = AppTest.from_file("quantcore/presentation/pages/1_Overview.py", default_timeout=30)
    at.session_state["runs_root"] = str(runs_root)
    at.session_state["selected_runs"] = []
    at.run()
    assert not at.exception  # 未選 run 也不崩潰


def test_decision_explorer_renders_six_layers(runs_root, run_dir):
    at = AppTest.from_file(
        "quantcore/presentation/pages/2_Decision_Explorer.py", default_timeout=30
    )
    _seed(at, runs_root, run_dir.name, strategy="full")
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown) + " ".join(s.value for s in at.subheader)
    for layer in ("合格選單", "動量分數", "絕對動量", "波動", "曝險", "目標權重"):
        assert layer in text
