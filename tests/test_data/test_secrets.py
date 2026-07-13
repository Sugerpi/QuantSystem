"""密鑰讀取：優先 os.environ，缺鍵給清楚錯誤。"""

import pytest

from quantcore.data.secrets import MissingSecretError, get_secret


def test_get_secret_from_environ(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "abc123")
    assert get_secret("TIINGO_API_KEY") == "abc123"


def test_missing_secret_raises_with_hint(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    with pytest.raises(MissingSecretError) as exc:
        get_secret("TIINGO_API_KEY")
    assert "TIINGO_API_KEY" in str(exc.value)
    assert ".env" in str(exc.value)
