"""EastMoney quote API の secid・前日比自前計算・除外管理の回帰テスト。"""

from src.eastmoney import parse_quote, secid


def test_secid_市場プレフィクス():
    assert secid("600000") == "1.600000"  # 上海
    assert secid("688981") == "1.688981"  # 科創板（上海）
    assert secid("000001") == "0.000001"  # 深セン
    assert secid("300750") == "0.300750"  # 創業板（深セン）


def test_parse_quote_終値前日比出来高時価総額業種():
    p = parse_quote({"f12": "600000", "f2": 11.0, "f18": 10.0, "f5": 123456,
                     "f20": 322900000000, "f100": "銀行"}, "2026-10-26")
    assert p["close"] == 11.0
    assert p["change_pct"] == 10.0  # (11/10-1)*100 を自前計算
    assert p["volume"] == 123456
    assert p["market_cap"] == 322900000000
    assert p["sector"] == "銀行"
    assert p["as_of"] == "2026-10-26"


def test_parse_quote_前日終値ゼロや欠損は前日比なし():
    assert parse_quote({"f2": 11.0, "f18": 0, "f5": None, "f20": "-", "f100": "-"}, "2026-10-26") == {
        "close": 11.0, "change_pct": None, "volume": None,
        "market_cap": None, "sector": None, "as_of": "2026-10-26",
    }
    assert parse_quote({"f2": 11.0, "f18": "-", "f5": 100, "f20": 1000, "f100": "银行"}, "2026-10-26")["change_pct"] is None


def test_parse_quote_取得不可はNone():
    assert parse_quote({"f2": "-"}, "2026-10-26") is None
    assert parse_quote({}, "2026-10-26") is None
