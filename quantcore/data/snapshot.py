"""不可變快照的建立/載入/hash（規格 §4.2）+ CLI。

回測永不直連網路；只有本模組的 create 連網。建立流程：
抓取 → 驗證來源覆蓋檢查 → §4.3 驗證 → §4.5 跨源 → 全過才寫檔（canonical hash）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pandas as pd

from quantcore.config import QuantConfig, load_config
from quantcore.data import validation as v
from quantcore.data.calendar import NyseCalendar
from quantcore.data.crosssource import cross_validate
from quantcore.data.hashing import (
    canonical_hash,
    canonicalize,
    combined_hash,
    config_hash,
    snapshot_id,
)
from quantcore.data.provider import PRICE_COLUMNS

_RATES_SERIES = "DTB3"

try:
    _QC_VERSION = version("quantcore")
except PackageNotFoundError:  # pragma: no cover
    _QC_VERSION = "unknown"


def _run_validation(
    prices: pd.DataFrame,
    spy_dividends: pd.DataFrame,
    cfg: QuantConfig,
    calendar: NyseCalendar,
) -> list:
    dq = cfg.data_quality
    spy = prices[prices["ticker"] == "SPY"]
    return [
        v.check_total_return(spy, spy_dividends, dq.total_return_tol_bps),
        v.check_extreme_returns(prices, dq.extreme_return),
        v.check_missing_values(prices, dq.max_consecutive_nan),
        v.check_calendar(prices, calendar),
        v.check_monotonic(prices),
    ]


def _json_safe_overrides(overrides: list[dict]) -> list[dict]:
    """把 overrides 中的 numpy 純量轉成 JSON 原生型別（避免 json.dumps TypeError）。"""
    safe = []
    for o in overrides:
        safe.append(
            {
                k: (
                    None
                    if (isinstance(v, float) and pd.isna(v))
                    else float(v)
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                    else v
                )
                for k, v in o.items()
            }
        )
    return safe


def create_snapshot(
    cfg: QuantConfig,
    *,
    primary,
    validation,
    rates,
    arbiter=None,
    out_root: Path,
    build_date: pd.Timestamp,
) -> Path:
    """建立快照目錄並回傳其 Path。任一硬性驗證失敗 → raise ValueError。

    arbiter 為可選第三源（如 Stooq）：僅盡力抓取（best-effort），不納入驗證來源
    覆蓋檢查；若提供則傳入 cross_validate 供 §4.5 少數服從多數裁決。
    """
    out_root = Path(out_root)
    menu = cfg.universe.menu
    start, end = cfg.backtest.start, build_date.date()
    calendar = NyseCalendar()

    prices = primary.fetch_prices(menu, start, end)[PRICE_COLUMNS]
    val_prices = validation.fetch_prices(menu, start, end)[PRICE_COLUMNS]
    arb_prices = None
    if arbiter is not None:
        arb_prices = arbiter.fetch_prices(menu, start, end)[PRICE_COLUMNS]
    metadata_raw = primary.fetch_metadata(menu)
    # §4.3-1 僅抽查 SPY，且 check_total_return 為單一 ticker 契約、股息 date-keyed，
    # 故只取 SPY 股息（避免跨檔股息污染）。
    spy_dividends = primary.fetch_dividends("SPY", start, end)
    rates_series = rates.fetch_series(_RATES_SERIES, start, end)

    # 驗證來源覆蓋檢查：任一 menu ticker 未被驗證來源回傳 → 無法交叉驗證，硬失敗。
    val_tickers = set(val_prices["ticker"].unique())
    missing_val = [t for t in menu if t not in val_tickers]
    if missing_val:
        raise ValueError(f"驗證來源未回傳資料，無法交叉驗證：{missing_val}")

    # §4.3 驗證
    results = _run_validation(prices, spy_dividends, cfg, calendar)
    hard_failures = [r for r in results if r.hard_fail and not r.passed]
    if hard_failures:
        names = ", ".join(r.name for r in hard_failures)
        raise ValueError(f"資料驗證失敗（§4.3）：{names}")

    # §4.5 跨源
    dq = cfg.data_quality
    xs = cross_validate(
        prices,
        val_prices,
        discrepancy_bps=dq.discrepancy_bps,
        window_days=dq.window_days,
        window_max_hits=dq.window_max_hits,
        arbiter=arb_prices,
    )
    if not xs.passed:
        raise ValueError(f"跨源驗證失敗（§4.5），需人工裁決：{xs.failed_assets}")

    # canonical 化 + hash
    prices_c = canonicalize(prices, ["ticker", "date"])
    rates_df = canonicalize(
        pd.DataFrame(
            {
                "date": pd.to_datetime(rates_series.index),
                _RATES_SERIES: rates_series.to_numpy(dtype="float64"),
            }
        ),
        ["date"],
    )
    providers_meta = {
        "primary": type(primary).__name__,
        "validation": [type(validation).__name__],
        "rates": type(rates).__name__,
    }
    metadata = {
        "tickers": metadata_raw,
        "overrides": _json_safe_overrides(xs.overrides),
        "sources": providers_meta,
    }
    meta_bytes = json.dumps(metadata, sort_keys=True, ensure_ascii=False).encode("utf-8")

    ph = canonical_hash(prices_c)
    rh = canonical_hash(rates_df)
    mh = hashlib.sha256(meta_bytes).hexdigest()
    ch = config_hash(cfg.model_dump(mode="json"))
    disc_hash = combined_hash([r["ticker"] + r["date"] for r in xs.report]) if xs.report else None

    combined = combined_hash([ch, ph, rh, mh])
    sid = snapshot_id(build_date, combined)
    out_dir = out_root / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    prices_c.to_parquet(out_dir / "prices.parquet", index=False)
    rates_df.to_parquet(out_dir / "rates.parquet", index=False)
    (out_dir / "metadata.json").write_bytes(meta_bytes)

    manifest = {
        "snapshot_id": sid,
        "created_at": datetime.now(UTC).isoformat(),
        "config_hash": ch,
        "content_hashes": {
            "prices.parquet": ph,
            "rates.parquet": rh,
            "metadata.json": mh,
        },
        "discrepancy_report_hash": disc_hash,
        "discrepancy_report": xs.report,
        "providers": providers_meta,
        "quantcore_version": _QC_VERSION,
    }
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out_dir


def load_snapshot(snapshot_dir: str | Path) -> dict:
    """載入快照並驗證 content hash（唯讀完整性）。"""
    d = Path(snapshot_dir)
    manifest = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
    prices = pd.read_parquet(d / "prices.parquet")
    rates = pd.read_parquet(d / "rates.parquet")
    meta_bytes = (d / "metadata.json").read_bytes()
    metadata = json.loads(meta_bytes.decode("utf-8"))
    ch = manifest["content_hashes"]
    if canonical_hash(canonicalize(prices, ["ticker", "date"])) != ch["prices.parquet"]:
        raise ValueError(f"快照 prices.parquet hash 不符：{d}")
    if canonical_hash(canonicalize(rates, ["date"])) != ch["rates.parquet"]:
        raise ValueError(f"快照 rates.parquet hash 不符：{d}")
    if hashlib.sha256(meta_bytes).hexdigest() != ch["metadata.json"]:
        raise ValueError(f"快照 metadata.json hash 不符：{d}")
    return {
        "prices": prices,
        "rates": rates,
        "metadata": metadata,
        "manifest": manifest,
    }


def _date_range(df: pd.DataFrame) -> str:
    lo, hi = df["date"].min(), df["date"].max()
    return f"{lo:%Y-%m-%d} → {hi:%Y-%m-%d}"


def format_summary(snap: dict) -> str:
    """把 load_snapshot 的結果整理成人類可讀的摘要。"""
    manifest, metadata = snap["manifest"], snap["metadata"]
    prices, rates = snap["prices"], snap["rates"]
    tickers = sorted(prices["ticker"].unique())
    series = [c for c in rates.columns if c != "date"]
    lines = [
        f"snapshot_id      : {manifest['snapshot_id']}",
        f"created_at       : {manifest['created_at']}",
        f"quantcore_version: {manifest.get('quantcore_version', 'unknown')}",
        f"config_hash      : {manifest['config_hash']}",
        f"providers        : {manifest.get('providers', {})}",
        "",
        f"prices           : {len(prices)} 列 × {len(prices.columns)} 欄　{_date_range(prices)}",
        f"  tickers ({len(tickers)})   : {', '.join(tickers)}",
        f"rates            : {len(rates)} 列　{_date_range(rates)}　series: {', '.join(series)}",
        "",
        f"跨源差異未解決    : {len(manifest.get('discrepancy_report', []))} 筆",
        f"仲裁 overrides   : {len(metadata.get('overrides', []))} 筆",
    ]
    return "\n".join(lines)


def _cli(argv: list[str] | None = None) -> int:
    # Windows 主控台的 Python 預設用 locale 編碼（cp950），會把中文輸出燒成亂碼。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="python -m quantcore.data.snapshot")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="建立不可變快照")
    create.add_argument("--config", required=True)
    inspect = sub.add_parser("inspect", help="檢視既有快照摘要（會驗證 content hash）")
    inspect.add_argument("--snapshot", required=True)
    args = parser.parse_args(argv)

    if args.command == "inspect":
        print(format_summary(load_snapshot(args.snapshot)))
        return 0

    if args.command == "create":
        from quantcore.data.providers.fred_adapter import FredAdapter
        from quantcore.data.providers.tiingo_adapter import TiingoAdapter
        from quantcore.data.providers.twelvedata_adapter import TwelveDataAdapter
        from quantcore.data.providers.yfinance_adapter import YFinanceAdapter

        cfg = load_config(args.config)
        out = create_snapshot(
            cfg,
            primary=YFinanceAdapter(),
            validation=TiingoAdapter(),
            rates=FredAdapter(),
            arbiter=TwelveDataAdapter(),
            out_root=Path("snapshots"),
            build_date=pd.Timestamp.now().normalize(),
        )
        print(f"快照已建立：{out}")
        print(f"請將 default.yaml 的 snapshot: 欄位填為 {out.as_posix()}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
