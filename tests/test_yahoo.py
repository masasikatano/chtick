"""Yahoo Finance chart API の接尾辞・終値・前日比算出の回帰テスト。"""

import requests

import src.yahoo as yahoo
from src.yahoo import YAHOO_EXCLUDE, parse_chart, symbol


def test_symbol_SSとSZ接尾辞():
    assert symbol("600000") == "600000.SS"  # 上海
    assert symbol("688981") == "688981.SS"
    assert symbol("000001") == "000001.SZ"  # 深セン
    assert symbol("300750") == "300750.SZ"


def _chart(closes, volumes, timestamps):
    return {
        "chart": {
            "result": [{
                "timestamp": timestamps,
                "indicators": {"quote": [{"close": closes, "volume": volumes}]},
            }]
        }
    }


def test_parse_chart_最後の2点から前日比算出():
    data = _chart([10.0, 11.0], [1000, 2000], [1761436800, 1761523200])
    p = parse_chart(data)
    assert p["close"] == 11.0
    assert p["change_pct"] == 10.0  # (11/10-1)*100
    assert p["volume"] == 2000
    assert p["as_of"] == "2025-10-27"  # 1761523200 = 2025-10-27 UTC


def test_parse_chart_最終点volume欠損は直近有効値():
    data = _chart([10.0, 11.0], [1000, None], [1761436800, 1761523200])
    assert parse_chart(data)["volume"] == 1000


def test_parse_chart_前日比データ1点のみはNone():
    data = _chart([11.0], [2000], [1761523200])
    p = parse_chart(data)
    assert p["close"] == 11.0
    assert p["change_pct"] is None


def test_parse_chart_取得不可はNone():
    assert parse_chart({"chart": {"result": []}}) is None
    assert parse_chart({"chart": {"result": [{"timestamp": [1], "indicators": {"quote": [{"close": [None]}]}}]}}) is None
    assert parse_chart({}) is None


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        raise requests.HTTPError(response=self)

    def json(self):
        return {}


class _FakeSession:
    """指定ステータスで必ず失敗するセッション。呼び出し回数を数える。"""

    def __init__(self, status_code):
        self.headers = {}
        self.status_code = status_code
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return _FakeResponse(self.status_code)


def test_fetch_one_4xxはリトライしない():
    session = _FakeSession(404)
    assert yahoo._fetch_one("000003", session) is None
    assert session.calls == 1  # 即諦める


def test_fetch_one_5xxはリトライする(monkeypatch):
    session = _FakeSession(502)
    monkeypatch.setattr(yahoo.time, "sleep", lambda s: None)
    assert yahoo._fetch_one("600000", session) is None
    assert session.calls == yahoo.RETRIES


def test_fetch_prices_除外銘柄はリクエストしない(monkeypatch):
    assert "000003" in YAHOO_EXCLUDE  # 前提：除外対象が登録されている
    called = []
    monkeypatch.setattr(yahoo, "_fetch_one",
                        lambda code, session=None: called.append(code) or {"close": 1.0})
    assert yahoo.fetch_prices(["000003", "600000"]) == {"600000": {"close": 1.0}}
    assert called == ["600000"]
