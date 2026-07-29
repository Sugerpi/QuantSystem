"""INV-6：(config, snapshot_hash, git_commit) 三元組決定輸出（規格 §3、§7.1）。

比對對象是**資料產出**，不是整個目錄——run 目錄名含時間戳、manifest 含 created_at，
兩次跑必然不同。邊界寫在 manifest 的 identity / content_hashes / created_at 切分上
（設計文件 §5.2）。

比對用兩種互補手段，皆**不比 parquet 位元組**（pyarrow 版本會改變位元編碼卻不改內容）：
- `assert_frame_equal` 讀回比對：抓列序、值的任何不決定性，對 parquet 編碼穩健。
- manifest `content_hashes`（canonical_hash，設計文件 §5.3）：跨環境可驗證的內容指紋；
  但 canonicalize 會排序，故此項不抓列序——列序由上面的 frame 比對守。
"""

import json

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from quantcore.config import load_config
from quantcore.experiments.runner import run_experiment
from tests.fixtures.synthetic import make_dates, make_snapshot

DATA_FRAMES = ("nav.parquet", "weights.parquet", "decisions.parquet", "trades.parquet")


def _cfg():
    cfg = load_config("quantcore/config/default.yaml").model_copy(deep=True)
    cfg.universe.menu = ["SPY", "QQQ"]
    cfg.universe.min_history_days = 5
    cfg.signal.top_k = 2
    cfg.schedule.selection_interval = 7
    cfg.schedule.exposure_check_interval = 3
    return cfg


def _snap(n=40):
    dates = make_dates(n)
    rng = np.random.default_rng(11)
    return make_snapshot(
        {
            "SPY": list(100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))),
            "QQQ": list(200.0 * np.cumprod(1 + rng.normal(0.0005, 0.012, n))),
        },
        dates,
    )


def _run(tmp_path, name):
    return run_experiment(
        cfg=_cfg(),
        snapshot=_snap(),
        out_root=tmp_path / name,
        label="repro",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )


def test_two_runs_produce_identical_data_artifacts(tmp_path):
    """同輸入兩次跑，資料內容逐格相同（含列序）；對 parquet 位元編碼穩健。"""
    a, b = _run(tmp_path, "a"), _run(tmp_path, "b")
    for fn in DATA_FRAMES:
        assert_frame_equal(pd.read_parquet(a / fn), pd.read_parquet(b / fn))
    ma = json.loads((a / "metrics.json").read_text(encoding="utf-8"))
    mb = json.loads((b / "metrics.json").read_text(encoding="utf-8"))
    assert ma == mb


def test_two_runs_share_identity_and_content_hashes(tmp_path):
    a = json.loads((_run(tmp_path, "a") / "manifest.json").read_text(encoding="utf-8"))
    b = json.loads((_run(tmp_path, "b") / "manifest.json").read_text(encoding="utf-8"))
    assert set(a) == {"identity", "content_hashes", "created_at"}
    assert a["identity"] == b["identity"]
    assert a["content_hashes"] == b["content_hashes"]


def test_content_hash_reflects_actual_data(tmp_path):
    """存的 content_hash 必須真的綁到寫出的資料——否則 hash 是空殼。

    重算讀回 nav 的 canonical_hash，須等於 manifest 記的值。
    """
    from quantcore.data.hashing import canonical_hash, canonicalize

    d = _run(tmp_path, "a")
    stored = json.loads((d / "manifest.json").read_text(encoding="utf-8"))["content_hashes"]
    nav = pd.read_parquet(d / "nav.parquet")
    recomputed = canonical_hash(canonicalize(nav, ["strategy_id", "date"]))
    assert recomputed == stored["nav.parquet"]


def test_changing_config_changes_config_hash(tmp_path):
    a = json.loads((_run(tmp_path, "a") / "manifest.json").read_text(encoding="utf-8"))

    cfg = _cfg()
    cfg.costs.per_side_bps = 20.0
    d = run_experiment(
        cfg=cfg,
        snapshot=_snap(),
        out_root=tmp_path / "c",
        label="repro",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    b = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert a["identity"]["config_hash"] != b["identity"]["config_hash"]


def test_changing_cost_changes_nav_and_its_content_hash(tmp_path):
    """config_hash 變了但輸出沒變 = hash 沒綁到真正影響結果的東西。

    改成本 → nav 數值變 → nav 的 content_hash 亦變（證明 content_hash 綁到真資料）。
    """
    a_dir = _run(tmp_path, "a")
    a_nav = pd.read_parquet(a_dir / "nav.parquet")
    a_hash = json.loads((a_dir / "manifest.json").read_text(encoding="utf-8"))["content_hashes"][
        "nav.parquet"
    ]

    cfg = _cfg()
    cfg.costs.per_side_bps = 20.0
    d = run_experiment(
        cfg=cfg,
        snapshot=_snap(),
        out_root=tmp_path / "c",
        label="repro",
        strategy_ids=["bh_spy", "ew_menu"],
        now=pd.Timestamp("2026-07-17T14:32:11"),
    )
    b_nav = pd.read_parquet(d / "nav.parquet")
    b_hash = json.loads((d / "manifest.json").read_text(encoding="utf-8"))["content_hashes"][
        "nav.parquet"
    ]
    assert not np.allclose(a_nav["nav"].to_numpy(), b_nav["nav"].to_numpy())
    assert a_hash != b_hash
