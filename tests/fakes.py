"""Synthetic adapters, deliberately unavailable from the production package."""

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
    GeocodeResult,
    HeaderMap,
    HeaderMapInput,
    HeaderMapOutput,
    ParseInput,
    ParseOutput,
    Record,
    SourceRef,
)
from deliciousmap.pipeline import ExecutionContext
from deliciousmap.storage import append_cache, select_cache, write_text


class SyntheticAdapters:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.build_input: BuildInput | None = None
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
        statuses = {"r0": "restaurant", "r1": "non_restaurant", "r2": "pending", "r3": "restaurant"}
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
        assert value.merchants == ("합성 식당", "좌표 없는 식당")
        generated = (
            GeocodeResult(
                merchant=value.merchants[0],
                status="success",
                latitude=37.5,
                longitude=127.0,
                evidence="synthetic coordinates",
            ),
            GeocodeResult(
                merchant=value.merchants[1], status="failed", evidence="synthetic no match"
            ),
        )
        previous = {item.merchant: item for item in value.previous}
        results = []
        for item in generated:
            cached = previous.get(item.merchant)
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
                    merchant="합성 식당", status="closed", evidence="synthetic license match"
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
