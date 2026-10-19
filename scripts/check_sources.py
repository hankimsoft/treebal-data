"""앱이 시세를 받는 곳들의 응답이 아직 우리가 아는 모양인지 확인한다. **아니면 실패시킨다.**

(2026-10-07 — `check_yahoo.py`를 넓혔다. 2026-09-05에 야후 앞에 소스 다섯(네이버 국내 · 미국 · 금 · CNBC ·
업비트)과 코인 예비(빗썸)를 붙이면서 **감시는 야후에 머물렀다.** 넓히자마자 하나가 걸렸다 — CNBC가 `last_time`을
날짜뿐(`2026-09-04`)에서 시각까지(`2026-10-06T16:00:00.000-0400`)로 바꿔, 앱이 그 사이 CNBC 값을 **전부 버리고**
있었다. 같은 자리의 네이버가 받아 화면엔 티가 안 났다 — **이런 걸 알려고 이 파일이 있다.**)

앱은 **오프라인이라 서버 로그가 없다.** 소스가 모양을 바꿔도 앱은 값을 버리고 다음 소스로 넘어갈 뿐이라
(느려지거나 · 금이면 어제 종가로) **아무도 모른다.** 여기가 빨개지면 GitHub이 메일을 보낸다. 그때
`project_docs/reference/quote_sources.md`(야후는 `yahoo_chart_response.md`)를 열어 **다시 관찰하고 문서를
고친 뒤** 앱을 손보면 된다.

⚠️ **값이 맞는지는 안 본다** — 매일 달라진다. 보는 건 **앱이 읽는 칸**과 그 값이 **말이 되는지**(타입 · 부호 ·
단위 · 시각이 지금 언저리인가)뿐이다. 칸 이름이 그대로여도 단위가 바뀌면 조용히 망가진다(야후 시각이 초 →
밀리초면 서기 5만년이 되어 그 종목이 얼어붙는다).

⚠️ **종목 목록 · 종가와 아무 상관이 없다.** 이건 앱이 쓰는 남의 API를 지켜보는 것뿐이고 `docs/` 아래 파일은
건드리지 않는다.

## ⚠️ **못 본 것과 바뀐 것은 다르다** (2026-09-04, 야후 첫 실행에서 배웠다)

| | 어떻게 |
|---|---|
| **못 봤다**(429 · 403 · 연결 실패 · 5xx) | 알리고 **통과**시킨다. 내일 또 본다 — 러너 IP가 막힌 것일 수 있다 |
| **모양이 다르다**(칸 · 타입 · 단위 · 시각) | **실패시킨다** → 메일이 온다 |
| **200인데 구조가 깨졌다** | **실패시킨다** — 이것도 바뀐 것이다([Malformed]) |

가짜 경보는 진짜 경보보다 나쁘다 — 메일을 무시하게 된다. ⚠️ 마지막 줄은 2026-09-08까지 구멍이었다
(`raise`를 바깥 `except Exception`이 도로 삼켰다). 지금은 [Malformed]로 갈라 두고 `test_check_sources.py`가 붙든다.

⚠️ **먼저 묻는 쪽이 손해다** — 한도는 잠깐 쉬면 풀려서, 한 바퀴 돈 뒤 **못 본 것만 한 번 더** 묻는다.

⚠️ **소스가 아홉이라 하나쯤 막히는 날이 잦다.** 매일 노란 줄이 뜨면 무시하게 되므로, **며칠 내리 같은 쪽만
못 보면** 그때 손으로 확인한다.
"""

from __future__ import annotations

import math
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

# ── 앱과 짝 ────────────────────────────────────────────────────────────────────────────────────
# 앱이 시세를 받는 곳(`lib/providers/quote_providers.dart`)과 **짝**이다 — **앱에 소스를 더하면 여기도 더한다.**
# 이번에 감시가 야후에 머문 게 바로 그 빈틈이었다. 앱 저장소의 `test/services/source_watch_test.dart`가
# 앱의 소스 목록과 이 두 묶음을 견준다(어느 쪽에도 없는 소스가 생기면 빨갛다).
WATCHED = {
    "YahooQuoteSource.krx": "야후 · 국내(뒷층)",
    "YahooQuoteSource.us": "야후 · 미국(뒷층)",
    "YahooExchangeRateSource": "야후 · 환율(같은 엔드포인트)",
    "NaverQuoteSource.krx": "네이버 · 국내",
    "NaverQuoteSource.us": "네이버 · 미국",
    "NaverGoldQuoteSource": "네이버 · 금",
    "CnbcQuoteSource": "CNBC · 미국",
    "UpbitQuoteSource": "업비트 · 코인",
    "BithumbQuoteSource": "빗썸 · 코인(뒷층)",
}
NOT_WATCHED = {
    "KrxStaticQuoteSource": "우리 파일 — 만드는 쪽(`update.yml`)이 곧 감시다",
}

# ── 헤더 — **소스마다 앱과 같게** ───────────────────────────────────────────────────────────────
# ⚠️ **공용 상수 하나로 뽑지 말 것**(앱 CLAUDE.md와 같은 규칙). 야후는 **브라우저 UA면 429**이고 CNBC는
# **브라우저 UA가 없으면 403**이다 — 정반대다.
#
# 야후 실측(2026-09-05, 맥, 각 3~5회): 429 — curl · python-requests · python-urllib · Go-http-client · 데스크톱
# Chrome · (UA 없음) / 200 — Dart(dart:io) · okhttp · 아무 이름이나. 즉 **알려진 도구 이름만 막는다.**
# 앱은 Dart 기본 UA라 원래 안 걸리고, 여기선 하는 일(`quote-check`)만 밝힌 이름을 쓴다(앱 · 서비스 이름은 안 넣는다).
# 네이버 · 업비트 · 빗썸도 앱이 헤더를 안 붙인다 — 같은 이름으로 묻는다.
YAHOO_HEADERS = {"User-Agent": "quote-check/1.0", "Accept": "application/json"}
NAVER_HEADERS = {"User-Agent": "quote-check/1.0", "Accept": "application/json"}
UPBIT_HEADERS = {"User-Agent": "quote-check/1.0", "Accept": "application/json"}
BITHUMB_HEADERS = {"User-Agent": "quote-check/1.0", "Accept": "application/json"}
# 앱(`lib/services/cnbc_quote_source.dart`)과 **같은 문자열**이다 — 없으면 한 건도 못 받는다.
CNBC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36",
}

# ── 말이 되는 값 ─────────────────────────────────────────────────────────────────────────────────
SANE_FROM = datetime(2000, 1, 1, tzinfo=timezone.utc)
SANE_TO = datetime(2100, 1, 1, tzinfo=timezone.utc)
# 시각이 **이보다 낡았으면** 얼어붙은 것이다. 주식은 연휴(추석 · 설)를 넘겨야 해서 넉넉히, 코인은 24시간 장이다.
STALE_STOCK = timedelta(days=14)
STALE_COIN = timedelta(days=3)
# 앱의 `sensibleAsOf`와 같다 — 이틀 넘는 미래는 말이 안 된다.
FUTURE = timedelta(days=2)


def _number(v) -> float | None:
    """앱의 `looseNumber`와 같다 — 숫자거나 콤마 섞인 숫자 문자열 · **끝이 있는 수**만."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        n = float(v)
    elif isinstance(v, str):
        try:
            n = float(v.replace(",", ""))
        except ValueError:
            return None
    else:
        return None
    return n if math.isfinite(n) else None


def _positive(v) -> str | None:
    n = _number(v)
    if n is None:
        return f"숫자가 아니다({v!r:.20})"
    return None if n > 0 else "0 이하다"


_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})$"
)


def _parse_iso(s: str) -> datetime | None:
    """`2026-10-07T10:40:46.429984+09:00` · `2026-10-06T16:00:00.000-0400` · `…Z`. **시차가 없으면 None.**

    파이썬 버전마다 `fromisoformat`이 받는 꼴이 달라(3.9는 `-0400`을 못 읽는다) 직접 읽는다 — 앱(Dart의
    `DateTime.tryParse`)이 받는 꼴과 맞춘다.
    """
    m = _ISO.match(s)
    if not m:
        return None
    y, mo, d, h, mi, se, frac, off = m.groups()
    if off == "Z":
        tz = timezone.utc
    else:
        sign = 1 if off[0] == "+" else -1
        digits = off[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
    micro = int((frac or "0")[:6].ljust(6, "0"))
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(se), micro, tzinfo=tz)
    except ValueError:
        return None


def _recent(at: datetime, stale: timedelta) -> str | None:
    now = datetime.now(timezone.utc)
    if not (SANE_FROM <= at <= SANE_TO):
        return f"말이 안 되는 시각이다({at.isoformat()})"
    if at > now + FUTURE:
        return f"미래다({at.isoformat()})"
    if at < now - stale:
        return f"너무 낡았다 — 얼어붙었나({at.isoformat()})"
    return None


def _iso_recent(v, stale: timedelta = STALE_STOCK) -> str | None:
    if not isinstance(v, str):
        return f"문자열이 아니다({type(v).__name__})"
    at = _parse_iso(v)
    if at is None:
        return f"시차 붙은 시각이 아니다({v!r:.40})"
    return _recent(at, stale)


def _millis_recent(v, stale: timedelta = STALE_COIN) -> str | None:
    """밀리초 epoch(숫자 · 숫자 문자열). **초로 바뀌면 1970년**이 되어 여기서 걸린다."""
    if isinstance(v, str) and v.isdigit():
        v = int(v)
    if not isinstance(v, int) or isinstance(v, bool):
        return f"정수가 아니다({type(v).__name__})"
    return _recent(datetime.fromtimestamp(v / 1000, tz=timezone.utc), stale)


# ── 받기 ─────────────────────────────────────────────────────────────────────────────────────────
TIMEOUT = 15
# 야후는 두 호스트를 번갈아 세 번(`query1 → query2 → query1`) — 한쪽만 막히는 일이 있다.
# 나머지는 두 번이면 된다. ⚠️ **더 늘리면 워크플로 타임아웃(20분)에 걸린다** — 타임아웃은 빨간 X라
# 못 본 것을 알리려다 **가짜 경보**를 만드는 꼴이다. 지금은 최악이 15분쯤이다.
RETRIES = 2
YAHOO_RETRIES = 3
RETRY_PAUSES = [10, 30]
SECOND_ROUND_PAUSE = 60


class Unseen(Exception):
    """**못 봤다.** 소스가 바뀐 게 아니라 우리가 못 본 것이다 — 실패로 치지 않는다."""


class Malformed(Exception):
    """**200인데 우리가 아는 구조가 아니다.** 진짜 신호다 — 실패시킨다.

    ⚠️ [Unseen]과 **반드시 갈라야 한다**(2026-09-08). 바깥 `except Exception`이 이걸 삼키면 *"못 봤다"*가 되어
    엔드포인트가 통째로 바뀌어도 메일이 안 온다."""


def get_json(urls: list[str], headers: dict, *, params: dict | None = None, retries: int = RETRIES):
    """`urls`를 번갈아 물어 JSON을 돌려준다. 못 보면 [Unseen] · 200인데 JSON이 아니면 [Malformed]."""
    last = ""
    for attempt in range(1, retries + 1):
        url = urls[(attempt - 1) % len(urls)]
        host = url.split("/")[2]
        try:
            r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
            if r.status_code == 200:
                try:
                    return r.json()
                except Exception as e:
                    raise Malformed(f"200인데 JSON이 아니다({type(e).__name__})") from e
            last = f"HTTP {r.status_code} ({host})"
        except Malformed:
            # ⚠️ **다시 던진다** — 아래 `except Exception`이 잡으면 *"못 봤다"*가 된다(2026-09-08 구멍).
            raise
        except Exception as e:
            last = f"{type(e).__name__} ({host})"
        if attempt < retries:
            pause = RETRY_PAUSES[attempt - 1]
            print(f"  {last} — {pause}초 뒤 다시")
            time.sleep(pause)
    raise Unseen(last)


def dig(body, *path):
    """`body[path0][path1]…`. 없으면 [Malformed] — 200인데 구조가 다르다."""
    node = body
    for key in path:
        try:
            node = node[key]
        except Exception as e:
            raise Malformed(f"200인데 `{'.'.join(map(str, path))}`를 못 찾는다({type(e).__name__})") from e
    return node


def need(bad: list[str], row: dict, key: str, check) -> None:
    if not isinstance(row, dict) or key not in row:
        bad.append(f"{key}: 칸이 없다")
        return
    why = check(row[key])
    if why:
        bad.append(f"{key}: {why}")


# ── 야후 — `lib/services/yahoo_chart.dart` · `reference/yahoo_chart_response.md` ─────────────────
YAHOO_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
YAHOO_PARAMS = {"range": "5d", "interval": "1d"}


def _epoch_seconds(v) -> str | None:
    if not isinstance(v, int) or isinstance(v, bool):
        return f"정수가 아니다({type(v).__name__})"
    if not (int(SANE_FROM.timestamp()) <= v <= int(SANE_TO.timestamp())):
        return f"초 단위 epoch가 아니다(자릿수 {len(str(abs(v)))})"  # 밀리초로 바뀌면 여기 걸린다
    return None


def _utc_offset(v) -> str | None:
    if not isinstance(v, int) or isinstance(v, bool):
        return f"정수가 아니다({type(v).__name__})"
    return None if -50_400 <= v <= 50_400 else "시차 범위 밖이다"  # 지구에 ±14시간 밖의 시간대는 없다


def yahoo(symbol: str):
    def check() -> list[str]:
        body = get_json(
            [f"https://{h}/v8/finance/chart/{symbol}" for h in YAHOO_HOSTS],
            YAHOO_HEADERS,
            params=YAHOO_PARAMS,
            retries=YAHOO_RETRIES,
        )
        meta = dig(body, "chart", "result", 0, "meta")
        bad: list[str] = []
        need(bad, meta, "regularMarketPrice", lambda v: _positive(v) if isinstance(v, (int, float)) else f"숫자가 아니다({type(v).__name__})")
        need(bad, meta, "regularMarketTime", _epoch_seconds)
        need(bad, meta, "gmtoffset", _utc_offset)
        # `currentTradingPeriod.regular`가 있어야 **종가인지 현재가인지**를 가른다.
        regular = (meta.get("currentTradingPeriod") or {}).get("regular")
        if not isinstance(regular, dict):
            bad.append("currentTradingPeriod.regular: 없거나 모양이 다르다")
        else:
            span_ok = True
            for key in ("start", "end"):
                why = _epoch_seconds(regular.get(key))
                if why:
                    bad.append(f"currentTradingPeriod.regular.{key}: {why}")
                    span_ok = False
            # 한 시간보다 짧거나 하루보다 길면 이상하다(정확한 길이는 시장마다 다르다 — 환율은 거의 하루다).
            if span_ok and not (3_600 <= regular["end"] - regular["start"] <= 86_400):
                bad.append(f"정규장 길이가 이상하다({regular['end'] - regular['start']}초)")
        return bad

    return check


# ── 네이버 국내 · 미국 — `lib/services/naver_quote_source.dart` ───────────────────────────────────
NAVER_STATUS = {"OPEN", "CLOSE"}  # 앱은 이 둘만 안다 — 그 밖이면 `종가`/`현재가`를 못 가른다


def naver(path: str, ask: str, key_field: str, currency: str, nation: str):
    def check() -> list[str]:
        body = get_json([f"https://polling.finance.naver.com/api/realtime/{path}/stock/{ask}"], NAVER_HEADERS)
        rows = dig(body, "datas")
        if not isinstance(rows, list):
            raise Malformed("200인데 `datas`가 목록이 아니다")
        row = next((r for r in rows if isinstance(r, dict) and r.get(key_field) == ask), None)
        if row is None:
            # 오래 상장돼 있고 없어질 일이 없는 종목이다 — 안 오면 꼬리표 · 칸 이름이 바뀐 것이다.
            return [f"물은 `{ask}`가 `{key_field}`로 안 왔다"]
        bad: list[str] = []
        price = row.get("closePriceRaw", row.get("closePrice"))
        if price is None:
            bad.append("closePriceRaw · closePrice: 칸이 없다")
        elif _positive(price):
            bad.append(f"closePriceRaw: {_positive(price)}")
        need(bad, row, "localTradedAt", _iso_recent)
        need(bad, row, "marketStatus", lambda v: None if v in NAVER_STATUS else f"모르는 값이다({v!r})")
        # ⚠️ **통화와 나라를 둘 다** 본다 — 앱이 둘 다 맞아야 받는다(아니면 `못 받는 곳`으로 버리고 뒷층으로 간다).
        need(bad, row, "currencyType", lambda v: None if isinstance(v, dict) and v.get("code") == currency else f"통화가 {currency}가 아니다({v!r:.40})")
        need(bad, row, "stockExchangeType", lambda v: None if isinstance(v, dict) and v.get("nationType") == nation else f"나라가 {nation}가 아니다({v!r:.40})")
        return bad

    return check


# ── 네이버 금 — `lib/services/naver_gold_quote_source.dart` ───────────────────────────────────────
def naver_gold() -> list[str]:
    body = get_json(["https://api.stock.naver.com/marketindex/metals/M04020000"], NAVER_HEADERS)
    if not isinstance(body, dict):
        raise Malformed("200인데 객체가 아니다")
    bad: list[str] = []
    # ⚠️ 단위가 바뀌면 값이 3.75배 틀린다 — 앱은 `원/g`가 아니면 버리고 우리 파일(어제 종가)로 간다.
    need(bad, body, "unit", lambda v: None if v == "원/g" else f"`원/g`가 아니다({v!r})")
    need(bad, body, "nationType", lambda v: None if v == "KOR" else f"KOR가 아니다({v!r})")
    need(bad, body, "closePrice", _positive)
    need(bad, body, "localTradedAt", _iso_recent)
    need(bad, body, "marketStatus", lambda v: None if v in NAVER_STATUS else f"모르는 값이다({v!r})")
    return bad


# ── CNBC — `lib/services/cnbc_quote_source.dart` ─────────────────────────────────────────────────
CNBC_ZONES = {"EDT", "EST"}  # 날짜뿐일 때 앱이 시차를 붙이는 이름 — 그 밖이면 버린다


def cnbc() -> list[str]:
    body = get_json(
        ["https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"],
        CNBC_HEADERS,
        params={"symbols": "AAPL", "output": "json"},
    )
    rows = dig(body, "FormattedQuoteResult", "FormattedQuote")
    if not isinstance(rows, list):
        raise Malformed("200인데 `FormattedQuote`가 목록이 아니다")
    row = next((r for r in rows if isinstance(r, dict) and r.get("symbol") == "AAPL"), None)
    if row is None:
        return ["물은 `AAPL`이 안 왔다"]
    bad: list[str] = []
    need(bad, row, "code", lambda v: None if v == 0 else f"0이 아니다({v!r}) — 1은 없는 코드 · 3은 다른 시장")
    need(bad, row, "currencyCode", lambda v: None if v == "USD" else f"USD가 아니다({v!r})")
    need(bad, row, "last", _positive)  # 정규장 값(시간외는 `ExtendedMktQuote`에 따로 있다)
    need(bad, row, "curmktstatus", lambda v: None if isinstance(v, str) else f"문자열이 아니다({type(v).__name__})")
    # `last_time`은 **두 모양**이다 — 날짜뿐(`2026-09-04` · 9월 5일) · 시각까지(`2026-10-06T16:00:00.000-0400` · 10월 7일).
    # 앱이 둘 다 받는다. 날짜뿐이면 앱이 `timeZone`으로 시차를 붙이므로 그것도 본다.
    day = row.get("last_time")
    if not isinstance(day, str):
        bad.append(f"last_time: 문자열이 아니다({type(day).__name__})")
    elif len(day) == 10:
        try:
            when = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            why = _recent(when, STALE_STOCK)
            if why:
                bad.append(f"last_time: {why}")
        except ValueError:
            bad.append(f"last_time: 날짜가 아니다({day!r})")
        if row.get("curmktstatus") != "REG_MKT":
            need(bad, row, "timeZone", lambda v: None if v in CNBC_ZONES else f"모르는 시간대다({v!r}) — 앱이 버린다")
    else:
        why = _iso_recent(day)
        if why:
            bad.append(f"last_time: {why}")
    return bad


# ── 업비트 · 빗썸 — `lib/services/upbit_quote_source.dart` · `bithumb_quote_source.dart` ──────────
def upbit() -> list[str]:
    body = get_json(["https://api.upbit.com/v1/ticker"], UPBIT_HEADERS, params={"markets": "KRW-BTC"})
    if not isinstance(body, list):
        raise Malformed("200인데 목록이 아니다")
    row = next((r for r in body if isinstance(r, dict) and r.get("market") == "KRW-BTC"), None)
    if row is None:
        return ["물은 `KRW-BTC`가 `market`으로 안 왔다"]
    bad: list[str] = []
    need(bad, row, "trade_price", _positive)
    need(bad, row, "trade_timestamp", _millis_recent)
    return bad


def bithumb() -> list[str]:
    body = get_json(["https://api.bithumb.com/public/ticker/BTC_KRW"], BITHUMB_HEADERS)
    if not isinstance(body, dict):
        raise Malformed("200인데 객체가 아니다")
    bad: list[str] = []
    # ⚠️ **실패도 HTTP 200**으로 온다 — `status`가 `0000`이어야 성공이다.
    need(bad, body, "status", lambda v: None if v == "0000" else f"0000이 아니다({v!r})")
    data = body.get("data")
    if not isinstance(data, dict):
        bad.append("data: 없거나 객체가 아니다")
        return bad
    need(bad, data, "closing_price", _positive)
    need(bad, data, "date", _millis_recent)
    return bad


# 국내 · 미국 · 환율 · 금 · 코인을 **다** 본다 — 한쪽만 바뀔 수 있다. 오래 상장돼 있고 없어질 일이 없는 것으로 고른다.
CHECKS = [
    ("야후 · 국내(005930.KS)", yahoo("005930.KS")),
    ("야후 · 미국(AAPL)", yahoo("AAPL")),
    ("야후 · 환율(USDKRW=X)", yahoo("USDKRW=X")),
    ("네이버 · 국내(005930)", naver("domestic", "005930", "itemCode", "KRW", "KOR")),
    ("네이버 · 미국(AAPL.O)", naver("worldstock", "AAPL.O", "reutersCode", "USD", "USA")),
    ("네이버 · 금(04020000)", naver_gold),
    ("CNBC · 미국(AAPL)", cnbc),
    ("업비트(KRW-BTC)", upbit),
    ("빗썸(BTC_KRW)", bithumb),
]


def main() -> None:
    problems: list[str] = []
    pending = list(CHECKS)
    unseen: list[str] = []
    for round_no in (1, 2):
        if not pending:
            break
        if round_no == 2:
            print(f"\n못 본 것을 한 번 더 — {SECOND_ROUND_PAUSE}초 쉬고")
            time.sleep(SECOND_ROUND_PAUSE)
        still = []
        unseen = []
        for label, check in pending:
            try:
                bad = check()
                problems += [f"{label}: {b}" for b in bad]
                print(f"{label}: 이상 {len(bad)}개")
            except Malformed as e:
                # 다시 물어볼 게 아니다 — 소스가 바뀐 것이다.
                problems.append(f"{label}: {e}")
                print(f"{label}: {e}")
            except Unseen as e:
                still.append((label, check))
                unseen.append(f"{label} — {e}")
        pending = still

    if problems:
        # 칸 이름과 까닭만 찍는다 — 값을 길게 남기지 않는다.
        sys.exit(
            "시세를 받는 곳의 응답이 우리가 아는 모양과 다르다:\n  "
            + "\n  ".join(problems)
            + "\n\n→ project_docs/reference/quote_sources.md(야후는 yahoo_chart_response.md)를 열어 다시 관찰하고,"
            "\n  문서를 고친 뒤 앱(lib/services/)을 손볼 것. 앱은 그동안 그 소스를 버리고 다음 소스로 넘어가고 있다."
        )

    if unseen:
        # ⚠️ **실패시키지 않는다.** 못 본 것은 바뀐 것이 아니다.
        print("\n⚠️ 못 본 것:\n  " + "\n  ".join(unseen))
        print("   러너 IP가 막힌 것일 수 있다 — 앱은 폰에서 부르므로 영향이 없다.")
        print("   내일 또 본다. **며칠 내리 같은 쪽만 못 보면** 그땐 손으로 확인할 것.")
        if len(unseen) < len(CHECKS):
            # 반만 봤으면 **반만 봤다고** 말한다. `그대로다`라고 하면 다 본 줄 안다.
            print("\n본 것은 모양 그대로다")
        return

    print("\n시세를 받는 곳 모두 모양 그대로다")


main()
