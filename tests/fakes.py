"""Synthetic adapters, deliberately unavailable from the production package."""

import json
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
