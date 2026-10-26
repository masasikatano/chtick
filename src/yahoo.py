"""Yahoo Finance から終値・前日比・出来高を取得する（EastMoney 取得失敗銘柄のフォールバック専用）。

エンドポイント: https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d
上海株は {コード}.SS、深セン株は {コード}.SZ の接尾辞を付ける。

終値・前日比は close 配列の最後の2点から (P_n/P_{n-1}-1)*100 を自前で算出する
（meta.regularMarketChangePercent は使わない）。
出来高は終値と同じ基準日の volume を採用し、最終点が None の場合は直近の有効値にフォールバック
（それも無ければ volume: None。表示は「—」）。

取得失敗した銘柄は戻り値に含めず、呼び出し側で「データなし」とする。
"""

from __future__ import annotations

import logging
import time
from datetime import date

import requests

log = logging.getLogger("yahoo")

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
REQUEST_INTERVAL = 0.1  # フォールバックは失敗銘柄のみなので短めでよい
RETRIES = 3

# Yahoo で取得を除外する銘柄コード（恒常的に失敗する銘柄はここに追加）
YAHOO_EXCLUDE: set[str] = set()

HEADERS = {"User-Agent": "Mozilla/5.0"}


def symbol(code: str) -> str:
    """銘柄コードを Yahoo 形式に変換する（上海=6/688→.SS、深セン=0/3→.SZ）。"""
    return code + (".SS" if code.startswith("6") else ".SZ")


def parse_chart(data: dict) -> dict | None:
    """chart API レスポンスから終値・前日比・出来高・基準日を算出する。

    close 配列の最後の2点から (P_n/P_{n-1}-1)*100 を計算する。
    取得できない場合は None を返す。
    """
    try:
        result = data["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        closes = quote["close"]
        volumes = quote.get("volume")
        timestamps = result["timestamp"]
    except (KeyError, IndexError, TypeError):
        return None
    points = [(ts, c) for ts, c in zip(timestamps, closes) if c is not None]
    if not points:
        return None
    last_ts, last_close = points[-1]
    change_pct = None
    if len(points) >= 2:
        prev = points[-2][1]
        if prev:
            change_pct = round((last_close / prev - 1) * 100, 3)
    volume = None
    if volumes:
        for v in reversed(volumes[:len(points)]):
            if v is not None:
                volume = int(v)
                break
    return {
        "close": float(last_close),
        "change_pct": change_pct,
        "volume": volume,
        "as_of": date.fromtimestamp(last_ts).isoformat(),
    }


def _fetch_one(code: str, session: requests.Session, retries: int = RETRIES) -> dict | None:
    url = CHART_URL.format(symbol=symbol(code))
    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries):
        try:
            res = session.get(url, params={"interval": "1d", "range": "5d"}, timeout=30)
            res.raise_for_status()
            parsed = parse_chart(res.json())
            if parsed is None:
                raise ValueError("no data")
            return parsed
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    log.warning("Yahoo 取得失敗: %s (%s)", code, last)
    return None


def fetch_prices(codes: list[str], session: requests.Session | None = None) -> dict[str, dict]:
    """銘柄コードごとの終値・前日比・出来高を取得する。

    戻り値: { "コード": {"close", "change_pct", "volume", "as_of"}, ... }
    取得失敗・除外銘柄は戻り値に含めない。
    """
    session = session or requests.Session()
    session.headers.update(HEADERS)
    out: dict[str, dict] = {}
    for code in codes:
        if code in YAHOO_EXCLUDE:
            continue
        price = _fetch_one(code, session)
        if price is not None:
            out[code] = price
        time.sleep(REQUEST_INTERVAL)
    log.info("Yahoo Finance（フォールバック）: %s/%s 銘柄の価格を取得", len(out), len(codes))
    return out
