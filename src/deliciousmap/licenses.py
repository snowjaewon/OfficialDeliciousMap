"""인허가 조회 어댑터. 인증·요청·좌표계·제공자 오류를 감추고 후보 사실만 공급한다."""

import functools
import json
import math
import os
from collections.abc import Mapping

from pyproj import Transformer

from deliciousmap.contracts import PlaceCandidate, ProviderCandidates
from deliciousmap.places import in_korea, plain, split_branch
from deliciousmap.transport import MAX_RESPONSE_BYTES, HttpTransport, Transport

PROVIDER = "license"
# 응답 해석 규칙·조회 업종이 바뀌면 올린다. 조회 캐시는 이 버전을 구별한다.
INTERPRETATION_VERSION = "food-license-1"
# localdata.go.kr은 2026-04-16 종료했다. 인허가 자료는 공공데이터포털의 조회서비스로 받는다.
BASE_URL = "https://apis.data.go.kr/1741000"
# 마커가 될 수 있는 업종만 본다. 카페는 휴게음식점, 빵집·떡집은 제과점영업에만 있다.
SERVICES = ("general_restaurants", "rest_cafes", "bakeries")
KEY_VARIABLE = "DATA_GO_KR_KEY"
# 조회서비스는 한 쪽에 최대 100건을 준다. 이 경로는 첫 쪽만 본다.
RESULT_LIMIT = 100
SUCCESS_CODE = "200"
# 좌표정보는 보정계수 없는 Bessel 중부원점TM이다. 위경도는 제공하지 않는다.
COORDINATE_REFERENCE = "EPSG:5174"


class ServiceError(Exception):
    """제공자가 문서로 알린 실패. 원문·상태 코드는 남기지 않는다."""


@functools.cache
def _to_wgs84() -> Transformer:
    return Transformer.from_crs(COORDINATE_REFERENCE, "EPSG:4326", always_xy=True)


class FoodLicenseSearch:
    provider = PROVIDER
    interpretation = INTERPRETATION_VERSION

    def __init__(self, key: str, transport: Transport, limit: int = RESULT_LIMIT) -> None:
        # 비밀값이다. 요청 밖으로 내보내지 않는다.
        self._key = key
        self.transport = transport
        self.limit = limit

    def search(self, query: str) -> ProviderCandidates:
        """업종마다 한 쪽씩 조회한다. 한 업종이라도 실패하면 조회 전체를 실패로 남긴다."""
        candidates: list[PlaceCandidate] = []
        for service in SERVICES:
            try:
                body = self.transport.fetch(
                    f"{BASE_URL}/{service}/info",
                    {
                        "serviceKey": self._key,
                        "pageNo": "1",
                        "numOfRows": str(self.limit),
                        "returnType": "json",
                        "cond[BPLC_NM::LIKE]": query,
                    },
                    {"Accept": "application/json"},
                )
            except Exception:
                return ProviderCandidates(status="error", error="unavailable")
            try:
                candidates.extend(_interpret(body, service))
            except ServiceError:
                return ProviderCandidates(status="error", error="unavailable")
            except (ValueError, TypeError, LookupError, UnicodeDecodeError):
                return ProviderCandidates(status="error", error="invalid_response")
        return ProviderCandidates(status="ok", candidates=tuple(candidates))


def from_environment(
    transport: Transport | None = None, environ: Mapping[str, str] | None = None
) -> FoodLicenseSearch | None:
    """키가 없으면 조회를 구성하지 않고 담당자가 준비한 후보만 쓴다."""
    values = os.environ if environ is None else environ
    key = values.get(KEY_VARIABLE, "").strip()
    if not key:
        return None
    return FoodLicenseSearch(key, transport or HttpTransport())


def _interpret(body: bytes, service: str) -> tuple[PlaceCandidate, ...]:
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("oversized lookup response")
    response = json.loads(body.decode("utf-8"))["response"]
    if str(response["header"]["resultCode"]) != SUCCESS_CODE:
        raise ServiceError("the license service reported a failure")
    items = response["body"]["items"]
    rows = items.get("item", []) if isinstance(items, dict) else items
    # 결과가 없으면 빈 문자열이나 빈 목록으로, 한 건이면 목록 없이 객체 하나로 올 수 있다.
    if rows is None or rows == "":
        rows = []
    elif isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise TypeError("lookup response items must be a list")
    return tuple(_candidate(row, service) for row in rows)


def _candidate(row: object, service: str) -> PlaceCandidate:
    if not isinstance(row, dict):
        raise TypeError("lookup item must be an object")
    merchant, branch = split_branch(plain(str(row["BPLC_NM"])))
    address = plain(str(row.get("ROAD_NM_ADDR") or row.get("LOTNO_ADDR") or "")) or None
    latitude, longitude = _coordinates(row.get("CRD_INFO_X"), row.get("CRD_INFO_Y"))
    return PlaceCandidate.model_validate(
        {
            "source": {
                "provider": PROVIDER,
                # 인허가 자료 안의 관리번호일 뿐 업소 동일성의 근거는 아니다.
                "source_id": f"{service}/{plain(str(row['MNG_NO']))}",
                "reference": f"{BASE_URL}/{service}/info",
            },
            "merchant": merchant,
            "branch": branch,
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
        }
    )


def _coordinates(x: object, y: object) -> tuple[float | None, float | None]:
    """중부원점TM 좌표만 경위도로 바꾼다. 확인할 수 없는 값은 추측하지 않는다."""
    try:
        easting, northing = float(str(x)), float(str(y))
    except ValueError:
        return None, None
    # 좌표를 싣지 않은 행은 빈 값이나 0으로 온다. 원점 좌표를 업소 위치로 보지 않는다.
    if not (math.isfinite(easting) and math.isfinite(northing)) or 0 in (easting, northing):
        return None, None
    longitude, latitude = _to_wgs84().transform(easting, northing)
    if not (math.isfinite(latitude) and math.isfinite(longitude)) or not in_korea(
        latitude, longitude
    ):
        return None, None
    return latitude, longitude
