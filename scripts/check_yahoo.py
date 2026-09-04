"""야후 응답이 아직 우리가 아는 모양인지 확인한다. **아니면 실패시킨다.**

앱은 야후의 **비공식 API**에 기대고 있다(`lib/services/yahoo_chart.dart`).
공식 문서가 없어 예고 없이 바뀔 수 있는데, 앱은 **오프라인이라 서버 로그가 없다** —
바뀌어도 조용히 덜 정확해질 뿐 아무도 모른다. 사용자에게 *"야후 응답이 바뀌었어요"*라고
말해봐야 할 수 있는 일도 없다. 그래서 **여기서 감시한다.**

여기가 빨개지면 GitHub이 메일을 보낸다. 그때 `project_docs/reference/yahoo_chart_response.md`를
열어 **다시 관찰하고 문서를 고친 뒤** 앱을 손보면 된다.

⚠️ **가격이 맞는지는 안 본다.** 값은 매일 달라지므로 볼 수 없다. 보는 건 **모양**뿐이다.

⚠️ **칸이 있는지만 보면 모자란다.** 이름이 그대로여도 **타입이나 단위가 바뀌면** 조용히
망가진다. 제일 무서운 게 `regularMarketTime`인데, 지금은 **초**이지만 야후가 **밀리초**로
바꾸면 앱이 1000을 곱해 **서기 5만년쯤**이 된다. 그 값이 저장되면 불러오기의 뒷걸음질
가드가 *"저장된 게 더 새것"*이라 판정해 **그 종목이 영구히 얼어붙는다.**
(앱도 같은 걸 막지만 — `yahoo_chart.dart`의 `_asOf` — 여기서 먼저 알아차리는 게 낫다.)

그래서 **말이 되는 값인지**까지 본다: 타입 · 부호 · 시각이 지금 언저리인가.

⚠️ **종목 목록·종가와 아무 상관이 없다.** 이건 앱이 쓰는 남의 API를 지켜보는 것뿐이고,
`docs/` 아래 파일은 건드리지 않는다.

## ⚠️ **못 본 것과 바뀐 것은 다르다** (2026-09-04, 첫 실행에서 배웠다)

첫 실행이 **429(요청한도)**로 죽었다. 야후가 바뀐 게 아니라 **GitHub 러너 IP가 막힌 것**이다 —
Actions 러너 IP는 전 세계가 같이 쓰고 야후를 긁는 사람이 많다. 같은 시각 **폰에서는 멀쩡히**
받아왔다.

그걸 실패로 치면 **가짜 경보**가 되고, 가짜 경보는 진짜 경보보다 나쁘다 — 메일을 무시하게
된다. 그래서 갈라 다룬다:

| | 어떻게 |
|---|---|
| **못 봤다**(429 · 연결 실패 · 5xx) | 알리고 **통과**시킨다. 내일 또 본다 |
| **모양이 다르다** | **실패시킨다** → 메일이 온다 |

⚠️ **먼저 묻는 쪽이 손해다.** 첫 실행에서 국내는 429인데 미국은 됐다 — 국내가 재시도로
100초를 기다리는 동안 한도가 풀려 **미국이 그 덕을 봤다.** 그래서 한 바퀴 돈 뒤
**못 본 것만 한 번 더** 물어본다.

브라우저처럼 보이는 `User-Agent`를 붙여 본다. 야후는 기본 파이썬 UA를 자주 막는다 —
그래도 막히면 위 표대로 조용히 넘어간다.
"""

from __future__ import annotations

import sys
import time

import requests

# 야후는 같은 데이터를 두 호스트로 준다. **한쪽만 막히는 일이 있어** 둘 다 찔러본다.
# ⚠️ 앱은 `query1`만 쓴다(`yahoo_chart.dart`) — 여기서 `query2`가 되는 것은
# *"응답 모양이 그대로다"*를 말해줄 뿐, 앱이 잘 된다는 뜻이 아니다.
HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
URL = "https://{}/v8/finance/chart/{}"
PARAMS = {"range": "5d", "interval": "1d"}

# 야후는 기본 파이썬 UA(`python-requests/...`)를 자주 막는다. 앱은 Dart의 http라 안 걸린다.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# 국내와 미국을 **둘 다** 본다 — 한쪽만 바뀔 수 있다(실제로 국내 정규장 시각만
# 낡아 있었다, 2026-09-04). 오래 상장돼 있고 없어질 일이 없는 것으로 고른다.
SYMBOLS = [("국내", "005930.KS"), ("미국", "AAPL")]

# 앱이 **실제로 읽는 칸**과, 그 값이 말이 되는지 보는 법.
# (→ `reference/yahoo_chart_response.md` 2절 표)
#
# 시각은 **하루가 86,400초**라는 걸 안다. 밀리초로 바뀌면 값이 1000배가 되어
# `SANE_FROM`~`SANE_TO` 밖으로 나간다 — 그래서 단위 변경이 여기서 걸린다.
SANE_FROM = 946_684_800      # 2000-01-01
SANE_TO = 4_102_444_800      # 2100-01-01


def _positive_number(v) -> str | None:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return f"숫자가 아니다({type(v).__name__})"
    return None if v > 0 else "0 이하다"


def _epoch_seconds(v) -> str | None:
    if not isinstance(v, int) or isinstance(v, bool):
        return f"정수가 아니다({type(v).__name__})"
    if not (SANE_FROM <= v <= SANE_TO):
        # 밀리초로 바뀌면 여기 걸린다.
        return f"초 단위 epoch가 아니다(자릿수 {len(str(abs(v)))})"
    return None


def _utc_offset(v) -> str | None:
    if not isinstance(v, int) or isinstance(v, bool):
        return f"정수가 아니다({type(v).__name__})"
    # 지구에 ±14시간 밖의 시간대는 없다.
    return None if -50_400 <= v <= 50_400 else "시차 범위 밖이다"


CHECKS = {
    "regularMarketPrice": _positive_number,
    "regularMarketTime": _epoch_seconds,
    "gmtoffset": _utc_offset,
}

TIMEOUT = 20
# 세 번이면 `query1 → query2 → query1`로 **두 호스트를 다 거친다.**
#
# ⚠️ **더 늘리면 워크플로 타임아웃(10분)에 걸린다** — 종목 둘을 두 바퀴 도는 구조라
# 시도 하나를 늘릴 때마다 네 번씩 는다. 타임아웃은 **빨간 X**라, 못 본 것을 알리려다
# **가짜 경보**를 만드는 꼴이 된다. 지금은 최악이 3분 40초쯤이다.
RETRIES = 3
# 늘려가며 기다린다 — 요청한도는 잠깐 쉬면 풀리는 종류다.
RETRY_PAUSES = [10, 30]
# 못 본 것을 한 번 더 묻기 전에 쉬는 시간.
SECOND_ROUND_PAUSE = 60


class Unseen(Exception):
    """**못 봤다.** 야후가 바뀐 게 아니라 우리가 못 본 것이다 — 실패로 치지 않는다."""


def meta_of(symbol: str) -> dict:
    """`chart.result[0].meta`. 못 보면 [Unseen]."""
    last = ""
    for attempt in range(1, RETRIES + 1):
        host = HOSTS[(attempt - 1) % len(HOSTS)]
        try:
            r = requests.get(
                URL.format(host, symbol),
                params=PARAMS,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
            if r.status_code == 200:
                try:
                    return r.json()["chart"]["result"][0]["meta"]
                except Exception:
                    # 200인데 모양이 다르다 — 이건 **진짜 신호**다.
                    raise
            last = f"HTTP {r.status_code} ({host.split('.')[0]})"
        except Exception as e:
            last = f"{type(e).__name__} ({host.split('.')[0]})"
        if attempt < RETRIES:
            pause = RETRY_PAUSES[attempt - 1]
            print(f"  {last} — {pause}초 뒤 다시")
            time.sleep(pause)
    raise Unseen(f"{symbol}: {last}")


def inspect(label: str, symbol: str, problems: list[str]) -> None:
    """한 종목을 본다. 이상한 게 있으면 [problems]에 담는다. 못 보면 [Unseen]."""
    meta = meta_of(symbol)
    bad: list[str] = []

    for key, check in CHECKS.items():
        if key not in meta:
            bad.append(f"{key}: 칸이 없다")
            continue
        why = check(meta[key])
        if why:
            bad.append(f"{key}: {why}")

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
        # 정규장이 한 시간보다 짧거나 하루보다 길면 뭔가 잘못된 것이다.
        # (길이는 시장마다 다르므로 **정확한 값이 아니라 말이 되는지**만 본다 —
        #  야후가 말하는 국내 마감은 실제보다 30분 이르다. 그건 앱이 따로 안다.)
        if span_ok:
            span = regular["end"] - regular["start"]
            if not (3_600 <= span <= 86_400):
                bad.append(f"정규장 길이가 이상하다({span}초)")

    problems += [f"{label}({symbol}): {b}" for b in bad]
    print(f"{label}({symbol}): 칸 {len(meta)}개 · 이상 {len(bad)}개")


def main() -> None:
    problems: list[str] = []
    pending = list(SYMBOLS)
    unseen: list[str] = []

    # 두 바퀴 돈다. **먼저 묻는 쪽이 손해**라서다 — 첫 바퀴에서 못 본 것은 그사이
    # 흐른 시간 덕에 두 번째엔 되는 일이 많다(첫 실행에서 국내만 429였다).
    for round_no in (1, 2):
        if not pending:
            break
        if round_no == 2:
            print(f"\n못 본 것을 한 번 더 — {SECOND_ROUND_PAUSE}초 쉬고")
            time.sleep(SECOND_ROUND_PAUSE)
        still: list[tuple[str, str]] = []
        unseen = []
        for label, symbol in pending:
            try:
                inspect(label, symbol, problems)
            except Unseen as e:
                still.append((label, symbol))
                unseen.append(f"{label}({e})")
        pending = still

    if problems:
        # 칸 이름만 찍는다 — 값도 종목도 안 남긴다.
        sys.exit(
            "야후 응답이 우리가 아는 모양과 다르다:\n  "
            + "\n  ".join(problems)
            + "\n\n→ project_docs/reference/yahoo_chart_response.md 를 열어 4절(다시 확인하는 법)대로"
            "\n  기기에서 관찰하고, 문서를 고친 뒤 앱을 손볼 것."
        )

    if unseen:
        # ⚠️ **실패시키지 않는다.** 못 본 것은 바뀐 것이 아니다.
        print("\n⚠️ 못 본 것: " + " · ".join(unseen))
        print("   러너 IP가 막힌 것일 수 있다 — 앱은 폰에서 부르므로 영향이 없다.")
        print("   내일 또 본다. **며칠 내리 같은 쪽만 못 보면** 그땐 손으로 확인할 것.")
        if len(unseen) == len(SYMBOLS):
            return
        # 반만 봤으면 **반만 봤다고** 말한다. `그대로다`라고 하면 다 본 줄 안다.
        print("\n본 것은 모양 그대로다")
        return

    print("\n야후 응답 모양 그대로다")


main()
