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
"""

from __future__ import annotations

import sys
import time

import requests

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
PARAMS = {"range": "5d", "interval": "1d"}

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
RETRIES = 3
RETRY_PAUSE = 10


def meta_of(symbol: str) -> dict:
    """`chart.result[0].meta`. 잠깐 그런 실패는 몇 번 다시 해본다."""
    last = ""
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(URL.format(symbol), params=PARAMS, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.json()["chart"]["result"][0]["meta"]
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = type(e).__name__
        if attempt < RETRIES:
            print(f"  {last} — {RETRY_PAUSE}초 뒤 다시")
            time.sleep(RETRY_PAUSE)
    sys.exit(
        f"야후를 못 불렀다 ({symbol}): {last}\n"
        "→ 막힌 것이라면 앱의 시세도 같이 막힌 것이다. reference/yahoo_chart_response.md 참고"
    )


def main() -> None:
    problems: list[str] = []

    for label, symbol in SYMBOLS:
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

    if problems:
        # 칸 이름만 찍는다 — 값도 종목도 안 남긴다.
        sys.exit(
            "야후 응답이 우리가 아는 모양과 다르다:\n  "
            + "\n  ".join(problems)
            + "\n\n→ project_docs/reference/yahoo_chart_response.md 를 열어 4절(다시 확인하는 법)대로"
            "\n  기기에서 관찰하고, 문서를 고친 뒤 앱을 손볼 것."
        )

    print("야후 응답 모양 그대로다")


main()
