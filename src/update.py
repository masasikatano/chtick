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

# EastMoney 業種名（中国語）→ 日本語表示名。未登録の名前は中国語のまま表示する
SECTOR_JA: dict[str, str] = {
    "IT服务Ⅱ": "ITサービスⅡ",
    "一般零售": "一般小売",
    "专业工程": "専門工事",
    "专业服务": "専門サービス",
    "专业连锁Ⅱ": "専門チェーンⅡ",
    "专用设备": "特殊設備",
    "个护用品": "パーソナルケア用品",
    "中药Ⅱ": "漢方薬Ⅱ",
    "乘用车": "乗用車",
    "互联网电商": "インターネット通販",
    "休闲食品": "菓子・食品",
    "体育Ⅱ": "スポーツⅡ",
    "保险Ⅱ": "保険Ⅱ",
    "元件": "電子部品",
    "光伏设备": "太陽光発電設備",
    "光学光电子": "光学光電子",
    "其他家电Ⅱ": "その他家電Ⅱ",
    "其他电子Ⅱ": "その他電子Ⅱ",
    "其他电源设备Ⅱ": "その他電源設備Ⅱ",
    "养殖业": "畜産",
    "军工电子Ⅱ": "軍事電子Ⅱ",
    "农业综合Ⅱ": "農業総合Ⅱ",
    "农产品加工": "農産物加工",
    "农化制品": "農薬・化学肥料",
    "冶钢原料": "製鉄原料",
    "出版": "出版",
    "动物保健Ⅱ": "動物用医薬品Ⅱ",
    "包装印刷": "包装印刷",
    "化妆品": "化粧品",
    "化学制品": "化学製品",
    "化学制药": "化学医薬品",
    "化学原料": "化学原料",
    "化学纤维": "化学繊維",
    "医疗器械": "医療機器",
    "医疗服务": "医療サービス",
    "医疗美容": "医療美容",
    "医药商业": "医薬品卸売",
    "半导体": "半導体",
    "厨卫电器": "キッチン・バス家電",
    "商用车": "商用車",
    "地面兵装Ⅱ": "地上兵装Ⅱ",
    "基础建设": "基礎建設",
    "塑料": "プラスチック",
    "多元金融": "総合金融",
    "家居用品": "家具・家庭用品",
    "家电零部件Ⅱ": "家電部品Ⅱ",
    "小家电": "小型家電",
    "小金属": "レアメタル",
    "工业金属": "工業金属",
    "工程咨询服务Ⅱ": "工学コンサルⅡ",
    "工程机械": "建設機械",
    "广告营销": "広告・マーケティング",
    "影视院线": "映画・劇場",
    "房地产开发": "不動産開発",
    "房地产服务": "不動産サービス",
    "房屋建设Ⅱ": "住宅建設Ⅱ",
    "摩托车及其他": "オートバイその他",
    "教育": "教育",
    "数字媒体": "デジタルメディア",
    "文娱用品": "娯楽用品",
    "旅游及景区": "旅行・観光地",
    "旅游零售Ⅱ": "観光小売Ⅱ",
    "普钢": "普通鋼",
    "服装家纺": "アパレル・寝装品",
    "林业Ⅱ": "林業Ⅱ",
    "橡胶": "ゴム",
    "水泥": "セメント",
    "汽车服务": "自動車サービス",
    "汽车零部件": "自動車部品",
    "油服工程": "油田サービス",
    "油气开采Ⅱ": "石油・ガス開発Ⅱ",
    "消费电子": "コンシューマー電機",
    "渔业": "漁業",
    "游戏Ⅱ": "ゲームⅡ",
    "炼化及贸易": "石油精製・販売",
    "焦炭Ⅱ": "コークスⅡ",
    "煤炭开采": "石炭採掘",
    "照明设备Ⅱ": "照明機器Ⅱ",
    "燃气Ⅱ": "ガスⅡ",
    "物流": "物流",
    "特钢Ⅱ": "特殊鋼Ⅱ",
    "环保设备Ⅱ": "環境機器Ⅱ",
    "环境治理": "環境整備",
    "玻璃玻纤": "ガラス・ガラス繊維",
    "生物制品": "バイオ製品",
    "电力": "電力",
    "电子化学品Ⅱ": "電子化学薬品Ⅱ",
    "电机Ⅱ": "電気機器Ⅱ",
    "电池": "電池",
    "电网设备": "送配電設備",
    "电视广播Ⅱ": "テレビ・放送Ⅱ",
    "白色家电": "白物家電",
    "白酒Ⅱ": "白酒Ⅱ",
    "种植业": "農作物栽培",
    "纺织制造": "繊維製造",
    "综合Ⅱ": "総合Ⅱ",
    "能源金属": "エネルギー金属",
    "自动化设备": "自動化設備",
    "航天装备Ⅱ": "宇宙機器Ⅱ",
    "航海装备Ⅱ": "船舶装備Ⅱ",
    "航空机场": "航空・空港",
    "航空装备Ⅱ": "航空装備Ⅱ",
    "航运港口": "海運・港湾",
    "装修建材": "内装建材",
    "装修装饰Ⅱ": "内装装飾Ⅱ",
    "计算机设备": "コンピュータ機器",
    "证券Ⅱ": "証券Ⅱ",
    "调味发酵品Ⅱ": "調味料・発酵食品Ⅱ",
    "贵金属": "貴金属",
    "贸易Ⅱ": "貿易Ⅱ",
    "轨交设备Ⅱ": "鉄道輸送機器Ⅱ",
    "软件开发": "ソフトウェア開発",
    "通信服务": "通信サービス",
    "通信设备": "通信機器",
    "通用设备": "汎用設備",
    "造纸": "製紙",
    "酒店餐饮": "ホテル・外食",
    "金属新材料": "金属新材料",
    "铁路公路": "鉄道・道路",
    "银行Ⅱ": "銀行Ⅱ",
    "非白酒": "白酒以外",
    "非金属材料Ⅱ": "非金属材料Ⅱ",
    "风电设备": "風力発電設備",
    "食品加工": "食品加工",
    "饮料乳品": "飲料・乳製品",
    "饰品": "アクセサリー",
    "饲料": "飼料",
    "黑色家电": "黒物家電",
}


def sector_label(sector: str) -> str:
    """EastMoney の中国語業種名を日本語表示名に変換（未登録はそのまま）。"""
    return SECTOR_JA.get(sector, sector)


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
        sector = sector_label((price or {}).get("sector") or UNCATEGORIZED)
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
