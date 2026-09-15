"""상호 포함 일치 규칙. 두 표기가 같은 업소의 이름인지만 가른다.

원본이 적은 상호와 제공자가 밝힌 상호는 지점명·법인 표기·괄호·띄어쓰기에서 갈린다. 그 차이를
떼고 남은 뼈대가 같거나 한쪽이 다른 쪽의 앞·뒤에 그대로 붙으면 같은 업소로 본다
([ADR-0010](../docs/adr/0010-adopt-single-provider-in-city.md)). 상호는 합성이며 형태만
[이슈 #169](https://github.com/snowjaewon/OfficialDeliciousMap/issues/169)의 광주 실측과 같다.
"""

import pytest

from deliciousmap.merchants import (
    INCLUSION_MINIMUM,
    bare_name,
    inclusion_overlap,
    name_inclusion,
)

# 같은 업소로 보는 표기 짝과 그 겹침 글자 수.
INCLUDED = {
    # 글자까지 같은 표기. 길이와 무관하게 같은 업소다.
    ("합성식당", "합성식당"): 4,
    # 제공자가 지점명을 상호에 붙여 낸 표기. 원본의 이름이 앞에 그대로 붙어 있다.
    ("합성커피", "합성커피광주상무역"): 4,
    # 원본이 지점명까지 적고 제공자는 상호만 낸 표기. 짧은 쪽이 3자 이상이다.
    ("합성커피광주상무역", "합성커피"): 4,
    # 원본이 앞에 수식을 붙인 표기. 제공자의 이름이 뒤에 그대로 붙어 있다.
    ("전통합성국밥", "합성국밥"): 4,
    # 띄어쓰기·가운뎃점·법인 표기·괄호는 뼈대가 아니다.
    ("합성 식당", "㈜합성식당"): 4,
    ("(주)합성식당", "합성식당 (본점)"): 4,
    ("합성식당(상무점)", "합성식당"): 4,
    # 꼬리말을 뗀 이름으로 견준다. 꼬리말은 다른 업소의 수일 뿐 이름이 아니다.
    ("합성식당 외 1", "합성식당"): 4,
}
# 같은 업소로 보지 않는 표기 짝.
EXCLUDED = (
    # 중간에만 겹친다. `강가`는 `건강가정지원센터` 안에 있지만 그 업소의 앞도 뒤도 아니다.
    ("강가", "건강가정지원센터"),
    # 3자를 넘겨 중간에 겹쳐도 같은 업소가 아니다.
    ("성국밥", "합성국밥집"),
    # 2자 접미. `본가`가 뒤에 붙는 상호는 수없이 많다.
    ("본가", "죽본가"),
    # 2자 접두.
    ("합성", "합성식당"),
    # 겹치는 곳이 없다.
    ("합성식당", "합성카페"),
    # 뼈대가 남지 않는 표기는 무엇과도 같지 않다.
    ("(주)", "합성식당"),
    ("", "합성식당"),
)


@pytest.mark.parametrize(("first", "second"), sorted(INCLUDED))
def test_a_bare_name_that_starts_or_ends_the_other_is_the_same_place(
    first: str, second: str
) -> None:
    assert name_inclusion(first, second)
    assert name_inclusion(second, first)


@pytest.mark.parametrize(("first", "second"), sorted(INCLUDED))
def test_the_overlap_counts_the_letters_the_two_names_share(first: str, second: str) -> None:
    """겹침이 긴 후보를 먼저 고르므로 그 길이가 값으로 남는다."""
    assert inclusion_overlap(first, second) == INCLUDED[(first, second)]


@pytest.mark.parametrize(("first", "second"), sorted(EXCLUDED))
def test_a_middle_overlap_or_a_two_letter_edge_is_a_different_place(
    first: str, second: str
) -> None:
    assert not name_inclusion(first, second)
    assert not name_inclusion(second, first)
    assert inclusion_overlap(first, second) == 0


def test_the_bare_name_drops_only_the_notation_and_keeps_the_letters() -> None:
    """뼈대는 표기를 지우는 것이지 이름을 줄이는 것이 아니다. 지운 뒤 남는 글자는 그대로다."""
    assert bare_name("㈜합성 식당 (본점) 외 1") == "합성식당"
    assert bare_name("Cafe 합성") == "cafe합성"


def test_the_minimum_overlap_is_three_letters() -> None:
    """2자 접두·접미를 같은 업소로 보면 `본가`가 도시 안 모든 `…본가`를 가리킨다."""
    assert INCLUSION_MINIMUM == 3
    assert not name_inclusion("합성", "합성식당")
    assert name_inclusion("합성식", "합성식당")
