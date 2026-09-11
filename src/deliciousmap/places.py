"""후보 표기와 좌표 해석의 공통 규칙. 특정 제공자의 자료형이나 어댑터에 기대지 않는다."""

import html
import re

# 마지막 낱말이 지점명이면 상호와 나눈다. 그 밖의 이름은 임의로 쪼개지 않는다.
_BRANCH = re.compile(r"\S*[가-힣A-Za-z0-9]점")
_TAG = re.compile(r"<[^>]*>")
# 좌표계를 확인하는 범위. 한반도 밖의 값은 해석하지 않고 보류한다.
LATITUDE_RANGE = (32.0, 40.0)
LONGITUDE_RANGE = (124.0, 132.0)


def plain(value: str) -> str:
    """검색어 강조 표시와 문자 참조를 걷어낸다. 표기 자체는 바꾸지 않는다."""
    return " ".join(html.unescape(_TAG.sub("", value)).split())


def split_branch(name: str) -> tuple[str, str]:
    """등록된 장소 이름의 지점명만 분리한다. 지점명이 없으면 지점 없는 업소로 본다."""
    merchant, _, last = name.rpartition(" ")
    if merchant and _BRANCH.fullmatch(last):
        return merchant, last
    return name, ""


def in_korea(latitude: float, longitude: float) -> bool:
    return (
        LATITUDE_RANGE[0] <= latitude < LATITUDE_RANGE[1]
        and LONGITUDE_RANGE[0] <= longitude < LONGITUDE_RANGE[1]
    )
