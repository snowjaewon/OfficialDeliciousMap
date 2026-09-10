"""City declarations; real boards are added only after verification."""

import re
from dataclasses import dataclass


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


@dataclass(frozen=True)
class City:
    slug: str
    name: str
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
