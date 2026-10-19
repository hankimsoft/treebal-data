"""감시가 **정말로 빨개지는지** 확인한다(감시의 감시).

`check_sources.py`는 *"시세를 받는 곳의 모양이 바뀌면 메일이 온다"*는 약속 하나로 존재한다. 그 약속이
깨져 있어도 **아무도 모른다** — 소스는 대개 안 바뀌므로 늘 초록이고, 그게 *"잘 지키고 있다"*와 구분이 안 된다.

⚠️ **실제로 그랬다**(2026-09-08). 200인데 구조가 깨진 경우 코드가 `raise`만 하고 **바깥 `except Exception`이
도로 삼켜** 조용히 통과했다. 주석엔 *"진짜 신호"*라고 적혀 있었는데 **주석이 지키는 건 아무것도 없다.**

네트워크를 안 쓴다 — `requests`와 `time.sleep`을 갈아끼워 **가짜 소스**로 돌린다. 그래서 러너 상태 ·
요청한도와 무관하게 늘 같은 답이 나온다. 시각은 **지금 언저리**로 만든다(감시가 너무 낡은 값도 잡으므로).

    python3 scripts/test_check_sources.py
"""

from __future__ import annotations

import contextlib
import copy
import io
import runpy
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).with_name("check_sources.py")

NOW = datetime.now(timezone.utc)
KST = timezone(timedelta(hours=9))
EDT = timezone(timedelta(hours=-4))


def _iso(at: datetime, tz: timezone, *, millis: bool = False, colon: bool = True) -> str:
    """`2026-10-07T10:40:46+09:00` · CNBC 꼴 `2026-10-06T16:00:00.000-0400`."""
    local = at.astimezone(tz)
    body = local.strftime("%Y-%m-%dT%H:%M:%S") + (".000" if millis else "")
    off = local.strftime("%z")  # +0900
    return body + (off[:3] + ":" + off[3:] if colon else off)


def good() -> dict:
    """앱이 읽는 칸이 다 있고 값도 말이 되는 응답 — 2026-10-07에 맥에서 받아 본 모양 그대로다."""
    hour_ago = NOW - timedelta(hours=1)
    epoch = int(hour_ago.timestamp())
    return {
        "yahoo": {
            "regularMarketPrice": 333.63,
            "regularMarketTime": epoch,  # 초 단위 epoch
            "gmtoffset": -14400,
            "currentTradingPeriod": {"regular": {"start": epoch - 23_400, "end": epoch}},  # 6.5시간
        },
        "naver_kr": {
            "datas": [
                {
                    "itemCode": "005930",
                    "closePriceRaw": "272500",
                    "closePrice": "272,500",
                    "localTradedAt": _iso(hour_ago, KST),
                    "marketStatus": "CLOSE",
                    "currencyType": {"code": "KRW"},
                    "stockExchangeType": {"nationType": "KOR"},
                }
            ]
        },
        "naver_us": {
            "datas": [
                {
                    "reutersCode": "AAPL.O",
                    "closePriceRaw": "333.63",
                    "closePrice": "333.63",
                    "localTradedAt": _iso(hour_ago, EDT),
                    "marketStatus": "CLOSE",
                    "currencyType": {"code": "USD"},
                    "stockExchangeType": {"nationType": "USA"},
                }
            ]
        },
        "naver_gold": {
            "closePrice": "179,460",
            "unit": "원/g",
            "nationType": "KOR",
            "localTradedAt": _iso(hour_ago, KST),
            "marketStatus": "CLOSE",
        },
        "cnbc": {
            "FormattedQuoteResult": {
                "FormattedQuote": [
                    {
                        "symbol": "AAPL",
                        "code": 0,
                        "currencyCode": "USD",
                        "last": "333.63",
                        "last_time": _iso(hour_ago, EDT, millis=True, colon=False),
                        "curmktstatus": "POST_MKT",
                        "timeZone": "EDT",
                    }
                ]
            }
        },
        "upbit": [
            {"market": "KRW-BTC", "trade_price": 115560000.0, "trade_timestamp": int(hour_ago.timestamp() * 1000)}
        ],
        "bithumb": {"status": "0000", "data": {"closing_price": "115616000", "date": str(int(hour_ago.timestamp() * 1000))}},
    }


def route(url: str) -> str:
    if "finance.yahoo.com" in url:
        return "yahoo"
    if "realtime/domestic" in url:
        return "naver_kr"
    if "realtime/worldstock" in url:
        return "naver_us"
    if "marketindex/metals" in url:
        return "naver_gold"
    if "quote.cnbc.com" in url:
        return "cnbc"
    if "api.upbit.com" in url:
        return "upbit"
    if "api.bithumb.com" in url:
        return "bithumb"
    raise AssertionError(f"모르는 주소: {url}")


def run(change=None, *, status: dict | None = None, broken: set | None = None, calls: list | None = None) -> int:
    """가짜 응답으로 감시를 돌리고 **종료 코드**를 돌려준다.

    change(bodies) — 응답을 고친다 · status — 소스별 HTTP 코드 · broken — 200인데 JSON이 아닌 소스 ·
    calls — (소스, 헤더)를 적어 둔다.
    """
    bodies = good()
    if change:
        change(bodies)
    status = status or {}
    broken = broken or set()

    class FakeResponse:
        def __init__(self, name: str):
            self.name = name
            self.status_code = status.get(name, 200)

        def json(self):
            if self.name in broken:
                raise ValueError("JSON이 아니다")
            body = copy.deepcopy(bodies[self.name])
            if self.name == "yahoo":
                return {"chart": {"result": [{"meta": body}]}}
            return body

    def fake_get(url, params=None, headers=None, timeout=None):
        name = route(url)
        if calls is not None:
            calls.append((name, dict(headers or {})))
        if status.get(name) == "offline":
            raise ConnectionError("오프라인")
        return FakeResponse(name)

    fake = types.ModuleType("requests")
    fake.get = fake_get
    sys.modules["requests"] = fake
    real_sleep = time.sleep
    time.sleep = lambda *_: None  # 재시도 · 두 번째 바퀴 대기를 없앤다
    out = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            runpy.run_path(str(SCRIPT), run_name="__main__")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    finally:
        time.sleep = real_sleep
        sys.modules.pop("requests", None)
    return code


def setter(path: str, value):
    """`naver_kr.datas.0.marketStatus` 꼴의 길로 값을 바꾼다(`value`가 `DELETE`면 지운다)."""

    def change(bodies):
        keys = path.split(".")
        node = bodies
        for k in keys[:-1]:
            node = node[int(k)] if isinstance(node, list) else node[k]
        last = keys[-1]
        if value is DELETE:
            del node[last]
        elif isinstance(node, list):
            node[int(last)] = value
        else:
            node[last] = value

    return change


DELETE = object()
OLD = NOW - timedelta(days=30)
HOUR_AGO = NOW - timedelta(hours=1)

# (이름, 돌리는 법, 빨개져야 하나)
CASES = [
    ("모양 그대로", lambda: run(), False),
    # ── 야후(국내 · 미국 · 환율이 같은 엔드포인트) ───────────────────────────────────
    ("야후 regularMarketTime이 밀리초", lambda: run(setter("yahoo.regularMarketTime", int(HOUR_AGO.timestamp() * 1000))), True),
    ("야후 regularMarketPrice 칸이 없다", lambda: run(setter("yahoo.regularMarketPrice", DELETE)), True),
    ("야후 regularMarketTime 칸이 없다", lambda: run(setter("yahoo.regularMarketTime", DELETE)), True),
    ("야후 regularMarketPrice가 문자열", lambda: run(setter("yahoo.regularMarketPrice", "333.63")), True),
    ("야후 regularMarketPrice가 0", lambda: run(setter("yahoo.regularMarketPrice", 0)), True),
    ("야후 gmtoffset이 시차 범위 밖", lambda: run(setter("yahoo.gmtoffset", 999_999)), True),
    ("야후 currentTradingPeriod가 없다", lambda: run(setter("yahoo.currentTradingPeriod", DELETE)), True),
    ("야후 정규장 길이가 이상하다", lambda: run(lambda b: b["yahoo"]["currentTradingPeriod"]["regular"].update(
        end=b["yahoo"]["currentTradingPeriod"]["regular"]["end"] + 200_000)), True),
    ("야후 200인데 구조가 깨졌다", lambda: run(broken={"yahoo"}), True),
    # ── 네이버 국내 · 미국 ────────────────────────────────────────────────────────
    ("네이버 국내 datas가 없다", lambda: run(setter("naver_kr.datas", DELETE)), True),
    ("네이버 국내 물은 코드가 안 왔다", lambda: run(setter("naver_kr.datas", [])), True),
    ("네이버 국내 나라가 바뀌었다", lambda: run(setter("naver_kr.datas.0.stockExchangeType", {"nationType": "KR"})), True),
    ("네이버 국내 통화가 바뀌었다", lambda: run(setter("naver_kr.datas.0.currencyType", {"code": "WON"})), True),
    ("네이버 국내 값이 숫자가 아니다", lambda: run(setter("naver_kr.datas.0.closePriceRaw", "abc")), True),
    ("네이버 국내 시각에 시차가 없다", lambda: run(setter("naver_kr.datas.0.localTradedAt", "2026-10-07T10:40:46")), True),
    ("네이버 국내 시각이 한 달 전이다(얼어붙음)", lambda: run(setter("naver_kr.datas.0.localTradedAt", _iso(OLD, KST))), True),
    ("네이버 국내 장 상태가 모르는 값", lambda: run(setter("naver_kr.datas.0.marketStatus", "PREOPEN")), True),
    ("네이버 미국 꼬리표가 바뀌었다(AAPL.O가 안 온다)", lambda: run(setter("naver_us.datas.0.reutersCode", "AAPL.OQ")), True),
    ("네이버 미국 나라가 바뀌었다", lambda: run(setter("naver_us.datas.0.stockExchangeType", {"nationType": "US"})), True),
    # ── 네이버 금 ─────────────────────────────────────────────────────────────────
    ("네이버 금 단위가 원/돈", lambda: run(setter("naver_gold.unit", "원/돈")), True),
    ("네이버 금 나라가 바뀌었다", lambda: run(setter("naver_gold.nationType", "KR")), True),
    ("네이버 금 값이 0", lambda: run(setter("naver_gold.closePrice", "0")), True),
    # ── CNBC ─────────────────────────────────────────────────────────────────────
    ("CNBC 날짜뿐 + EDT(9월 모양)", lambda: run(setter("cnbc.FormattedQuoteResult.FormattedQuote.0.last_time", HOUR_AGO.astimezone(EDT).strftime("%Y-%m-%d"))), False),
    ("CNBC 날짜뿐인데 시간대가 모르는 이름", lambda: run(lambda b: (
        setter("cnbc.FormattedQuoteResult.FormattedQuote.0.last_time", HOUR_AGO.astimezone(EDT).strftime("%Y-%m-%d"))(b),
        setter("cnbc.FormattedQuoteResult.FormattedQuote.0.timeZone", "XYZ")(b),
    )), True),
    ("CNBC 시각이 읽히지 않는다", lambda: run(setter("cnbc.FormattedQuoteResult.FormattedQuote.0.last_time", "2026-10-06T??")), True),
    ("CNBC 결과 칸이 없다", lambda: run(setter("cnbc.FormattedQuoteResult", DELETE)), True),
    ("CNBC code가 0이 아니다", lambda: run(setter("cnbc.FormattedQuoteResult.FormattedQuote.0.code", 1)), True),
    ("CNBC 통화가 달러가 아니다", lambda: run(setter("cnbc.FormattedQuoteResult.FormattedQuote.0.currencyCode", "JPY")), True),
    ("CNBC 장 상태 칸이 없다", lambda: run(setter("cnbc.FormattedQuoteResult.FormattedQuote.0.curmktstatus", DELETE)), True),
    # ── 업비트 · 빗썸 ─────────────────────────────────────────────────────────────
    ("업비트 시각이 초 단위", lambda: run(setter("upbit.0.trade_timestamp", int(HOUR_AGO.timestamp()))), True),
    ("업비트 값이 숫자가 아니다", lambda: run(setter("upbit.0.trade_price", "x")), True),
    ("업비트 물은 마켓이 안 왔다", lambda: run(setter("upbit.0.market", "KRW-ETH")), True),
    ("업비트 200인데 구조가 깨졌다", lambda: run(broken={"upbit"}), True),
    ("빗썸 상태가 0000이 아니다", lambda: run(setter("bithumb.status", "5500")), True),
    ("빗썸 시각이 초 단위", lambda: run(setter("bithumb.data.date", str(int(HOUR_AGO.timestamp())))), True),
    ("빗썸 값이 NaN", lambda: run(setter("bithumb.data.closing_price", "NaN")), True),
    # ── 못 본 것 — 통과해야 한다(가짜 경보는 진짜 경보보다 나쁘다) ─────────────────
    ("야후 429 요청한도", lambda: run(status={"yahoo": 429}), False),
    ("CNBC 403", lambda: run(status={"cnbc": 403}), False),
    ("네이버 국내 404", lambda: run(status={"naver_kr": 404}), False),
    ("다 503", lambda: run(status={k: 503 for k in ("yahoo", "naver_kr", "naver_us", "naver_gold", "cnbc", "upbit", "bithumb")}), False),
    ("업비트 연결이 안 된다", lambda: run(status={"upbit": "offline"}), False),
]


def headers_case() -> list[str]:
    """**앱과 같은 헤더**를 쓰는가 — CNBC는 브라우저 UA가 없으면 403, 야후는 브라우저 UA면 429다(정반대)."""
    calls: list = []
    run(calls=calls)
    bad = []
    ua = {name: h.get("User-Agent", "") for name, h in calls}
    if "Mozilla" not in ua.get("cnbc", ""):
        bad.append("CNBC에 브라우저 UA가 없다 — 없으면 403이다")
    for name in ("yahoo", "naver_kr", "naver_us", "naver_gold", "upbit", "bithumb"):
        if "Mozilla" in ua.get(name, ""):
            bad.append(f"{name}에 브라우저 UA가 붙었다 — 야후는 그러면 429다 · 앱도 안 붙인다")
    return bad


def main() -> None:
    failed = []
    for name, go, should_fail in CASES:
        code = go()
        ok = (code != 0) == should_fail
        want = "빨강" if should_fail else "초록"
        got = "빨강" if code else "초록"
        print(f"{'  ok  ' if ok else ' FAIL '} {name:36s} 기대 {want} · 실제 {got}")
        if not ok:
            failed.append(name)
    bad = headers_case()
    print(f"{'  ok  ' if not bad else ' FAIL '} {'헤더가 앱과 같다':36s}" + ("" if not bad else " — " + " · ".join(bad)))
    if bad:
        failed.append("헤더")

    if failed:
        sys.exit(f"\n감시가 약속을 안 지킨다 ({len(failed)}개):\n  " + "\n  ".join(failed))
    print(f"\n{len(CASES) + 1}개 모두 약속대로다")


main()
