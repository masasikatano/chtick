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
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests

log = logging.getLogger("yahoo")

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
REQUEST_INTERVAL = 0.1  # フォールバックは失敗銘柄のみなので短めでよい
MAX_WORKERS = 8
RETRIES = 3

# Yahoo で取得を除外する銘柄コード（恒常的に失敗する銘柄はここに追加）。
# 上場廃止銘柄は Yahoo が恒常的に 404 を返すため、リクエスト自体を省略する
#（2026-10-26 の run で 404 が確認されたコード）。
YAHOO_EXCLUDE: set[str] = {
    "000003", "000004", "000005", "000013", "000015", "000016", "000018",
    "000022", "000023", "000024", "000033", "000038", "000040", "000043",
    "000046", "000047", "000150", "000405", "000406", "000412", "000413",
    "000416", "000418", "000502", "000508", "000511", "000515", "000522",
    "000527", "000535", "000540", "000542", "000549", "000556", "000562",
    "000569", "000578", "000583", "000584", "000585", "000587", "000588",
    "000594", "000602", "000606", "000611", "000613", "000616", "000618",
    "000621", "000622", "000627", "000638", "000653", "000658", "000660",
    "000662", "000666", "000667", "000671", "000673", "000675", "000687",
    "000689", "000693", "000699", "000730", "000732", "000748", "000760",
    "000763", "000765", "000769", "000780", "000787", "000805", "000806",
    "000817", "000827", "000832", "000835", "000836", "000851", "000861",
    "000866", "000916", "000918", "000939", "000956", "000961", "000971",
    "000976", "000979", "000982", "000996",
    "001235", "001381",
    "002002", "002013", "002018", "002070", "002071", "002087", "002089",
    "002113", "002118", "002143", "002147", "002220", "002231", "002257",
    "002260", "002280", "002288", "002308", "002325", "002336", "002341",
    "002359", "002411", "002417", "002433", "002435", "002447", "002450",
    "002464", "002473", "002477", "002499", "002502", "002503", "002504",
    "002505", "002509", "002525", "002604", "002610", "002618", "002619",
    "002621", "002665", "002680", "002684", "002699", "002710", "002711",
    "002720", "002740", "002750", "002751", "002770", "002776", "002781",
    "002808", "002898",
    "300023", "300028", "300029", "300038", "300064", "300089", "300090",
    "300104", "300108", "300114", "300116", "300117", "300156", "300178",
    "300186", "300202", "300208", "300216", "300262", "300273", "300280",
    "300282", "300297", "300309", "300312", "300325", "300330", "300336",
    "300344", "300356", "300362", "300367", "300372", "300379", "300391",
    "300392", "300431", "300495", "300526", "300630", "300728", "300742",
    "300799",
}

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


def _fetch_one(code: str, session: requests.Session | None = None, retries: int = RETRIES) -> dict | None:
    session = session or requests.Session()
    session.headers.update(HEADERS)
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
            # 4xx（404 等）はリトライしても変わらないので即諦める
            if isinstance(e, requests.HTTPError) and e.response is not None \
                    and e.response.status_code < 500:
                break
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
    log.warning("Yahoo 取得失敗: %s (%s)", code, last)
    return None


def fetch_prices(codes: list[str], session: requests.Session | None = None) -> dict[str, dict]:
    """銘柄コードごとの終値・前日比・出来高を取得する。

    戻り値: { "コード": {"close", "change_pct", "volume", "as_of"}, ... }
    取得失敗・除外銘柄は戻り値に含めない。
    session は互換用に残しているが、並列ワーカーではスレッドごとにセッションを作る
    （requests.Session はスレッドセーフではない）。
    """
    targets = [c for c in codes if c not in YAHOO_EXCLUDE]
    out: dict[str, dict] = {}
    # セッションはスレッド間で共有しない
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for code, price in zip(targets, pool.map(_fetch_one, targets)):
            if price is not None:
                out[code] = price
            time.sleep(REQUEST_INTERVAL)
    log.info("Yahoo Finance（フォールバック）: %s/%s 銘柄の価格を取得", len(out), len(codes))
    return out
