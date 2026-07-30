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
