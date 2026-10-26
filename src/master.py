"""東方財産（EastMoney）の銘柄一覧APIから A株マスタを取得・パースする。

エンドポイント: https://82.push2.eastmoney.com/api/qt/clist/get
fs パラメータで上海A股（m:1+t:2）・科創板（m:1+t:23）・深センA股（m:0+t:6）・
創業板（m:0+t:80）のみを指定し、B股・BSE・ETF/LOF/REIT/優先株/転換社債を除外する。
さらにコード帯のベルトチェックで二重に普通株のみに絞る。

取得失敗時はリポジトリ内のフォールバックスナップショット（data/master.json）を使う。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

log = logging.getLogger("master")

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SNAPSHOT = DATA_DIR / "master.json"

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
PAGE_SIZE = 100  # EastMoney の clist は pz 最大100
# 上海A股・科創板・深センA股・創業板のみ（B股/BSE/ETF 等は含まない）
FS = "m:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80"
FIELDS = "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13,f14,f15,f16,f17,f18,f20,f21,f22,f23,f24,f25,f62,f115,f128,f136,f152"

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


def parse_clist_page(data: dict) -> list[dict]:
    """clist レスポンスの1ページをレコードリストにパースする。"""
    diff = (data.get("data") or {}).get("diff")
    if not diff:
        return []
    records = []
    for fields in diff:
        code = str(fields.get("f12") or "").strip()
        name = str(fields.get("f14") or "").strip()
        if not code or not is_a_share(code):
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
                if code and code != "-" and is_a_share(code) and code not in records:
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

    ダウンロードに成功した場合は data/master.json のスナップショットを差し替える。
    失敗時はスナップショットを使う。スナップショットもなくclistも失敗した場合のみ
    ulist プローブで初回マスタを構成する。
    """
    records = fetch_all() if fetch else None
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
