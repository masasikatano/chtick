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


def test_sector_ofはf100を取り出しハイフンや欠損はNone():
    from src.master import sector_of
    assert sector_of({"f100": "银行Ⅱ"}) == "银行Ⅱ"
    assert sector_of({"f100": "-"}) is None
    assert sector_of({}) is None
    assert sector_of(None) is None


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


class _FakeTextResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


SSE_SAMPLE = (
    'var _t = new Array();\n'
    '_t.push({val:"600000",val2:"浦発銀行",val3:"pfyx"});\n'
    '_t.push({val:"688981",val2:"中芯国際",val3:"zxgj"});\n'
    '_t.push({val:"360001",val2:"农行优1",val3:"nxy1"});\n'  # 優先株は除外
    '_t.push({val:"900901",val2:"儀電B股",val3:"ydbg"});\n'  # B股は除外
    '_t.push({val:"510300",val2:"300ETF",val3:"etf"});\n'   # ETFは除外
)


def test_sse公式一覧は上海A株のみ抽出(monkeypatch):
    from src import master

    monkeypatch.setattr(master.requests, "get",
                        lambda *a, **k: _FakeTextResp(SSE_SAMPLE))
    recs = master.fetch_sse()
    assert [r["ticker"] for r in recs] == ["600000", "688981"]
    assert recs[0]["exchange"] == "上海"
    assert recs[0]["name"] == "浦発銀行"


SZSE_PAGE1 = [{
    "metadata": {"pagecount": 2},
    "data": [
        {"agdm": "000001", "agjc": "<a href='x'><u>平安銀行</u></a>"},
        {"agdm": "200002", "agjc": "<a href='x'><u>万  科Ｂ</u></a>"},  # B股は除外
    ],
}]
SZSE_PAGE2 = [{
    "metadata": {"pagecount": 2},
    "data": [
        {"agdm": "300750", "agjc": "<a href='x'><u>寧徳時代</u></a>"},
    ],
}]


def test_szse公式レポートは全ページを深センA株のみ抽出(monkeypatch):
    from src import master

    pages = iter([SZSE_PAGE1, SZSE_PAGE2])

    def fake_get(url, params=None, timeout=30):
        return _FakeResp(next(pages))

    monkeypatch.setattr(master.time, "sleep", lambda s: None)
    monkeypatch.setattr(master.requests, "Session", lambda: type("S", (), {
        "headers": {}, "get": staticmethod(fake_get)})())
    recs = master._fetch_szse_report()
    assert [r["ticker"] for r in recs] == ["000001", "300750"]
    assert recs[0]["exchange"] == "深セン"
    assert recs[0]["name"] == "平安銀行"


CNINFO_SAMPLE = {"stockList": [
    {"code": "000001", "zwjc": "平安银行", "category": "A股"},
    {"code": "200002", "zwjc": "万科B", "category": "B股"},   # B股は除外
    {"code": "300750", "zwjc": "宁德时代", "category": "A股"},
]}


def test_cninfo一覧は深センA株のみ抽出(monkeypatch):
    from src import master

    monkeypatch.setattr(master, "_fetch_szse_report", lambda timeout=30: None)
    monkeypatch.setattr(master.requests, "get",
                        lambda *a, **k: _FakeResp(CNINFO_SAMPLE))
    recs = master.fetch_szse()
    assert [r["ticker"] for r in recs] == ["000001", "300750"]
    assert recs[0]["exchange"] == "深セン"
    assert recs[0]["name"] == "平安银行"


def test_load_masterはclist失敗時に取引所公式にフォールバック(monkeypatch, tmp_path):
    from src import master

    monkeypatch.setattr(master, "fetch_all", lambda: None)
    monkeypatch.setattr(master, "fetch_sse", lambda timeout=30: [
        {"ticker": "600000", "name": "浦発銀行", "exchange": "上海", "fields": {}}])
    monkeypatch.setattr(master, "fetch_szse", lambda timeout=30: [
        {"ticker": "000001", "name": "平安銀行", "exchange": "深セン", "fields": {}}])
    monkeypatch.setattr(master, "SNAPSHOT", tmp_path / "master.json")
    recs = master.load_master()
    assert [r["ticker"] for r in recs] == ["600000", "000001"]
