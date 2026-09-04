"""공공데이터포털에서 국내 종목 목록과 종가를 받아 docs/ 아래에 쓴다.

**`금융위원회_주식시세정보`를 쓴다.** 이 API는 하루치 시세를 주는데 거기에 종목명이
같이 들어 있다(`srtnCd` 단축코드 · `itmsNm` 종목명 · `clpr` 종가 · `mrktCtg` 시장구분).
그래서 **한 번 받아 파일 둘을 만든다** — 호출이 늘지 않는다.

  · `docs/symbols/krx.json` — 코드·이름·시가총액. 앱의 **한글 검색**이 쓴다
    (시가총액은 **순위**에 쓴다 — `삼성`을 쳤을 때 `삼성전자`가 위로 와야 한다)
  · `docs/prices/krx.json`  — 코드·종가·기준일. 앱의 **시세 예비**가 쓴다
    (1순위는 계속 야후다. 야후는 장중에도 값이 있고 이건 어제 종가뿐이다)

이용허락범위는 **제한없음**임을 확인했다(사용자, 2026-09-03) — 그래서 종가도 올린다.

⚠️ **`basDt`(기준일자)로 하루를 집어서 받아야 한다.** 안 주면 날짜별 전 이력이 나온다
(문서 예제의 `totalCount`가 171만 건이다). 그래서 오늘부터 거꾸로 짚어 **가장 최근
영업일**을 먼저 찾는다 — 주말·공휴일엔 직전 영업일이 최신이다.

**포털이 몇 시에 올리는지 모른다.** 그래서 크론이 저녁에 여러 번 돈다(워크플로 참고).
대신 **날짜만 짚어보고 이미 최신이면 그 자리에서 끝낸다** — 헛도는 실행이
전부 받아오지 않게. 그런 실행은 호출 서너 번으로 끝난다.

규칙 둘:
  · **키를 절대 찍지 않는다.** 이 API는 키를 URL 쿼리에 넣는데, URL을 로그에 남기면
    공개 저장소의 Actions 로그로 그대로 나간다. 깃허브의 자동 가리기(***)는
    글자가 정확히 같을 때만 되는데 URL 인코딩되면(`+`→`%2B`) 못 알아본다.
  · **실패하면 아무것도 안 쓴다.** 빈 파일로 덮으면 앱의 검색이 통째로 죽는다.
"""

# `str | None` 같은 표기를 옛 파이썬에서도 쓰게 해준다(워크플로는 3.12지만
# 손으로 돌려볼 땐 그보다 낮을 수 있다).
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import sys
import time

import requests

KEY = os.environ["DATA_GO_KR_KEY"]
BASE = "https://apis.data.go.kr/1160100/service"

# 주식과 나머지는 **서비스가 갈린다.** 포털에서 각각 따로 활용신청해야 그 키로 불린다.
# 아직 신청 안 한 게 있으면 그 줄만 지우면 된다 — 주식만으로도 목록은 선다.
SERVICES = [
    ("주식", "GetStockSecuritiesInfoService/getStockPriceInfo"),
    ("ETF", "GetSecuritiesProductInfoService/getETFPriceInfo"),
    ("ETN", "GetSecuritiesProductInfoService/getETNPriceInfo"),
    # KRX 금시장 — `금 99.99_1Kg`(04020000)·미니금. **종가가 원/g**이다.
    ("금", "GetGeneralProductInfoService/getGoldPriceInfo"),
]

# ⚠️ **ELW(`getETFPriceInfo`와 같은 서비스의 `getELWPriceInfo`)는 일부러 뺐다.**
#   ① 하루치가 **5,000개쯤**이라 목록이 두 배가 된다(주식이 2,700개다)
#   ② 이름이 `신한H501삼성전자콜` 꼴이라 **`삼성전자`를 치면 수백 개가 걸린다** — 검색이 죽는다
#   ③ 애초에 리밸런싱으로 들고 갈 물건이 아니다(단기 파생이다)
#   ④ 코드가 `50H501`이라 앱의 국내 코드 규칙(`\d{4}` + 두 자리)에 안 맞는다

SYMBOLS_OUT = pathlib.Path("docs/symbols/krx.json")
PRICES_OUT = pathlib.Path("docs/prices/krx.json")
PAGE = 1000
# 문서상 초당 30건까지다. 넉넉히 쉬어간다 — 급할 게 없는 일이다.
PAUSE = 0.2
# 한 번 삐끗했다고 실행을 통째로 버리지 않는다. 한 실행이 호출을 12~18번 하는데
# **그중 하나만 타임아웃 나도 전부 헛수고**가 된다(2026-09-03 밤 실제로 그랬다).
RETRIES = 3
RETRY_PAUSE = 5


def call(path: str, **params) -> dict:
    """한 번 부른다. **일시적인 실패는 몇 번 다시 시도한다.**

    키가 틀렸거나(401·403) 응답 모양이 다른 건 **다시 해도 같으므로** 바로 죽는다 —
    괜히 세 번 더 기다릴 이유가 없다.
    """
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(
                f"{BASE}/{path}",
                # 키를 params로 — 문자열을 직접 이어 붙이면 실수로 로그에 남기기 쉽다.
                params={"serviceKey": KEY, "resultType": "json", **params},
                timeout=30,
            )
        except Exception as e:
            # ⚠️ **여길 안 잡으면 키가 샌다.** requests의 연결 예외 메시지엔 URL이 통째로
            # 들어 있고(`...?serviceKey=aB3%2BxY%3D&...`), 안 잡으면 파이썬이 그 역추적을
            # 공개 저장소의 Actions 로그에 그대로 찍는다. 깃허브의 자동 가리기(***)는
            # **인코딩된 형태를 못 알아본다.** 그래서 **예외의 종류만** 남긴다.
            if attempt == RETRIES:
                sys.exit(f"연결 실패: {type(e).__name__} ({path}) — {RETRIES}번 시도")
            print(f"  연결 실패({type(e).__name__}) — {RETRY_PAUSE}초 뒤 다시")
            time.sleep(RETRY_PAUSE)
            continue

        if r.status_code == 200:
            try:
                return r.json()["response"]["body"]
            except Exception:
                # 키가 틀리면 200에 XML 에러 문서가 오기도 한다. **다시 해도 같다.**
                sys.exit(
                    f"응답이 예상과 다르다 ({path}) — 인증키를 확인할 것(디코딩 키여야 한다)"
                )

        # 5xx·429는 잠깐 그런 것일 수 있다. 4xx는 다시 해도 같다.
        # ⚠️ r.url도 r.text도 찍지 않는다 — 둘 다 키를 담고 있을 수 있다.
        retryable = r.status_code >= 500 or r.status_code == 429
        if not retryable or attempt == RETRIES:
            sys.exit(f"조회 실패: HTTP {r.status_code} ({path})")
        print(f"  HTTP {r.status_code} — {RETRY_PAUSE}초 뒤 다시")
        time.sleep(RETRY_PAUSE)

    sys.exit(f"조회 실패 ({path})")  # 여기 오지 않는다


def rows_of(body: dict) -> list[dict]:
    items = (body.get("items") or {}).get("item") or []
    return items if isinstance(items, list) else [items]


def latest_business_day(path: str) -> str:
    """오늘부터 거꾸로 짚어 데이터가 있는 첫 날. 주말·공휴일을 이걸로 넘긴다."""
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    for back in range(10):
        day = (today - datetime.timedelta(days=back)).strftime("%Y%m%d")
        body = call(path, basDt=day, numOfRows=1, pageNo=1)
        if int(body.get("totalCount") or 0) > 0:
            return day
        time.sleep(PAUSE)
    sys.exit(f"최근 10일 안에 데이터가 없다 ({path})")


def fetch_day(path: str, day: str) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        body = call(path, basDt=day, numOfRows=PAGE, pageNo=page)
        got = rows_of(body)
        out += got
        if len(got) < PAGE:
            return out
        page += 1
        if page > 50:  # 안전장치 — 5만 건이면 뭔가 잘못된 것이다
            sys.exit(f"페이지가 너무 많다 ({path})")
        time.sleep(PAUSE)


def number_of(row: dict, key: str) -> float | None:
    """숫자 칸. 콤마가 섞여 오기도 하고, 빈 값·0은 **없는 것으로 친다.**"""
    try:
        value = float(str(row.get(key) or "").replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def price_of(row: dict) -> float | None:
    """종가. 0이나 빈 값은 **없는 것으로 친다** — 거래정지 종목이 0으로 오기도 한다."""
    return number_of(row, "clpr")


def write(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


# 국내 코드는 두 모양이다.
#   · 주식·ETF·ETN — **여섯 자리인데 숫자만은 아니다**(`0085P0`·`00104K`)
#   · 일반상품(금)  — **여덟 자리 숫자**(`04020000`)
#
# ⚠️ **숫자만 걸러내면 안 된다.** 글자가 섞인 종목을 버리면 그건 **검색에 영영 안 나온다.**
# 앱도 같은 함정을 밟았다가 고쳤다(2026-09-02, `quote_service.dart`의 `marketOf`) —
# **두 곳의 규칙이 같아야 한다.** 여기서 통과시킨 코드를 앱이 국내로 못 알아보면
# 검색해서 골라도 시세를 못 부른다.
CODE = re.compile(r"^(?:[0-9]{4}[A-Z0-9]{2}|[0-9]{8})$")


def saved_days() -> dict[str, str]:
    """지난 실행이 남긴 서비스별 기준일. 파일이 없거나 깨졌으면 빈 값.

    ⚠️ **내보낼 파일이 하나라도 없으면 빈 값을 준다.** 안 그러면 이런 일이 생긴다 —
    출력 파일을 하나 더 늘렸는데(2026-09-04에 `prices`를 그렇게 더했다) 그날 날짜가
    이미 `symbols`에 적혀 있으면 **조기 종료해서 새 파일이 영영 안 만들어진다.**
    """
    if not all(p.exists() for p in (SYMBOLS_OUT, PRICES_OUT)):
        return {}
    try:
        return json.loads(SYMBOLS_OUT.read_text(encoding="utf-8"))["basDt"]
    except Exception:
        return {}


def code_of(row: dict) -> str | None:
    raw = str(row.get("srtnCd") or "").strip().upper()
    # `A005930`처럼 앞에 글자가 붙어 오는 경우가 있다.
    if raw.startswith("A") and CODE.match(raw[1:]):
        raw = raw[1:]
    return raw if CODE.match(raw) else None


def main() -> None:
    # **날짜부터 짚는다.** 포털이 몇 시에 올리는지 몰라 크론이 여러 번 도는데,
    # 이미 받아둔 날짜면 **전부 받을 필요가 없다** — 호출 서너 번으로 끝낸다.
    days = {label: latest_business_day(path) for label, path in SERVICES}
    if days == saved_days():
        print(f"이미 최신이다 ({days}) — 받을 게 없다")
        return

    names: dict[str, str] = {}
    caps: dict[str, float] = {}
    prices: dict[str, tuple[float, str]] = {}
    sample_keys: list[str] = []

    for label, path in SERVICES:
        day = days[label]
        rows = fetch_day(path, day)
        if rows and not sample_keys:
            sample_keys = sorted(rows[0].keys())

        before = len(names)
        for row in rows:
            code = code_of(row)
            if not code:
                continue
            name = str(row.get("itmsNm") or "").strip()
            if name:
                names.setdefault(code, name)
            # 시가총액 — **검색 순위에만** 쓴다. 없으면(스팩·일부 ETN) 0으로 두면 되고,
            # 그러면 그냥 뒤로 밀린다.
            cap = number_of(row, "mrktTotAmt")
            if cap is not None:
                caps.setdefault(code, cap)
            price = price_of(row)
            if price is not None:
                # 기준일은 **줄에 적힌 것**을 쓴다 — 우리가 물어본 날과 다를 수 있다.
                prices.setdefault(code, (price, str(row.get("basDt") or day)))
        print(f"{label}: {day} 기준 {len(rows)}줄 → 이름 {len(names) - before}개 더함")

    if not names:
        # 여기 걸리면 칸 이름이 문서와 다른 것이다.
        # **칸 이름만** 찍는다 — 거기엔 비밀이 없다. 이 줄을 그대로 알려주면 고칠 수 있다.
        sys.exit(f"쓸 수 있는 줄이 없다. 받은 칸 이름: {sample_keys}")

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    # 앱이 읽는 모양 — **이름표를 붙인다**(자리 순서로 적으면 나중에 값을 하나 더할 때
    # 통째로 밀린다).
    write(
        SYMBOLS_OUT,
        {
            "updatedAt": now,
            "basDt": days,
            "count": len(names),
            "items": [
                {"code": c, "name": n, "cap": caps.get(c, 0)}
                for c, n in sorted(names.items())
            ],
        },
    )
    write(
        PRICES_OUT,
        {
            "updatedAt": now,
            "count": len(prices),
            # 기준일을 **줄마다** 담는다 — 주식과 ETF가 다른 날일 수 있고,
            # 앱은 "언제 가격인지"를 화면에 적는다.
            "items": [
                {"code": c, "close": p, "asOf": d}
                for c, (p, d) in sorted(prices.items())
            ],
        },
    )
    print(f"이름 {len(names)}개 · 종가 {len(prices)}개를 썼다")


main()
