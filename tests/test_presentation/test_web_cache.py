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


def test_distinct_loaders_same_path_do_not_collide(tmp_path):
    # 同一路徑、兩個不同 loader 不得互相供錯結果（鍵含 loader 身份）。
    cache.clear()
    p = tmp_path / "d"
    p.mkdir()

    def load_a(path):
        return "A"

    def load_b(path):
        return "B"

    assert cache.read(p, load_a) == "A"
    assert cache.read(p, load_b) == "B"
    assert cache.read(p, load_a) == "A"
