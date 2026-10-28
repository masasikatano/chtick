"""latest.json のペイロード構成・セクター集約・UTF-8エンコーディングの回帰テスト。"""

import json

from src.update import OTHER, TOP_SECTORS, SECTOR_JA, UNCATEGORIZED, aggregate_sector, build_payload, sector_label


def _rec(ticker, name, exchange="上海"):
    return {"ticker": ticker, "name": name, "exchange": exchange, "fields": {"f12": ticker}}


def _price(close=10.0, sector="銀行", **kw):
    return {"close": close, "change_pct": 1.0, "volume": 100, "market_cap": 1000,
            "sector": sector, "as_of": "2026-10-26", **kw}


def test_ペイロード基本構成と7列に必要なフィールド():
    payload = build_payload([_rec("600000", "浦発銀行")], {"600000": _price()})
    assert payload["count"] == 1
    assert payload["with_price_count"] == 1
    assert payload["reference"] is True
    assert payload["reference_note"] == "参考値（CNY, 2026-10-26時点）"
    assert payload["timezone"] == "Asia/Shanghai"
    item = payload["items"][0]
    assert set(item) == {"ticker", "name", "exchange", "sector", "fields", "price"}
    assert item["price"]["market_cap"] == 1000  # latest.json のみ保持（表示列には使わない）
    assert item["fields"]["f12"] == "600000"    # マスタ全列保持


def test_価格取得失敗銘柄は行を残してセクター未分類():
    payload = build_payload([_rec("600000", "浦発銀行"), _rec("000001", "平安銀行", "深セン")],
                            {"600000": _price()})
    assert payload["with_price_count"] == 1
    miss = payload["items"][1]
    assert miss["price"] is None
    assert miss["sector"] == UNCATEGORIZED
    cats = {c["id"]: c["count"] for c in payload["categories"]}
    assert cats[UNCATEGORIZED] == 1


def test_セクター集約_上位Nとその他():
    counts = {f"業種{i:02d}": 1 for i in range(TOP_SECTORS + 5)}
    counts["大口"] = 999
    tab_of = aggregate_sector(counts)
    assert tab_of["大口"] == "大口"
    individual = [n for n, tab in tab_of.items() if tab != OTHER]
    assert len(individual) == TOP_SECTORS  # 上位Nのみ個別タブ、残りはその他
    assert "大口" in individual
    assert sum(1 for tab in tab_of.values() if tab == OTHER) == len(counts) - TOP_SECTORS


def test_セクタータブは全銘柄が所属し銘柄数順():
    prices = {f"6000{i:02d}": _price(sector="銀行") for i in range(3)}
    prices["600099"] = _price(sector="半導体")
    records = [_rec(c, f"銘柄{c}") for c in prices]
    payload = build_payload(records, prices)
    cats = payload["categories"]
    assert cats[0]["id"] == "銀行" and cats[0]["count"] == 3
    covered = sum(c["count"] for c in cats)
    assert covered == len(records)
    for item in payload["items"]:
        assert any(c["id"] == item["sector"] for c in cats)


def test_UTF8中国語銘柄名が化けない():
    payload = build_payload([_rec("600000", "浦发银行"), _rec("300750", "宁德时代", "深セン")],
                            {"600000": _price(), "300750": _price(sector="电池")})
    text = json.dumps(payload, ensure_ascii=False)
    loaded = json.loads(text)
    assert loaded["items"][0]["name"] == "浦发银行"
    assert loaded["items"][1]["name"] == "宁德时代"
    assert "浦发银行" in text  # ensure_ascii=False で UTF-8 のまま


def test_セクター名は日本語変換され未登録は中国語のまま():
    assert sector_label("银行Ⅱ") == "銀行Ⅱ"
    assert sector_label("半导体") == "半導体"
    assert sector_label(UNCATEGORIZED) == UNCATEGORIZED
    assert sector_label("登録なし") == "登録なし"  # 未登録は中国語のまま
    payload = build_payload([_rec("600000", "浦发银行")], {"600000": _price(sector="电池")})
    assert payload["items"][0]["sector"] == "電池"
    assert payload["categories"][0]["id"] == "電池"


def _rec_with_sector(ticker, name, sector, exchange="上海"):
    rec = _rec(ticker, name, exchange)
    rec["fields"]["f100"] = sector
    return rec


def test_マスタ側f100を優先してセクター決定():
    # clist 由来のマスタ業種があれば価格側の sector より優先される
    payload = build_payload([_rec_with_sector("600000", "浦发银行", "银行Ⅱ")],
                            {"600000": _price(sector="半导体")})
    assert payload["items"][0]["sector"] == "銀行Ⅱ"


def test_マスタ側f100が無い銘柄は価格側セクターで補完():
    payload = build_payload([_rec("600000", "浦发银行")], {"600000": _price(sector="半导体")})
    assert payload["items"][0]["sector"] == "半導体"


def test_マスタ側f100がハイフンや欠損でも価格側にフォールバック():
    rec = _rec_with_sector("600000", "浦发银行", "-")  # 廃止銘柄等の "-"
    payload = build_payload([rec], {"600000": _price(sector="半导体")})
    assert payload["items"][0]["sector"] == "半導体"
    rec["fields"].pop("f100")
    payload = build_payload([rec], {"600000": _price(sector="半导体")})
    assert payload["items"][0]["sector"] == "半導体"


def test_価格取得失敗でもマスタ側f100があれば未分類にならない():
    payload = build_payload([_rec_with_sector("600000", "浦发银行", "银行Ⅱ")], {})
    item = payload["items"][0]
    assert item["price"] is None
    assert item["sector"] == "銀行Ⅱ"
