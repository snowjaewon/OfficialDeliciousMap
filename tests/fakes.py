"""Synthetic adapters, deliberately unavailable from the production package."""

import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from deliciousmap.contracts import (
    BuildInput,
    BuildOutput,
    CacheEntry,
    CacheRef,
    Classification,
    ClassifyInput,
    ClassifyOutput,
    ClosureInput,
    ClosureOutput,
    ClosureResult,
    FetchInput,
    FetchOutput,
    GeocodeInput,
    GeocodeOutput,
    HeaderMap,
    HeaderMapInput,
    HeaderMapOutput,
    ParseInput,
    ParseOutput,
    Record,
    SourceRef,
)
from deliciousmap.identity import decide_identity
from deliciousmap.pipeline import ExecutionContext
from deliciousmap.storage import append_cache, select_cache, write_text


class SyntheticAdapters:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.build_input: BuildInput | None = None
        self.classify_input: ClassifyInput | None = None
        self.cache_misses = 0
        self.geocode_lookups = 0

    def fetch(self, value: FetchInput, context: ExecutionContext) -> FetchOutput:
        self.calls.append("fetch")
        assert value.target.organizations[0].boards[0].url == "https://example.invalid/board"
        return FetchOutput(
            sources=(
                SourceRef(
                    path=context.paths.raw_root / "합성 원본.xlsx",
                    source_hash="a" * 64,
                    organization="test-org",
                    board="expenses",
                    url="https://example.invalid/expense/1",
                ),
            )
        )

    def headermap(self, value: HeaderMapInput, context: ExecutionContext) -> HeaderMapOutput:
        self.calls.append("headermap")
        source = value.sources[0]
        cache_path = context.paths.shared("headermap")
        key = "b" * 64
        entry = select_cache(cache_path, key)
        if entry is None:
            self.cache_misses += 1
            entry = CacheEntry(
                key=key,
                revision=1,
                valid=True,
                evidence="synthetic mapping",
                value={"layout": "table"},
            )
            append_cache(cache_path, entry)
        return HeaderMapOutput(
            mappings=(
                HeaderMap(
                    source_hash=source.source_hash,
                    table="sheet1",
                    layout="table",
                    header_rows=(1,),
                    data_start_row=2,
                    year_hint=2026,
                    columns={"spent_on": 0, "merchant": 1, "amount_krw": 2},
                    amount_multiplier=Decimal("1"),
                    cache=CacheRef(key=key, revision=entry.revision),
                ),
            )
        )

    def parse(self, value: ParseInput, context: ExecutionContext) -> ParseOutput:
        self.calls.append("parse")
        mapping = value.mappings[0]
        assert mapping.source_hash == value.sources[0].source_hash
        assert mapping.columns["merchant"] == 1
        return ParseOutput(
            records=tuple(
                Record(
                    record_id=f"r{index}",
                    spent_on=date(2026, 1, 2),
                    organization="test-org",
                    department="총무과",
                    merchant=name,
                    purpose="업무 협의",
                    amount_krw=Decimal("1000"),
                    source_hash=mapping.source_hash,
                    source_location=f"sheet1:R{index + 2}",
                )
                for index, name in enumerate(
                    ("합성 식당", "합성 마트", "모호한 상호", "좌표 없는 식당")
                )
            )
        )

    def classify(self, value: ClassifyInput, context: ExecutionContext) -> ClassifyOutput:
        self.calls.append("classify")
        self.classify_input = value
        statuses = {"r0": "restaurant", "r1": "non_restaurant", "r2": "pending", "r3": "restaurant"}
        # 조회는 확정 복원명으로 한다. 원본 표기는 레코드에 그대로 남는다.
        restored = {item.record_id: item.restored_merchant for item in value.restorations}
        write_text(
            context.paths.city_dir(context.target) / "geocode-input.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "lookups": [
                        {
                            "scope": {
                                "city": context.target.city.slug,
                                "organization": record.organization,
                                "record_id": record.record_id,
                                "source_hash": record.source_hash,
                            },
                            "status": "ok",
                            "facts": [
                                {
                                    "merchant": restored.get(record.record_id, record.merchant),
                                    "branch": "",
                                    "address": "합성로 1",
                                    "source": "https://example.invalid/disclosure",
                                }
                            ],
                            "candidates": [
                                {
                                    "source": {
                                        "provider": "local",
                                        "source_id": record.record_id,
                                        "reference": "https://example.invalid/place",
                                    },
                                    "merchant": restored.get(record.record_id, record.merchant),
                                    "branch": "",
                                    "address": "합성로 1",
                                    "latitude": 37.5 if record.record_id == "r0" else None,
                                    "longitude": 127.0 if record.record_id == "r0" else None,
                                }
                            ],
                        }
                        for record in value.records
                        if statuses[record.record_id] == "restaurant"
                    ],
                },
                ensure_ascii=False,
            ),
        )
        return ClassifyOutput(
            decisions=tuple(
                Classification.model_validate(
                    {
                        "record_id": record.record_id,
                        "status": statuses[record.record_id],
                        "evidence": "synthetic verdict",
                    }
                )
                for record in value.records
            )
        )

    def geocode(self, value: GeocodeInput, context: ExecutionContext) -> GeocodeOutput:
        self.calls.append("geocode")
        assert tuple(record.merchant for record in value.records) == ("합성 식당", "좌표 없는 식당")
        generated = tuple(
            decide_identity(record, lookup, dependency_key=value.dependency_key)
            for record, lookup in zip(value.records, value.lookups, strict=True)
        )
        previous = {item.lookup_key: item for item in value.previous}
        results = []
        for item in generated:
            cached = previous.get(item.lookup_key)
            if cached is not None and (cached.status == "success" or not value.retry_failed):
                results.append(cached)
            else:
                self.geocode_lookups += 1
                results.append(item)
        return GeocodeOutput(results=tuple(results))

    def closure(self, value: ClosureInput, context: ExecutionContext) -> ClosureOutput:
        self.calls.append("closure")
        assert [candidate.merchant for candidate in value.candidates] == ["합성 식당"]
        return ClosureOutput(
            results=(
                ClosureResult(
                    business_id=value.candidates[0].business_id,
                    status="closed",
                    evidence="synthetic license match",
                ),
            )
        )

    def build(self, value: BuildInput, context: ExecutionContext) -> BuildOutput:
        self.calls.append("build")
        self.build_input = value
        output = context.paths.output_root / context.target.city.slug / "synthetic.txt"
        write_text(output, "TEST ONLY\n" + "\n".join(record.record_id for record in value.records))
        return BuildOutput(
            files=(output,), record_count=len(value.records), marker_count=len(value.candidates)
        )


class FakeTransport:
    """네이버 응답만 대신한다. 인증 헤더 구성·요청·응답 해석은 실제 어댑터가 한다."""

    def __init__(self, *responses: bytes | Exception) -> None:
        self.responses = responses or (naver_body(),)
        self.urls: list[str] = []
        self.requests: list[dict[str, str]] = []
        self.headers: list[dict[str, str]] = []

    def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes:
        self.urls.append(url)
        self.requests.append(dict(params))
        self.headers.append(dict(headers))
        response = self.responses[min(len(self.requests), len(self.responses)) - 1]
        if isinstance(response, Exception):
            raise response
        return response


def naver_item(
    title: str,
    road_address: str,
    *,
    mapx: str = "1291000000",
    mapy: str = "351000000",
    link: str = "",
) -> dict[str, str]:
    """지역검색 응답 한 건. 실제 응답처럼 공급자 전용 필드도 함께 둔다."""
    return {
        "title": title,
        "link": link,
        "category": "음식점>한식",
        "description": "합성 설명",
        "telephone": "051-000-0000",
        "address": "부산 합성동 1-2",
        "roadAddress": road_address,
        "mapx": mapx,
        "mapy": mapy,
    }


def naver_body(*items: dict[str, str]) -> bytes:
    return json.dumps(
        {
            "lastBuildDate": "Thu, 10 Sep 2026 00:00:00 +0900",
            "total": len(items),
            "start": 1,
            "display": len(items),
            "items": list(items),
        },
        ensure_ascii=False,
    ).encode("utf-8")


# 인허가 조회서비스의 업종별 경로. 마커가 될 수 있는 세 업종만 쓴다.
LICENSE_SERVICES = ("general_restaurants", "rest_cafes", "bakeries")


def license_item(
    name: str,
    road_address: str,
    *,
    x: str = "391413.5",
    y: str = "179897.3",
    management: str = "3250000-101-2026-00001",
    lot_address: str = "부산 합성동 1-2",
) -> dict[str, str]:
    """조회서비스 응답 한 건. 실제 응답처럼 대조에 쓰지 않는 필드도 함께 둔다."""
    return {
        "OPN_ATMY_GRP_CD": "3250000",
        "MNG_NO": management,
        "BPLC_NM": name,
        "ROAD_NM_ADDR": road_address,
        "LOTNO_ADDR": lot_address,
        "SALS_STTS_NM": "영업/정상",
        "DTL_SALS_STTS_NM": "영업",
        "CLSBIZ_YMD": "",
        "CRD_INFO_X": x,
        "CRD_INFO_Y": y,
        "BZSTAT_SE_NM": "한식",
        "TELNO": "051-000-0000",
        "LCPMT_YMD": "20200101",
    }


def license_body(*items: dict[str, str], result_code: str = "200") -> bytes:
    return json.dumps(
        {
            "response": {
                "header": {"resultCode": result_code, "resultMsg": "NORMAL SERVICE"},
                "body": {
                    "dataType": "json",
                    "numOfRows": 100,
                    "pageNo": 1,
                    "totalCount": len(items),
                    "items": {"item": list(items)},
                },
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")


class FakeLicenseTransport:
    """인허가 응답만 대신한다. 업종별 경로를 구별하고 조회 회차마다 다음 응답을 준다."""

    def __init__(self, *responses: bytes | Exception, service: str = "general_restaurants") -> None:
        self.responses = responses or (license_body(),)
        self.service = service
        self.urls: list[str] = []
        self.requests: list[dict[str, str]] = []
        self.headers: list[dict[str, str]] = []
        self.rounds: dict[str, int] = {}

    def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes:
        self.urls.append(url)
        self.requests.append(dict(params))
        self.headers.append(dict(headers))
        slug = url.rstrip("/").split("/")[-2]
        self.rounds[slug] = attempt = self.rounds.get(slug, 0) + 1
        if slug != self.service:
            return license_body()
        response = self.responses[min(attempt, len(self.responses)) - 1]
        if isinstance(response, Exception):
            raise response
        return response
