"""東方財産（EastMoney）の銘柄一覧APIから A株マスタを取得・パースする。

エンドポイント: https://82.push2.eastmoney.com/api/qt/clist/get
fs パラメータで上海A股（m:1+t:2）・科創板（m:1+t:23）・深センA股（m:0+t:6）・
創業板（m:0+t:80）のみを指定し、B股・BSE・ETF/LOF/REIT/優先株/転換社債を除外する。
さらにコード帯のベルトチェックで二重に普通株のみに絞る。

取得失敗時はリポジトリ内のフォールバックスナップショット（data/master.json）を使う。

clist が使えない環境（GitHub Actions の IP を EastMoney が拒否する等）では、
取引所公式の銘柄一覧（SSE の suggest データ・SZSE のレポート API）にフォールバックする。
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import requests

log = logging.getLogger("master")

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SNAPSHOT = DATA_DIR / "master.json"

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
SSE_URL = "https://www.sse.com.cn/js/common/ssesuggestdata.js"
SZSE_URL = "https://www.szse.cn/api/report/ShowReport/data"
SZSE_REFERER = "https://www.szse.cn/market/product/stock/list/index.html"
PAGE_SIZE = 100  # EastMoney の clist は pz 最大100
# 上海A股・科創板・深センA股・創業板のみ（B股/BSE/ETF 等は含まない）
FS = "m:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80"
FIELDS = "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13,f14,f15,f16,f17,f18,f20,f21,f22,f23,f24,f25,f62,f100,f115,f128,f136,f152"

# 明示的に除外するコード帯（spec.md Q3。8xxxxx/4xxxxx/92xxxx=BSE、
# 900=B股(上海)、200=B股(深セン)、15/16=ETF/LOF、50/58=ETF/REIT 等、11/12=転換社債・社債）
EXCLUDED_PREFIXES = ("900", "200", "8", "4", "92", "15", "16", "50", "58", "11", "12")

# clist が使えない環境（接続遮断等）かつスナップショット未生成の初回のみ、
# ulist でコードレンジを総当たりしてマスタを構成するフォールバック用レンジ
PROBE_RANGES = (
    ("600000", "609999"),  # 上海主板
    ("688000", "689999"),  # 科創板
    ("000000", "003999"),  # 深セン主板
    ("300000", "303999"),  # 創業板
)

SHANGHAI = "上海"
SHENZHEN = "深セン"


def sector_of(fields: dict) -> str | None:
    """clist の fields から業種（f100）を取り出す（"-"/空は None）。"""
    sector = (fields or {}).get("f100")
    return str(sector) if sector and sector != "-" else None


def exchange_of(code: str) -> str:
    """コード先頭で取引所を判別（6xxxxx→上海、0xxxxx/3xxxxx→深セン）。"""
    return SHANGHAI if code.startswith("6") else SHENZHEN


def is_a_share(code: str) -> bool:
    """普通A株のコード帯かどうか（6桁数字で、除外コード帯に合致しない）。"""
    if len(code) != 6 or not code.isdigit():
        return False
    if code.startswith(EXCLUDED_PREFIXES):
        return False
    return code[0] in "036"


def is_listed(name: str) -> bool:
    """上場中かどうか（銘柄名に「退」が付くのは上場廃止銘柄のみ）。"""
    return "退" not in name


def parse_clist_page(data: dict) -> list[dict]:
    """clist レスポンスの1ページをレコードリストにパースする。"""
    diff = (data.get("data") or {}).get("diff")
    if not diff:
        return []
    records = []
    for fields in diff:
        code = str(fields.get("f12") or "").strip()
        name = str(fields.get("f14") or "").strip()
        if not code or not is_a_share(code) or not is_listed(name):
            continue
        records.append({
            "ticker": code,
            "name": name,
            "exchange": exchange_of(code),
            "fields": fields,
        })
    return records


def _fetch_page(session: requests.Session, page: int, timeout: int, retries: int = 3) -> list[dict]:
    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries):
        try:
            res = session.get(CLIST_URL, params={
                "pn": page, "pz": PAGE_SIZE, "po": "1", "np": "1",
                "fltt": "2", "invt": "2", "fid": "f12",
                "fs": FS, "fields": FIELDS,
            }, timeout=timeout)
            res.raise_for_status()
            return parse_clist_page(res.json())
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    raise RuntimeError(f"clist ページ {page} 取得失敗: {last}")


def fetch_all(timeout: int = 30) -> list[dict] | None:
    """銘柄一覧を全ページ取得する。失敗時は None。"""
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    records: list[dict] = []
    page = 1
    try:
        while True:
            batch = _fetch_page(session, page, timeout)
            records.extend(batch)
            if len(batch) < PAGE_SIZE:
                return records
            page += 1
            time.sleep(0.3)  # レート制限対策
    except Exception as e:
        log.warning("EastMoney 銘柄一覧 ダウンロード失敗: %s", e)
        return None


def _secid(code: str) -> str:
    return ("1." if code.startswith("6") else "0.") + code


# 取引所公式フォールバック: SSE suggest データの1行
_SSE_ROW = re.compile(r'_t\.push\(\{val:"(\d{6})",val2:"(.*?)"[,}]')
_TAG = re.compile(r"<[^>]*>")


def fetch_sse(timeout: int = 30) -> list[dict] | None:
    """上海証券交易所の公式 suggest データから上海 A株レコードを取得する。"""
    try:
        res = None
        delay = 2.0
        for attempt in range(3):
            try:
                res = requests.get(SSE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
                res.raise_for_status()
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(delay)
                delay *= 2
    except Exception as e:
        log.warning("SSE 銘柄一覧 取得失敗: %s", e)
        return None
    records = []
    for code, name in _SSE_ROW.findall(res.text):
        # 上海の A株は 6xxxxx のみ（36xxxx 優先株・900 B股・5x ETF 等は除外）
        if not (code.startswith("6") and is_a_share(code) and is_listed(name)):
            continue
        records.append({"ticker": code, "name": name, "exchange": SHANGHAI, "fields": {}})
    return records


CNINFO_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"


def fetch_szse(timeout: int = 30) -> list[dict] | None:
    """深セン A株レコードを取得する（第一候補: 巨潮資訊、第二候補: SZSE 公式レポート API）。

    巨潮資訊（cninfo）は SZSE 系の公式開示プラットフォームで海外 IP からも安定して
    取れる。SZSE 公式 API（www.szse.cn）は WAF で海外/クラウド IP を拒否することが
    あるためフォールバックに留める。
    """
    records = _fetch_szse_cninfo(timeout)
    if records is not None:
        return records
    return _fetch_szse_report(timeout)


def _fetch_szse_cninfo(timeout: int = 30) -> list[dict] | None:
    try:
        res = requests.get(CNINFO_URL, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "http://www.cninfo.com.cn/",
        }, timeout=timeout)
        res.raise_for_status()
        stocks = res.json().get("stockList") or []
    except Exception as e:
        log.warning("cninfo 銘柄一覧 取得失敗: %s", e)
        return None
    records = []
    for s in stocks:
        code = str(s.get("code") or "").strip()
        name = str(s.get("zwjc") or "").strip()
        # cninfo のリストは全市場対象のため深セン（0xxxxx/3xxxxx）のみに絞る。
        # 上場廃止銘柄（名前に「退」）は価格が取得できないため除外する
        if s.get("category") != "A股" or code[:1] not in "03" \
                or not (code and name and is_a_share(code) and is_listed(name)):
            continue
        records.append({"ticker": code, "name": name, "exchange": SHENZHEN, "fields": {}})
    return records


def _fetch_szse_report(timeout: int = 30) -> list[dict] | None:
    """SZSE 公式レポート API から深セン A株レコードを全ページ取得する。"""
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": SZSE_REFERER})
    records = []
    page = 1
    try:
        while True:
            payload = None
            delay = 2.0
            for attempt in range(3):
                try:
                    res = session.get(SZSE_URL, params={
                        "SHOWTYPE": "JSON", "CATALOGID": "1110", "TABKEY": "tab1",
                        "PAGENO": page, "random": time.time(),
                    }, timeout=timeout)
                    res.raise_for_status()
                    payload = res.json()[0]
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(delay)
                    delay *= 2
            rows = payload.get("data") or []
            for row in rows:
                code = str(row.get("agdm") or "").strip()
                name = _TAG.sub("", str(row.get("agjc") or "")).strip()
                if not (code and name and is_a_share(code) and is_listed(name)):
                    continue
                records.append({"ticker": code, "name": name, "exchange": SHENZHEN, "fields": {}})
            if page >= int(payload.get("metadata", {}).get("pagecount") or 1):
                return records
            page += 1
            time.sleep(0.3)  # レート制限対策
    except Exception as e:
        log.warning("SZSE 公式レポート 取得失敗: %s", e)
        return None


def fetch_from_exchanges(timeout: int = 30) -> list[dict] | None:
    """取引所公式の銘柄一覧（SSE + SZSE）をまとめて取得する。失敗時は None。"""
    sh = fetch_sse(timeout)
    sz = fetch_szse(timeout)
    if sh is None or sz is None or not sh or not sz:
        return None
    records = sh + sz
    log.info("取引所公式一覧利用: 上海 %s 銘柄 / 深セン %s 銘柄", len(sh), len(sz))
    return records


def probe_via_ulist(timeout: int = 30) -> list[dict] | None:
    """clist が使えずスナップショットも無い初回のフォールバック。

    ulist API で候補コードレンジを100銘柄/回で総当たりし、存在する銘柄を返す。
    """
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    codes: list[str] = []
    for start, end in PROBE_RANGES:
        codes.extend(str(n).zfill(6) for n in range(int(start), int(end) + 1))
    records: dict[str, dict] = {}
    try:
        for i in range(0, len(codes), 100):
            batch = codes[i:i + 100]
            res = session.get("https://push2.eastmoney.com/api/qt/ulist.np/get", params={
                "fltt": "2", "invt": "2", "np": "1",
                "secids": ",".join(_secid(c) for c in batch),
                "fields": "f12,f14",
            }, timeout=timeout)
            res.raise_for_status()
            diff = (res.json().get("data") or {}).get("diff") or []
            for fields in diff:
                code = str(fields.get("f12") or "").strip()
                name = str(fields.get("f14") or "").strip()
                if code and code != "-" and is_a_share(code) and is_listed(name) and code not in records:
                    records[code] = {
                        "ticker": code,
                        "name": str(fields.get("f14") or "").strip(),
                        "exchange": exchange_of(code),
                        "fields": dict(fields),
                    }
            time.sleep(0.3)
    except Exception as e:
        log.warning("ulist プローブ失敗: %s", e)
        return None
    return sorted(records.values(), key=lambda r: r["ticker"])


def load_master(fetch: bool = True) -> list[dict]:
    """普通A株レコードのリストを返す（ticker / name / exchange / fields）。

    取得優先順: EastMoney clist → 取引所公式（SSE/SZSE） → ulist プローブ。
    すべて失敗した場合は data/master.json のスナップショットにフォールバックする。
    ダウンロードに成功した場合はスナップショットを差し替える。
    """
    records = fetch_all() if fetch else None
    if records is None:
        records = fetch_from_exchanges()
    if records is None and not SNAPSHOT.is_file():
        log.info("clist 不可・スナップショットなしのため ulist プローブで初回マスタを構成")
        records = probe_via_ulist()
    if records is None:
        records = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        log.info("フォールバックスナップショット利用: %s 銘柄", len(records))
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        log.info("銘柄一覧: %s 銘柄（フィルタ後）", len(records))
    return records
