"""합쳐 적은 상호의 표기 규칙. 레코드를 가르거나 업소를 확정하지 않는다.

원본이 한 칸에 업소 둘 이상을 적은 표기를 이름 후보로 나눈다. 나눈 이름은 조회를 더 해 보는
데만 쓰고, 무엇이 업소 몇 곳인지는 사람 확인(`data/manual/<city>/merchants.jsonl`)이 정한다 —
`그저,쉼`처럼 이름 안에 구분자가 든 한 업소를 규칙으로는 가릴 수 없기 때문이다.

`POLICY_VERSION`은 이 표기 규칙과 그것을 읽는 가르기 정책의 버전이다. 확인을 레코드에 적용하는
일은 다른 사람 검토 입력과 규칙이 같아 `restoration.divide`가 한다. 규칙이 바뀌면 나뉜 이름도
보류 사유도 달라지므로 parse와 geocode의 의존성이 이 값을 함께 읽는다.
"""

import re
from collections.abc import Iterable
from decimal import Decimal

from deliciousmap.contracts import Record

POLICY_VERSION = "merchants-1"

# 원본이 실제로 쓴 구분자(2026-09-14 광주 실측: 쉼표 443건·슬래시 81건·`&` 19건·`및` 6건).
# 숫자 사이의 쉼표는 천단위 구분이라 가르지 않는다 — `낙지촌 96,000원 / 엠지(MG)블루 17,500`은
# 슬래시로만 갈린다. `및`은 앞뒤가 공백일 때만 구분자로 본다.
SEPARATOR = re.compile(r"(?<!\d),(?!\d)|/|&|\s및\s")


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
