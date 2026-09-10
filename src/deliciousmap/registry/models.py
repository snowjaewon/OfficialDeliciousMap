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

    @property
    def organizations(self) -> tuple[Organization, ...]:
        return tuple(
            org for org in self.city.organizations if self.org is None or org.slug == self.org
        )


def select_target(cities: tuple[City, ...], city_slug: str, org: str | None) -> Target:
    for city in cities:
        if city.slug == city_slug:
            if not re.fullmatch(r"[a-z][a-z0-9-]*", city_slug):
                break
            if org is not None and (
                not re.fullmatch(r"[a-z][a-z0-9-]*", org)
                or org not in {item.slug for item in city.organizations}
            ):
                break
            return Target(city, org)
    raise ValueError("invalid city or organization selection")
