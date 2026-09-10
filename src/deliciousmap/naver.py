"""네이버 지역검색 어댑터. 인증·요청·응답 해석·제공자 오류를 감추고 후보 사실만 공급한다."""

import html
import json
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from deliciousmap.contracts import PlaceCandidate, ProviderCandidates
from deliciousmap.identity import digest

PROVIDER = "naver"
# 응답 해석 규칙이 바뀌면 올린다. 조회 캐시는 이 버전을 구별한다.
INTERPRETATION_VERSION = "naver-local-1"
# NAVER API HUB의 지역검색. 개발자센터 구형 엔드포인트·헤더는 쓰지 않는다.
SEARCH_URL = "https://naverapihub.apigw.ntruss.com/search/v1/local"
KEY_ID_HEADER = "X-NCP-APIGW-API-KEY-ID"
KEY_HEADER = "X-NCP-APIGW-API-KEY"
CLIENT_ID_VARIABLE = "NAVER_SEARCH_CLIENT_ID"
CLIENT_SECRET_VARIABLE = "NAVER_SEARCH_CLIENT_SECRET"
# 지역검색은 한 요청에 최대 5건을 주고 다음 페이지를 제공하지 않는다.
RESULT_LIMIT = 5
MAX_RESPONSE_BYTES = 1_000_000
REQUEST_TIMEOUT = 10.0

_TAG = re.compile(r"<[^>]*>")
# 마지막 낱말이 지점명이면 상호와 나눈다. 그 밖의 이름은 임의로 쪼개지 않는다.
_BRANCH = re.compile(r"\S*[가-힣A-Za-z0-9]점")
# 좌표계 확인용 범위. 지역검색은 WGS84를 10^7배한 정수를 준다.
_LATITUDE = range(320_000_000, 400_000_000)
_LONGITUDE = range(1_240_000_000, 1_320_000_000)


class Transport(Protocol):
    """HTTP 경계. 테스트는 이 자리에 응답만 주입하고 어댑터는 그대로 실행한다."""

    def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes: ...


class HttpTransport:
    def __init__(self, timeout: float = REQUEST_TIMEOUT) -> None:
        self.timeout = timeout

    def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes:
        request = urllib.request.Request(
            f"{url}?{urllib.parse.urlencode(dict(params))}", headers=dict(headers)
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return bytes(response.read(MAX_RESPONSE_BYTES + 1))


@dataclass(frozen=True)
class Credentials:
    """비밀값이다. 로그·산출물·예외에 남지 않도록 표현을 숨긴다."""

    key_id: str = field(repr=False)
    key: str = field(repr=False)


class NaverPlaceSearch:
    provider = PROVIDER
    interpretation = INTERPRETATION_VERSION

    def __init__(
        self, credentials: Credentials, transport: Transport, limit: int = RESULT_LIMIT
    ) -> None:
        self.credentials = credentials
        self.transport = transport
        self.limit = limit

    def search(self, query: str) -> ProviderCandidates:
        """제공자 오류를 안전한 코드로 바꾼다. 요청 맥락의 도시는 질의에 넣지 않는다."""
        try:
            body = self.transport.fetch(
                SEARCH_URL,
                {"query": query, "display": str(self.limit), "start": "1"},
                {
                    KEY_ID_HEADER: self.credentials.key_id,
                    KEY_HEADER: self.credentials.key,
                    "Accept": "application/json",
                },
            )
        except Exception:
            return ProviderCandidates(status="error", error="unavailable")
        try:
            return ProviderCandidates(status="ok", candidates=_interpret(body))
        except (ValueError, TypeError, LookupError, UnicodeDecodeError):
            return ProviderCandidates(status="error", error="invalid_response")


def from_environment(
    transport: Transport | None = None, environ: Mapping[str, str] | None = None
) -> NaverPlaceSearch | None:
    """키가 모두 없으면 조회를 구성하지 않고, 한쪽만 있으면 설정 오류로 알린다."""
    values = os.environ if environ is None else environ
    key_id = values.get(CLIENT_ID_VARIABLE, "").strip()
    key = values.get(CLIENT_SECRET_VARIABLE, "").strip()
    if not key_id and not key:
        return None
    missing = [
        name
        for name, value in ((CLIENT_ID_VARIABLE, key_id), (CLIENT_SECRET_VARIABLE, key))
        if not value
    ]
    if missing:
        raise ValueError(f"incomplete naver search credentials: {', '.join(missing)}")
    return NaverPlaceSearch(Credentials(key_id, key), transport or HttpTransport())


def _interpret(body: bytes) -> tuple[PlaceCandidate, ...]:
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("oversized lookup response")
    items = json.loads(body.decode("utf-8"))["items"]
    if not isinstance(items, list):
        raise TypeError("lookup response items must be a list")
    return tuple(_candidate(item) for item in items)


def _candidate(item: object) -> PlaceCandidate:
    if not isinstance(item, dict):
        raise TypeError("lookup item must be an object")
    name = _plain(str(item["title"]))
    merchant, branch = _split_branch(name)
    address = _plain(str(item.get("roadAddress") or item.get("address") or "")) or None
    latitude, longitude = _coordinates(item.get("mapy"), item.get("mapx"))
    reference = str(item.get("link") or "").strip() or SEARCH_URL
    return PlaceCandidate.model_validate(
        {
            "source": {
                "provider": PROVIDER,
                "source_id": digest([INTERPRETATION_VERSION, name, address]),
                "reference": reference,
            },
            "merchant": merchant,
            "branch": branch,
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
        }
    )


def _plain(value: str) -> str:
    """검색어 강조 표시와 문자 참조를 걷어낸다. 표기 자체는 바꾸지 않는다."""
    return " ".join(html.unescape(_TAG.sub("", value)).split())


def _split_branch(name: str) -> tuple[str, str]:
    """등록된 장소 이름의 지점명만 분리한다. 지점명이 없으면 지점 없는 업소로 본다."""
    merchant, _, last = name.rpartition(" ")
    if merchant and _BRANCH.fullmatch(last):
        return merchant, last
    return name, ""


def _coordinates(mapy: object, mapx: object) -> tuple[float | None, float | None]:
    """좌표계를 확인할 수 있는 값만 경위도로 바꾼다. 그 밖의 값은 추측하지 않는다."""
    try:
        latitude, longitude = int(str(mapy)), int(str(mapx))
    except ValueError:
        return None, None
    if latitude in _LATITUDE and longitude in _LONGITUDE:
        return latitude / 1e7, longitude / 1e7
    return None, None
