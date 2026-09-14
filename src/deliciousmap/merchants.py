"""상호 표기에서 읽는 사실. 조회·판정·저장은 하지 않고 레코드의 원본 표기도 바꾸지 않는다.

원본이 상호 칸 하나에 업소 둘 이상을 적는 방식이 둘이다. 이름을 다 적고 구분자로 나눈 표기
(합쳐 적은 상호, `시골밥집, 데이지`)와, 이름은 첫 곳만 적고 나머지는 수만 밝힌 꼬리말
(이름 없는 동행 업소, `카페말바우 외 1`)이다. 둘 다 표기를 통째로 조회하면 제공자에 그런 업소가
없어 후보가 0건이 된다.

- 꼬리말은 [#127](https://github.com/snowjaewon/OfficialDeliciousMap/issues/127)이 떼어 이름이
  적힌 첫 업소와 이름 없는 나머지의 수로 나눈다. 이름을 하나도 안 적은 업소는 규칙만으로 가른다.
- 구분자는 [#117](https://github.com/snowjaewon/OfficialDeliciousMap/issues/117)이 이름 후보로
  나누되 조회를 더 해 보는 데만 쓴다. 무엇이 업소 몇 곳인지는 사람 확인
  (`data/manual/<city>/merchants.jsonl`)이 정한다 — `그저,쉼`처럼 이름 안에 구분자가 든 한 업소를
  규칙으로는 가릴 수 없기 때문이다.

`POLICY_VERSION`은 구분자 표기 규칙과 그것을 읽는 가르기 정책의 버전이다. 확인을 레코드에
적용하는 일은 다른 사람 검토 입력과 규칙이 같아 `restoration.divide`가 한다. 규칙이 바뀌면 나뉜
이름도 보류 사유도 달라지므로 parse와 geocode의 의존성이 이 값을 함께 읽는다. 꼬리말 규칙이
바꾸는 것은 근거와 대조할 이름이라 그 판정의 버전은 `identity.POLICY_VERSION`이 맡는다.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from deliciousmap.contracts import Record

POLICY_VERSION = "merchants-1"

# 이름 없이 수만 밝힌 꼬리말. 세는 낱말과 `외` 앞뒤의 공백은 원본마다 다르다.
# 뒤 갈래는 수도 적지 않은 맨끝 `외`이며, 앞의 공백을 요구해 낱말 안의 글자를 자르지 않는다.
_TAIL = re.compile(r"(?:\s*외\s*(?P<count>\d+)\s*(?:개소|곳|명|개)?|\s+외)\s*$")

# 원본이 실제로 쓴 구분자(2026-09-14 광주 실측: 쉼표 443건·슬래시 81건·`&` 19건·`및` 6건).
# 숫자 사이의 쉼표는 천단위 구분이라 가르지 않는다 — `낙지촌 96,000원 / 엠지(MG)블루 17,500`은
# 슬래시로만 갈린다. `및`은 앞뒤가 공백일 때만 구분자로 본다.
SEPARATOR = re.compile(r"(?<!\d),(?!\d)|/|&|\s및\s")


@dataclass(frozen=True)
class Companions:
    """상호 칸 하나가 밝힌 업소. 이름이 적힌 첫 업소와 이름 없는 나머지의 수로 나눈다."""

    # 조회하고 근거와 대조할 이름. 꼬리말이 없으면 원본 표기 그대로다.
    named: str
    # 이름 없는 업소 수. 꼬리말이 없으면 0, 원본이 수를 적지 않았으면 알 수 없어 None이다.
    unnamed: int | None = 0


def read(merchant: str) -> Companions:
    """상호 끝의 꼬리말만 뗀다. 이름 가운데의 `외`와 이름이 남지 않는 표기는 그대로 둔다."""
    found = _TAIL.search(merchant)
    named = merchant[: found.start()].strip() if found else ""
    # 꼬리말이 없거나, 떼면 이름이 하나도 남지 않는다. 조회할 이름을 지어내지 않는다.
    if found is None or not named:
        return Companions(merchant, 0)
    count = found.group("count")
    return Companions(named, int(count) if count is not None else None)


def parts(merchant: str) -> tuple[str, ...]:
    """상호 표기를 이름 후보로 나눈다. 나눌 구분자가 없으면 표기 하나를 그대로 돌려준다."""
    found = tuple(item.strip() for item in SEPARATOR.split(merchant))
    return (merchant,) if len(found) == 1 or not all(found) else found


def is_merged(merchant: str) -> bool:
    """업소 둘 이상으로 읽히는 표기인지. 한 업소인지는 사람 확인만이 가른다."""
    return len(parts(merchant)) > 1


def expense_total(records: Iterable[Record]) -> Decimal:
    """지출 총액. 나뉜 레코드는 금액이 빈 값이므로 그 지출의 금액을 한 번만 더한다(ADR-0007)."""
    total = Decimal(0)
    counted: set[str] = set()
    for record in records:
        if record.amount_krw is not None:
            total += record.amount_krw
        elif record.expense is not None and record.expense.expense_id not in counted:
            counted.add(record.expense.expense_id)
            total += record.expense.amount_krw
    return total


def unsplit_expenses(records: Iterable[Record]) -> int:
    """업소 둘 이상으로 읽히는데 사람 확인이 없어 가르지 못한 지출 수."""
    return sum(record.expense is None and is_merged(record.merchant) for record in records)
