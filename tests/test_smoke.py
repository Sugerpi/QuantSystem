"""Phase 0 冒煙測試：套件可 import、版本存在。"""

import quantcore


def test_package_imports():
    assert quantcore.__version__ == "0.1.0"
