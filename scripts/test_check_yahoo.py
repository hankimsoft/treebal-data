"""카나리가 **정말로 빨개지는지** 확인한다.

`check_yahoo.py`는 *"모양이 바뀌면 메일이 온다"*는 약속 하나로 존재한다. 그 약속이
깨져 있어도 **아무도 모른다** — 야후는 대개 안 바뀌므로 늘 초록이고, 그게 *"잘 지키고
있다"*와 구분이 안 된다.

⚠️ **실제로 그랬다**(2026-09-08). 200인데 구조가 깨진 경우 코드가 `raise`만 하고
**바깥 `except Exception`이 도로 삼켜** 조용히 통과했다. 주석엔 *"진짜 신호"*라고
적혀 있었는데 **주석이 지키는 건 아무것도 없다.**

네트워크를 안 쓴다 — `requests`와 `time.sleep`을 갈아끼워 **가짜 야후**로 돌린다.
그래서 러너 상태·요청한도와 무관하게 늘 같은 답이 나온다.

    python3 scripts/test_check_yahoo.py
"""

from __future__ import annotations

import contextlib
import io
import runpy
import sys
import time
import types
from pathlib import Path

SCRIPT = Path(__file__).with_name("check_yahoo.py")


def good_meta() -> dict:
    """앱이 읽는 칸이 다 있고 값도 말이 되는 응답."""
    return {
        "regularMarketPrice": 319.97,
        "regularMarketTime": 1788724800,  # 초 단위 epoch
        "gmtoffset": -14400,
        "currentTradingPeriod": {
            "regular": {"start": 1788700200, "end": 1788723600}  # 6.5시간
        },
        "symbol": "AAPL",
    }


def run(meta_maker, *, status: int = 200, body_ok: bool = True) -> int:
    """가짜 응답으로 카나리를 돌리고 **종료 코드**를 돌려준다."""

    class FakeResponse:
        status_code = status

        def json(self):
            if not body_ok:
                # 200인데 `chart.result`가 없다 — 엔드포인트가 바뀌었거나 에러 본문이다.
                return {"chart": {"error": {"code": "Not Found"}}}
            return {"chart": {"result": [{"meta": meta_maker()}]}}

    fake = types.ModuleType("requests")
    fake.get = lambda *a, **k: FakeResponse()
    sys.modules["requests"] = fake

    real_sleep = time.sleep
    time.sleep = lambda *_: None  # 재시도·두 번째 바퀴 대기를 없앤다

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


def without(key: str):
    def make():
        m = good_meta()
        del m[key]
        return m

    return make


def replaced(key: str, value):
    def make():
        m = good_meta()
        m[key] = value
        return m

    return make


def longer_session():
    m = good_meta()
    m["currentTradingPeriod"]["regular"]["end"] += 200_000
    return m


# (이름, 돌리는 법, 빨개져야 하나)
CASES = [
    ("모양 그대로", lambda: run(good_meta), False),
    # ── 바뀐 것 — 빨개져야 한다 ────────────────────────────────────────────
    # 제일 무서운 것: 초 → 밀리초. 앱이 서기 5만년쯤을 저장하고 그 종목이 얼어붙는다.
    ("regularMarketTime이 밀리초", lambda: run(replaced("regularMarketTime", 1788724800000)), True),
    ("regularMarketPrice 칸이 없다", lambda: run(without("regularMarketPrice")), True),
    ("regularMarketPrice가 문자열", lambda: run(replaced("regularMarketPrice", "319.97")), True),
    ("regularMarketPrice가 0 이하", lambda: run(replaced("regularMarketPrice", 0)), True),
    ("regularMarketTime 칸이 없다", lambda: run(without("regularMarketTime")), True),
    ("gmtoffset이 시차 범위 밖", lambda: run(replaced("gmtoffset", 999_999)), True),
    ("currentTradingPeriod가 없다", lambda: run(without("currentTradingPeriod")), True),
    ("정규장 길이가 이상하다", lambda: run(longer_session), True),
    # ⚠️ 2026-09-08까지 **여기가 새고 있었다.**
    ("200인데 구조가 깨졌다", lambda: run(good_meta, body_ok=False), True),
    # ── 못 본 것 — 통과해야 한다(가짜 경보는 진짜 경보보다 나쁘다) ────────
    ("429 요청한도", lambda: run(good_meta, status=429), False),
    ("503 서버 오류", lambda: run(good_meta, status=503), False),
    ("404", lambda: run(good_meta, status=404), False),
]


def main() -> None:
    failed = []
    for name, go, should_fail in CASES:
        code = go()
        ok = (code != 0) == should_fail
        want = "빨강" if should_fail else "초록"
        got = "빨강" if code else "초록"
        print(f"{'  ok  ' if ok else ' FAIL '} {name:28s} 기대 {want} · 실제 {got}")
        if not ok:
            failed.append(name)

    if failed:
        sys.exit(
            f"\n카나리가 약속을 안 지킨다 ({len(failed)}개):\n  " + "\n  ".join(failed)
        )
    print(f"\n{len(CASES)}개 모두 약속대로다")


main()
