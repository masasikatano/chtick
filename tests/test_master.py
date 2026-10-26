"""EastMoney 銘柄一覧API のコード帯フィルタ・取引所判別の回帰テスト。"""

import pytest

from src.master import exchange_of, is_a_share, parse_clist_page


@pytest.mark.parametrize("code", [
    "600000",  # 上海主板
    "601318",  # 上海主板
    "603259",  # 上海主板
    "605499",  # 上海主板
    "688981",  # 科創板
    "689009",  # 科創板（CDR）
    "000001",  # 深セン主板
    "002594",  # 深セン中小板（主板統合済み）
    "003816",  # 深セン主板
    "300750",  # 創業板
    "301308",  # 創業板
])
def test_a_share_コード帯は含める(code):
    assert is_a_share(code)


@pytest.mark.parametrize("code", [
    "900901",  # B股（上海）
    "200002",  # B股（深セン）
    "830799",  # BSE（8xxxxx）
    "430047",  # BSE（4xxxxx）
    "920002",  # BSE（92xxxx）
    "150001",  # ETF/LOF 等
    "160131",  # LOF
    "501018",  # ETF
    "580001",  # 認証券等
    "110001",  # 転換社債
    "128001",  # 社債（12xxxx）
    "ABC",     # 6桁数字でない
    "60000",   # 5桁
    "1234567", # 7桁
])
def test_非普通株コード帯は除外(code):
    assert not is_a_share(code)


def test_取引所判別():
    assert exchange_of("600000") == "上海"
    assert exchange_of("688981") == "上海"
    assert exchange_of("000001") == "深セン"
    assert exchange_of("300750") == "深セン"


CLIST_SAMPLE = {
    "data": {
        "total": 4,
        "diff": [
            {"f12": "600000", "f14": "浦発銀行", "f2": 8.5, "f13": 1},
            {"f12": "900901", "f14": "儀電B股", "f2": 0.5, "f13": 1},   # B股は除外
            {"f12": "300750", "f14": "寧徳時代", "f2": 180.0, "f13": 0},
            {"f12": "830799", "f14": "艾融软件", "f2": 10.0, "f13": 0},  # BSEは除外
        ],
    }
}


def test_parse_clist_page_普通株のみ抽出して全列保持():
    records = parse_clist_page(CLIST_SAMPLE)
    assert [r["ticker"] for r in records] == ["600000", "300750"]
    sh, sz = records
    assert sh["exchange"] == "上海"
    assert sh["name"] == "浦発銀行"
    assert sh["fields"]["f2"] == 8.5  # 全列は fields に保持
    assert sz["exchange"] == "深セン"


def test_parse_clist_page_データなしは空リスト():
    assert parse_clist_page({"data": None}) == []
    assert parse_clist_page({}) == []


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_ulistプローブで存在銘柄のみ抽出(monkeypatch):
    from src import master

    def fake_get(url, params=None, timeout=30):
        secids = params["secids"].split(",")
        diff = [{"f12": c.split(".")[1], "f14": f"銘柄{c.split('.')[1]}"}
                for c in secids if c.endswith(("600000", "300750"))]
        return _FakeResp({"data": {"diff": diff}})

    monkeypatch.setattr(master.time, "sleep", lambda s: None)
    monkeypatch.setattr(master.requests, "Session", lambda: type("S", (), {
        "headers": {}, "get": staticmethod(fake_get)})())
    recs = master.probe_via_ulist()
    got = {r["ticker"]: r for r in recs}
    assert set(got) == {"600000", "300750"}
    assert got["600000"]["exchange"] == "上海"
    assert got["300750"]["exchange"] == "深セン"
