"""Local refined-input stages. No HTTP, originals, LLM or budget operations."""

import json
from pathlib import Path

from deliciousmap.contracts import (
    BuildInput,
    BuildOutput,
    ClassifyInput,
    ClassifyOutput,
    ClosureInput,
    ClosureOutput,
    ClosureResult,
    FetchInput,
    FetchOutput,
    GeocodeInput,
    GeocodeOutput,
    HeaderMapInput,
    HeaderMapOutput,
    MarkerFile,
    ParseInput,
    ParseOutput,
    PublishedMarker,
    RecordFile,
)
from deliciousmap.identity import decide_identity, lookup_key, reconcile_coordinates
from deliciousmap.pipeline import AdapterFailure, ExecutionContext, FailureCause
from deliciousmap.site import (
    coordinate_source,
    coverage,
    published_record,
    write_site_shell,
)
from deliciousmap.storage import write_text


class LocalAdapters:
    def fetch(self, value: FetchInput, context: ExecutionContext) -> FetchOutput:
        raise AdapterFailure(FailureCause.NOT_IMPLEMENTED)

    def headermap(self, value: HeaderMapInput, context: ExecutionContext) -> HeaderMapOutput:
        raise AdapterFailure(FailureCause.NOT_IMPLEMENTED)

    def parse(self, value: ParseInput, context: ExecutionContext) -> ParseOutput:
        raise AdapterFailure(FailureCause.NOT_IMPLEMENTED)

    def classify(self, value: ClassifyInput, context: ExecutionContext) -> ClassifyOutput:
        raise AdapterFailure(FailureCause.NOT_IMPLEMENTED)

    def geocode(self, value: GeocodeInput, context: ExecutionContext) -> GeocodeOutput:
        lookups = {item.scope.record_id: item for item in value.lookups}
        confirmations = {item.scope.record_id: item for item in value.confirmations}
        restorations = {item.record_id: item for item in value.restorations}
        previous = {item.lookup_key: item for item in value.previous}
        results = []
        for record in value.records:
            lookup = lookups[record.record_id]
            confirmation = confirmations.get(record.record_id)
            restored = restorations.get(record.record_id)
            key = lookup_key(record, lookup, confirmation, restored, value.dependency_key)
            cached = previous.get(key)
            if cached is not None and (cached.status == "success" or not value.retry_failed):
                results.append(cached)
            else:
                results.append(
                    decide_identity(
                        record,
                        lookup,
                        confirmation,
                        restored,
                        dependency_key=value.dependency_key,
                    )
                )
        return GeocodeOutput(results=reconcile_coordinates(tuple(results)))

    def closure(self, value: ClosureInput, context: ExecutionContext) -> ClosureOutput:
        return ClosureOutput(
            results=tuple(
                ClosureResult(
                    business_id=candidate.business_id,
                    status="unknown",
                    evidence="license-evidence-not-supplied",
                )
                for candidate in value.candidates
            )
        )

    def build(self, value: BuildInput, context: ExecutionContext) -> BuildOutput:
        directory = context.paths.output_root / context.target.city.slug
        if context.target.org:
            directory = directory / "orgs" / context.target.org
        marker_path = directory / "markers.json"
        closure_by_business = {item.business_id: item for item in value.closures}
        geocode_by_record = {item.record_id: item for item in value.geocodes}
        marker_file = MarkerFile(
            city=context.target.city.slug,
            org=context.target.org,
            markers=tuple(
                PublishedMarker(
                    business_id=candidate.business_id,
                    merchant=candidate.merchant,
                    visit_count=len(candidate.record_ids),
                    latitude=candidate.latitude,
                    longitude=candidate.longitude,
                    closed=closure_by_business[candidate.business_id].status == "closed",
                    # 묶인 레코드는 같은 좌표를 공유하므로 첫 레코드의 근거로 출처를 밝힌다.
                    coordinate_source=coordinate_source(geocode_by_record[candidate.record_ids[0]]),
                )
                for candidate in value.candidates
            ),
        )
        write_text(
            marker_path,
            json.dumps(
                marker_file.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
        )
        record_path = directory / "records.json"
        decision_by_record = {item.record_id: item for item in value.decisions}

        record_file = RecordFile(
            city=context.target.city.slug,
            org=context.target.org,
            records=tuple(
                published_record(
                    record,
                    decision_by_record[record.record_id].status,
                    geocode_by_record.get(record.record_id),
                )
                for record in value.records
            ),
        )
        write_text(
            record_path,
            json.dumps(record_file.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            + "\n",
        )
        # 기관 실행은 도시 전체 화면을 덮어쓰지 않도록 데이터 파일만 낸다.
        site_files: tuple[Path, ...] = ()
        if context.target.org is None:
            if context.map_key is None:
                raise ValueError("the map shell requires a configured public map key")
            site_files = write_site_shell(
                context.paths.output_root,
                context.target.city,
                directory,
                context.map_key,
                coverage(context.target.organizations, value.records),
            )
        return BuildOutput(
            files=(marker_path, record_path, *site_files),
            record_count=len(value.records),
            marker_count=len(value.candidates),
        )
