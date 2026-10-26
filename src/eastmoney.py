"""東方財産（EastMoney）の quote API から終値・前日比・出来高・時価総額・業種を取得する（主データソース）。

エンドポイント: https://push2.eastmoney.com/api/qt/ulist.np/get
secids パラメータで「市場.コード」をカンマ区切りで最大100銘柄/リクエストでバッチ取得する。
市場 prefix は 1.=上海、0.=深セン。

終値は f2（当日終値、市場クローズ後は確定値）、前日終値は f18、
出来高は f5、時価総額は f20（latest.json のみ保持）、業種は f100。
前日比は (f2/f18-1)*100 を自前で算出する。

取得失敗した銘柄は戻り値に含めず、呼び出し側で Yahoo →「データなし」とする。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("eastmoney")

ULIST_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
BATCH = 100
RETRIES = 3
REQUEST_INTERVAL = 0.3  # リクエスト間の間隔（秒）
CST = ZoneInfo("Asia/Shanghai")

UT = "fa5fd1943c7b386f172d6893dbfba10b"  # EastMoney が公開画面で使う固定トークン
FIELDS = "f2,f5,f12,f14,f18,f20,f100"

# EastMoney で取得を除外する銘柄コード（恒常的に失敗する銘柄はここに追加）
EASTMONEY_EXCLUDE: set[str] = set()

HEADERS = {"User-Agent": "Mozilla/5.0"}


def secid(code: str) -> str:
    """銘柄コードを secid（市場.コード）に変換する（6/688→1.=上海、0/3→0.=深セン）。"""
    return ("1." if code.startswith("6") else "0.") + code


def parse_quote(fields: dict, as_of: str) -> dict | None:
    """ulist レスポンスの1銘柄分から終値・前日比・出来高・時価総額・業種を算出する。

    f2 が数値でない（"-" 等、取得不可）は None を返す。
    前日比は (f2/f18-1)*100 を自前計算する（f18 が無効なら None）。
    """
    try:
        close = float(fields["f2"])
    except (KeyError, TypeError, ValueError):
        return None
    prev = fields.get("f18")
    change_pct = None
    try:
        prev_f = float(prev)
        if prev_f:
            change_pct = round((close / prev_f - 1) * 100, 3)
    except (TypeError, ValueError):
        pass
    volume = fields.get("f5")
    market_cap = fields.get("f20")
    sector = fields.get("f100")
    return {
        "close": close,
        "change_pct": change_pct,
        "volume": int(volume) if isinstance(volume, (int, float)) else None,
        "market_cap": int(market_cap) if isinstance(market_cap, (int, float)) else None,
        "sector": str(sector) if sector and sector != "-" else None,
        "as_of": as_of,
    }


def _fetch_batch(ids: list[str], session: requests.Session, retries: int = RETRIES) -> list[dict]:
    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries):
        try:
            res = session.get(ULIST_URL, params={
                "fltt": "2", "invt": "2", "np": "1", "ut": UT,
                "secids": ",".join(ids), "fields": FIELDS,
            }, timeout=30)
            res.raise_for_status()
            data = res.json()
            diff = (data.get("data") or {}).get("diff") or []
            return diff if isinstance(diff, list) else [diff]
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    log.warning("EastMoney バッチ取得失敗（%s 銘柄）: %s", len(ids), last)
    return []


def fetch_prices(codes: list[str], session: requests.Session | None = None) -> dict[str, dict]:
    """銘柄コードごとの終値・前日比・出来高・時価総額・業種を取得する。

    戻り値: { "コード": {"close", "change_pct", "volume", "market_cap", "sector", "as_of"}, ... }
    取得失敗・除外銘柄は戻り値に含めない（呼び出し側で Yahoo →「データなし」扱い）。
    """
    session = session or requests.Session()
    session.headers.update(HEADERS)
    as_of = datetime.now(CST).date().isoformat()
    targets = [c for c in codes if c not in EASTMONEY_EXCLUDE]
    out: dict[str, dict] = {}
    for i in range(0, len(targets), BATCH):
        batch = targets[i:i + BATCH]
        diff = _fetch_batch([secid(c) for c in batch], session)
        got: set[str] = set()
        for fields in diff:
            code = str(fields.get("f12") or "").strip()
            if not code or code in got:
                continue
            parsed = parse_quote(fields, as_of)
            if parsed is not None:
                out[code] = parsed
                got.add(code)
        missing = [c for c in batch if c not in got]
        if missing:
            log.info("EastMoney 未取得 %s/%s 銘柄（Yahoo フォールバックへ）", len(missing), len(batch))
        time.sleep(REQUEST_INTERVAL)
    with_sector = sum(1 for p in out.values() if p.get("sector"))
    log.info("EastMoney: %s/%s 銘柄の価格を取得（業種付き %s）", len(out), len(targets), with_sector)
    return out
