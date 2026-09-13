"""상호 끝의 `외 N` 꼬리말을 읽는 규칙.

꼬리말은 둘째 업소의 이름을 적지 않고 수만 밝힌다. 떼면 첫 업소가 남고, 이름 없는 업소의 수는
사실로 남는다([#127](https://github.com/snowjaewon/OfficialDeliciousMap/issues/127)).
상호는 합성이며 형태만 광주에서 실측한 것과 같다. 실측 표기는
[이슈 #127 검증](../docs/validation/issue-127.md)에 있다.
"""

import pytest

from deliciousmap.merchants import Companions, read

# 실측한 다섯 꼬리말 형태와 맨끝 `외`. 공백이 있는 표기와 없는 표기가 섞여 있다.
TAILS = {
    "합성식당 외 1": Companions("합성식당", 1),
    "합성카페외 1": Companions("합성카페", 1),
    "합성베이커리 본점외 1": Companions("합성베이커리 본점", 1),
    "합성회식당 외 2": Companions("합성회식당", 2),
    "합성보쌈외 1개소": Companions("합성보쌈", 1),
    "합성매운탕외1개소": Companions("합성매운탕", 1),
    "합성어장 외 1곳": Companions("합성어장", 1),
    "합성한정식 외 1명": Companions("합성한정식", 1),
    "합성감자탕 외 1개": Companions("합성감자탕", 1),
    # 원본이 수를 적지 않았다. 몇 곳인지 모르는 것을 0곳이나 1곳으로 적지 않는다.
    "합성낙지 외": Companions("합성낙지", None),
    "합성곰탕 합성이네 외": Companions("합성곰탕 합성이네", None),
}
# 꼬리말이 아닌 `외`. 이름 가운데나 낱말 안의 글자를 자르면 없는 상호를 조회하게 된다.
KEPT = (
    "외갓집",
    "합성해물외가",
    "외갓집 순두부 본점",
    "외 1",
    "외",
    # 맨끝 `외`이지만 앞에 공백이 없다. 낱말이 잘린 것인지 꼬리말인지 가를 근거가 없다.
    "합성로컬푸드직외",
    # 쉼표로 둘을 다 적은 표기는 가르는 일이며 #117 범위다. 여기서 떼지 않는다.
    "합성곰탕, 합성브라운외",
    "합성밥집, 합성데이지",
)


@pytest.mark.parametrize("merchant", sorted(TAILS))
def test_a_tail_names_the_first_place_and_counts_the_unnamed_rest(merchant: str) -> None:
    assert read(merchant) == TAILS[merchant]


@pytest.mark.parametrize("merchant", sorted(KEPT))
def test_an_inner_or_word_internal_oe_is_never_cut(merchant: str) -> None:
    """꼬리말이 아닌 `외`는 상호의 글자다. 이름이 잘리면 없는 업소를 조회한다."""
    assert read(merchant) == Companions(merchant, 0)


def test_a_merchant_without_a_tail_is_passed_through_unchanged() -> None:
    """꼬리말이 없는 상호는 글자 하나 바뀌지 않는다. 기존 확정 판정이 그대로 유지된다."""
    assert read("같은 식당") == Companions("같은 식당", 0)


def test_an_unwritten_count_is_not_reported_as_none_missing() -> None:
    """수를 적지 않은 꼬리말의 0곳은 없는 사실이다. 알 수 없음과 0곳을 가른다."""
    assert read("합성낙지 외").unnamed is None
    assert read("합성낙지").unnamed == 0


def test_a_counted_tail_is_cut_even_when_a_word_happens_to_end_in_the_same_letter() -> None:
    """수를 적은 꼬리말은 공백 없이도 뗀다. 그 대가로 `외`로 끝나는 낱말 뒤의 수도 잘린다.

    광주 실측에는 이런 표기가 없다. 공백을 요구하면 `합성카페외 1` 같은 실제 표기를 못 뗀다.
    잘린 이름은 후보를 못 얻거나 근거와 어긋나 미확정으로 남을 뿐, 다른 업소를 확정하지는
    않는다(`identity.decide_identity`가 상호·지점·주소의 독립 근거를 요구한다).
    """
    assert read("합성해외 2") == Companions("합성해", 2)
