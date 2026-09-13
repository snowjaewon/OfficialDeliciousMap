"""상호 표기에서 읽는 사실. 조회·판정·저장은 하지 않는다.

원본이 상호 칸 끝에 `외 1`처럼 수만 적고 이름은 적지 않을 때가 있다. 그 꼬리말을 통째로 조회하면
제공자에 그런 업소가 없어 후보가 0건이 된다. 여기서 꼬리말을 떼어 이름이 적힌 첫 업소와
이름 없는 나머지 업소의 수로 나눈다. 레코드의 원본 표기는 이 모듈이 바꾸지 않는다.

근거와 실측은 [#127](https://github.com/snowjaewon/OfficialDeliciousMap/issues/127)에 있다.
이름을 다 적고 구분자로 나눈 표기(합쳐 적은 상호)는 가르는 일이며 여기서 떼지 않는다.
"""

import re
from dataclasses import dataclass

# 이름 없이 수만 밝힌 꼬리말. 세는 낱말과 `외` 앞뒤의 공백은 원본마다 다르다.
# 뒤 갈래는 수도 적지 않은 맨끝 `외`이며, 앞의 공백을 요구해 낱말 안의 글자를 자르지 않는다.
_TAIL = re.compile(r"(?:\s*외\s*(?P<count>\d+)\s*(?:개소|곳|명|개)?|\s+외)\s*$")


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
