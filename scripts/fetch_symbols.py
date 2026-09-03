"""공공데이터포털에서 국내 상장 종목 목록을 받아 docs/symbols/krx.json으로 쓴다.

규칙 둘:
  · **키를 절대 찍지 않는다.** 이 API는 키를 URL 쿼리에 넣는데, URL을 로그에 남기면
    공개 저장소의 Actions 로그로 그대로 나간다. 깃허브의 자동 가리기(***)는
    글자가 정확히 같을 때만 되는데 URL 인코딩되면(`+`→`%2B`) 못 알아본다.
  · **실패하면 아무것도 안 쓴다.** 빈 파일로 덮으면 앱의 검색이 통째로 죽는다.
"""

import datetime
import json
import os
import pathlib
import sys

import requests

KEY = os.environ["DATA_GO_KR_KEY"]
BASE = "https://apis.data.go.kr/1160100/service/GetKrxListedInfoService/getItemInfo"
OUT = pathlib.Path("docs/symbols/krx.json")
PAGE = 1000


def fetch_page(page: int) -> list[dict]:
    r = requests.get(
        BASE,
        # 키를 params로 넘긴다 — 문자열을 직접 이어 붙이면 실수로 로그에 남기기 쉽다.
        params={
            "serviceKey": KEY,
            "resultType": "json",
            "numOfRows": PAGE,
            "pageNo": page,
        },
        timeout=30,
    )
    if r.status_code != 200:
        # ⚠️ r.url도 r.text도 찍지 않는다 — 둘 다 키를 담고 있을 수 있다.
        sys.exit(f"조회 실패: HTTP {r.status_code} (page {page})")
    try:
        body = r.json()["response"]["body"]
    except Exception:
        sys.exit(f"응답이 예상과 다르다 (page {page})")
    items = body.get("items", {}).get("item", [])
    return items if isinstance(items, list) else [items]


def code_of(row: dict) -> str | None:
    """단축코드 6자리. `A005930`처럼 앞에 글자가 붙어 오기도 한다."""
    raw = str(row.get("srtnCd") or "")
    digits = "".join(c for c in raw if c.isdigit())
    return digits[-6:] if len(digits) >= 6 else None


def main() -> None:
    rows: list[dict] = []
    page = 1
    while True:
        got = fetch_page(page)
        rows += got
        if len(got) < PAGE:
            break
        page += 1
        if page > 50:  # 안전장치 — 5만 건이면 뭔가 잘못된 것이다
            sys.exit("페이지가 너무 많다")

    # 코드 기준으로 겹치는 걸 지운다(같은 종목이 여러 시장에 걸쳐 나오기도 한다).
    by_code: dict[str, str] = {}
    for row in rows:
        code = code_of(row)
        name = str(row.get("itmsNm") or "").strip()
        if code and name:
            by_code.setdefault(code, name)

    if not by_code:
        # 여기 걸리면 필드 이름이 짐작과 다른 것이다.
        # **칸 이름만** 찍는다 — 거기엔 비밀이 없다. 이 줄을 그대로 알려주면 고칠 수 있다.
        sample = sorted(rows[0].keys()) if rows else []
        sys.exit(f"쓸 수 있는 줄이 없다. 받은 칸 이름: {sample}")

    now = datetime.datetime.now(datetime.timezone.utc)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "updatedAt": now.isoformat(timespec="seconds"),
                "count": len(by_code),
                # 앱이 읽는 모양 — **이름표를 붙인다**(자리 순서로 적으면 나중에
                # 값을 하나 더할 때 통째로 밀린다).
                "items": [
                    {"code": c, "name": n} for c, n in sorted(by_code.items())
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"{len(by_code)}개 종목을 썼다")


main()
