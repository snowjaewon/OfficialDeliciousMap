"""네이버 지역검색 어댑터. 인증·요청·응답 해석·제공자 오류를 감추고 후보 사실만 공급한다."""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from deliciousmap.contracts import PlaceCandidate, ProviderCandidates
from deliciousmap.identity import digest
from deliciousmap.places import in_korea, plain, split_branch
from deliciousmap.transport import MAX_RESPONSE_BYTES, HttpTransport, Transport

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
# 지역검색은 WGS84를 10^7배한 정수를 준다.
COORDINATE_SCALE = 1e7


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
    name = plain(str(item["title"]))
    merchant, branch = split_branch(name)
    address = plain(str(item.get("roadAddress") or item.get("address") or "")) or None
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


def _coordinates(mapy: object, mapx: object) -> tuple[float | None, float | None]:
    """좌표계를 확인할 수 있는 값만 경위도로 바꾼다. 그 밖의 값은 추측하지 않는다."""
    try:
        latitude = int(str(mapy)) / COORDINATE_SCALE
        longitude = int(str(mapx)) / COORDINATE_SCALE
    except ValueError:
        return None, None
    if in_korea(latitude, longitude):
        return latitude, longitude
    return None, None
