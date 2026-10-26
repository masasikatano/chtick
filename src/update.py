"""EastMoney 銘柄マスタ + quote API 価格（Yahoo Finance フォールバック）をまとめて docs/data/latest.json に書き出す。"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src import eastmoney, master, yahoo

log = logging.getLogger("update")
ROOT = Path(__file__).resolve().parents[1]
CST = ZoneInfo("Asia/Shanghai")

UNCATEGORIZED = "未分類"
OTHER = "その他"
# 業種タブの集約: 銘柄数上位 N 個 + その他（EastMoney 業種は細かく約80種あるため）
TOP_SECTORS = 20


def aggregate_sector(sector_counts: dict[str, int]) -> dict[str, str]:
    """セクター名 → タブID の対応を返す（上位TOP_SECTORS + その他）。"""
    ranked = sorted(sector_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top = {name for name, _ in ranked[:TOP_SECTORS]}
    return {name: (name if name in top else OTHER) for name in sector_counts}


def build_payload(records: list[dict], prices: dict[str, dict]) -> dict:
    """prices: { "コード": {"close", "change_pct", "volume", "market_cap", "sector", "as_of"} }。
    取得失敗銘柄はキーなし（price=None で行を残す）。"""

    items: list[dict] = []
    as_of_dates: list[str] = []
    raw_sectors: dict[str, int] = {}
    for rec in records:
        price = prices.get(rec["ticker"])
        sector = (price or {}).get("sector") or UNCATEGORIZED
        raw_sectors[sector] = raw_sectors.get(sector, 0) + 1
        if price is not None:
            as_of_dates.append(price["as_of"])
        items.append({
            "ticker": rec["ticker"],
            "name": rec["name"],
            "exchange": rec["exchange"],
            "sector": sector,
            "fields": rec["fields"],
            "price": price,
        })

    # セクタータブ: 上位TOP_SECTORS + その他（銘柄数順）。全銘柄が所属するタブを必ず作る
    tab_of = aggregate_sector(raw_sectors)
    tab_counts: dict[str, int] = {}
    for it in items:
        it["sector"] = tab_of[it["sector"]]
        tab_counts[it["sector"]] = tab_counts.get(it["sector"], 0) + 1
    categories = [
        {"id": sec, "title": sec, "count": n}
        for sec, n in sorted(tab_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    ref_date = max(as_of_dates) if as_of_dates else None
    with_price = sum(1 for it in items if it["price"] is not None)
    return {
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "source": "eastmoney(+yahoo_finance fallback)",
        "reference": True,
        "reference_date": ref_date,
        "reference_note": f"参考値（CNY, {ref_date}時点）" if ref_date else "参考値（データなし）",
        "categories": categories,
        "count": len(items),
        "with_price_count": with_price,
        "items": items,
    }


def run() -> dict:
    records = master.load_master()
    codes = [rec["ticker"] for rec in records]
    prices = eastmoney.fetch_prices(codes)
    # EastMoney で取得できなかった銘柄は Yahoo Finance で埋める（それも失敗は行を残す）
    missing = [c for c in codes if c not in prices]
    if missing:
        log.info("EastMoney 未取得 %s 銘柄を Yahoo でフォールバック", len(missing))
        for code, price in yahoo.fetch_prices(codes=missing).items():
            if code in missing:
                prices.setdefault(code, price)
    return build_payload(records, prices)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    payload = run()
    out = ROOT / "docs" / "data" / "latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=None, separators=(",", ":")), encoding="utf-8")
    log.info("wrote %s items=%s with_price=%s ref=%s",
             out, payload["count"], payload["with_price_count"], payload["reference_date"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
