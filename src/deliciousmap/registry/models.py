"""City declarations; real boards are added only after verification."""

import re
from dataclasses import dataclass
from typing import Literal, get_args

# 수집 보류 사유의 단일 출처. CONTEXT.md의 네 가지 외에는 보류로 남기지 않는다.
HoldReason = Literal["bot_blocked", "drm", "board_lost", "below_threshold"]


@dataclass(frozen=True)
class Board:
    slug: str
    url: str
    scraper: type


@dataclass(frozen=True)
class Organization:
    slug: str
    name: str
    boards: tuple[Board, ...] = ()
    # 사유를 달고 이번 수집에서 미룬 기관. 상호의 판단 보류와 다른 상태다.
    hold_reason: HoldReason | None = None

    def __post_init__(self) -> None:
        if self.hold_reason is not None and self.hold_reason not in get_args(HoldReason):
            raise ValueError("unknown collection hold reason")


@dataclass(frozen=True)
class MapBounds:
    south: float
    west: float
    north: float
    east: float

    def __post_init__(self) -> None:
        if not (-90 <= self.south < self.north <= 90):
            raise ValueError("invalid city latitude bounds")
        if not (-180 <= self.west < self.east <= 180):
            raise ValueError("invalid city longitude bounds")


@dataclass(frozen=True)
class City:
    slug: str
    name: str
    map_bounds: MapBounds
    organizations: tuple[Organization, ...] = ()


@dataclass(frozen=True)
class Target:
    city: City
    org: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", self.city.slug):
            raise ValueError("invalid city selection")
        if self.org is not None and (
            not re.fullmatch(r"[a-z][a-z0-9-]*", self.org)
            or self.org not in {item.slug for item in self.city.organizations}
        ):
            raise ValueError("invalid organization selection")

    @property
    def organizations(self) -> tuple[Organization, ...]:
        return tuple(
            org for org in self.city.organizations if self.org is None or org.slug == self.org
        )


def select_target(cities: tuple[City, ...], city_slug: str, org: str | None) -> Target:
    for city in cities:
        if city.slug == city_slug:
            return Target(city, org)
    raise ValueError("invalid city or organization selection")
