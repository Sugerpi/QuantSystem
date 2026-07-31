import os

from quantcore.presentation.web import cache


def test_read_caches_until_mtime_changes(tmp_path):
    cache.clear()
    p = tmp_path / "f.txt"
    p.write_text("1", encoding="utf-8")
    calls = {"n": 0}

    def loader(path):
        calls["n"] += 1
        return path.read_text(encoding="utf-8")

    assert cache.read(p, loader) == "1"
    assert cache.read(p, loader) == "1"
    assert calls["n"] == 1

    p.write_text("2", encoding="utf-8")
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 10))
    assert cache.read(p, loader) == "2"
    assert calls["n"] == 2
