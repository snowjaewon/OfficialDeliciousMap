# 서울에서 읽지 못한 제목 기간 표기 37건 (#155)

2026-09-14 실행. [#141](issue-141.md)이 기간 미선언(`undeclared_in_year`)으로 남긴 서울 제목
37건을 네 갈래로 나눠 판정한 기록이다. 비교의 기준점은 `origin/develop` 1eaf190이다. 이 문서의
수는 모두 커밋된 `data/<city>/**/fetch.json`을 [4절](#4-다시-세는-방법)의 명령으로 센 것이고,
단위는 **제목이 있는 장부 항목**이다(#141의 13,677건과 같은 단위, 도시·기관 `fetch.json`을 중복
제거 없이 더함). "종"은 서로 다른 제목 문자열의 수다.

## 1. 더한 표기

모두 `DECLARATION`(해에 붙은 표기)이 기간을 못 읽은 제목에만 쓰는 보조 규칙이다. 해에 붙은
표기가 먼저이므로 `DECLARATION`이 읽는 제목의 판정은 어느 도시에서도 바뀌지 않는다.

| 규칙 | 모양 | 실측 예 | 서울 항목 |
| --- | --- | --- | --- |
| `BARE_YEAR` | 제목 맨 앞 네 자리 해 + 띄어 쓴 바로 뒤의 달 | 구로 `2026 3월 자동차관리과시책추진업무추진비 공개` | 3 |
| `BARE_YEAR` | 제목 맨 앞 네 자리 해 + 제목 끝 괄호의 달 | 구로 `2026 행정관리국 기관운영업무추진비 집행내역(4월)` | 25 |
| `YEARLESS_MONTH` | 해 없이 제목 가운데에 띄어 쓴 달 | 성북 `민원여권과 1월 시책추진업무추진비 공개` | 2 |
| `YEARLESS_MONTH` | 해 없이 제목 끝 괄호의 달 | 성북 `지역경제과 시책추진업무추진비 집행내역 공개(8월)` | 2 |

- `BARE_YEAR`는 달이 없으면 그 해 전체로 넓히지 않는다. 달 없이 `2026 …`만 적은 제목, 제목 끝이
  아닌 괄호의 달, 제목 맨 앞이 아닌 해, 달 뒤에 붙은 글자(`3월분`), 분기 뒤 괄호의 달은 실측하지
  않아 읽지 않는다.
- 광주 게시판에도 `BARE_YEAR` 모양이 8종 11항목 있고 그중 5종이 범위다(`2015 5~6월 …`,
  `2015 9-10월 …`, `2015 6∼7월 …`, `2019 5~6월 …`, `2012 1월 ~4월 …`). 해 바로 뒤의 달은
  `DECLARATION`과 같은 달 표기(`MONTHS`)를 써서 범위를 첫 달로 잘라 읽지 않는다. 8종 모두
  게시일이 2012~2020년이라 `posted_out_of_range` 그대로다.
- 해 없는 달은 [#146](issue-132.md#issue-146-update--dong-gu-titles-and-a-month-only-title-2026-09-14)의
  규칙대로 게시일까지의 가장 가까운 그 달이다. 서울 네 건은 `1월`·`6월`이 대상이고, 9월에 올린
  `(8월)` 두 건이 대상 기간 밖이다.
- 넓힌 `YEARLESS_MONTH`는 광주 제목 8항목도 새로 읽는다 — 가운데 달 6(`수질연구소 8월 …` 등,
  `2013넌 9월 …` 오기 2 포함), 끝 괄호 달 2(`국제협력과 업무추진비 사용내역(6월)` 등). 모두
  2012~2015년 게시라 판정이 바뀌지 않는다.
- 해 없는 제목에 달의 범위가 있으면(`합성과 6월 ~ 7월 …`, `합성과 1 ~ 3월 …`) 범위를 달 하나로
  잘라 읽지 않도록 읽지 않는다(`MONTH_RANGE`). 네 도시에 이런 제목은 없다.

## 2. 읽지 않기로 한 갈래

| 갈래 | 서울 항목 | 제목 | 이유 |
| --- | --- | --- | --- |
| 기관이 해를 잘못 적었다 | 2 | 성동 `2026월 1월 돌봄건강과 …`, 성북 `정릉4동 업무추진비 집행내역 공개(206.4월)` | 부산에도 `2026월 3월 덕천1동 …`, `…사용내역(202년 2월)`이 있어 네 항목이 세 모양이다. 규칙이 되지 않으므로 짐작하지 않는다. 가운데 달 규칙이 `2026월 1월`을 게시일의 해로 읽지 않도록, 해 자리에 세 자리 이상의 숫자를 쓴 제목(`2026월`·`206.`·`202년`)은 해 없는 제목으로 보지 않는다(`MISWRITTEN_YEAR`) |
| 기간을 적지 않았다 | 3 | 강남 `지방보조금으로 취득한 중요재산`, 강서 `안전교통국, 안전관리과 업무추진비 누락 내역 공개`, 서초 `방배2동 기관운영업무추진비 내역공개(현금)` | 더할 표기가 없다. 제목이 밝히지 않은 기간을 게시일로 채우지 않는다 |

이 다섯 항목은 원본으로는 수집돼 있고 대상 선별에서만 빠진다.

## 3. 판정 전·후

| 도시 | 제목 있는 항목 | 전: 대상 / 기간 밖 / 게시일 밖 / 미선언 | 후: 대상 / 기간 밖 / 게시일 밖 / 미선언 |
| --- | --- | --- | --- |
| 서울 | 13,677 | 10,161 / 3,416 / 63 / **37** | 10,184 / 3,425 / 63 / **5** |
| 광주 | 12,413 | 1,097 / 530 / 10,786 / 0 | 같다 |
| 울산 | 3,148 | 2,276 / 872 / 0 / 0 | 같다 |
| 부산 | 3,519 | 2,373 / 1,143 / 0 / 3 | 같다 |

서울에서 판정이 바뀐 32항목은 모두 미선언에서 나왔다 — 대상 23, 기간 밖 9(구로 `2025 …(12월)`
2, 구로 7·8월 5, 성북 `(8월)` 2). 기간 밖 9는 4절 출력의 `BARE_YEAR`·`YEARLESS_MONTH` 줄 가운데
`declared_out_of_range`인 줄이다.

**광주·울산은 판정이 바뀐 장부 항목이 0건이다.** 두 도시의 미선언이 전부터 0건이고, 새 규칙은
미선언인 제목에만 쓰이기 때문이다. 대상 원본이 그대로이므로 커밋된 광주·울산 산출물을 다시 내지
않았다. develop의 부산도 판정이 바뀐 항목이 0건이다. 부산의 미선언 3항목은 오기 2와 시청
`회계장비담당관 2분기 시책업무추진비 사용내역`이다 — 해 없는 분기는 실측 범위 밖이라 #155에서
다루지 않았다.

## 4. 다시 세는 방법

저장소 루트, Git Bash. 전은 `git stash`로 이 변경을 걷어 낸 뒤, 전에는 없는 `BARE_YEAR`를
찾는 두 줄(`if period.BARE_YEAR…`와 그 아래 한 줄)을 빼고 실행했다. 도시마다 첫 줄이 3절 표이고, `BARE_YEAR`·`YEARLESS_MONTH` 줄은
`DECLARATION`이 못 읽은 제목 중 그 규칙에 맞는 것, `undeclared` 줄은 남은 미선언 제목이다.

```bash
PYTHONIOENCODING=utf-8 uv run python - seoul gwangju ulsan busan <<'EOF'
import json, sys
from collections import Counter
from datetime import date
from pathlib import Path
from deliciousmap import period
for city in sys.argv[1:]:
    counts, bare, yearless, undeclared = Counter(), Counter(), Counter(), []
    for file in sorted(Path("data", city).glob("**/fetch.json")):
        for source in json.loads(file.read_text(encoding="utf-8"))["payload"]["sources"]:
            title = source.get("title")
            if not title:
                continue
            posted = date.fromisoformat(source["posted"]) if source.get("posted") else None
            spent = date.fromisoformat(source["spent_on"]) if source.get("spent_on") else None
            reason = period.exclusion(posted, title, spent)
            counts[str(reason)] += 1
            if reason == "undeclared_in_year":
                undeclared.append(title)
            if period.DECLARATION.search(title) is None:
                if period.BARE_YEAR.search(title):
                    bare[(source.get("posted"), str(reason), title)] += 1
                elif period.YEARLESS_MONTH.search(title):
                    yearless[(source.get("posted"), str(reason), title)] += 1
    print(city, sum(counts.values()), dict(counts))
    for name, found in (("BARE_YEAR", bare), ("YEARLESS_MONTH", yearless)):
        print(f"  {name}: titles {len(found)} entries {sum(found.values())}")
        for (posted, reason, title), n in sorted(found.items()):
            print(f"    {posted} {reason} x{n} {title}")
    for title in sorted(undeclared):
        print(f"  undeclared: {title}")
EOF
```

서울 `YEARLESS_MONTH` 11항목은 성북 4, #137·#146의 맨 앞 달 규칙이 이미 읽던 6, 오기로 막은
성동 1이다. 광주 `YEARLESS_MONTH` 46항목은 맨 앞 달 38과 새로 읽는 8이다.

## 5. 검증

- `tests/test_period.py`: 더한 모양 네 가지와 읽지 않는 모양(달 없는 해, 끝이 아닌 괄호, 맨 앞이
  아닌 해, `3월분`, 분기 뒤 괄호의 달, 해 없는 제목의 띄어 쓴 범위, 오기 세 모양)을 행동 테스트로
  막았다.
