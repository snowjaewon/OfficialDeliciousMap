"""Local refined-input stages. No HTTP, originals, LLM or budget operations."""

import json
import os

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
    ParseInput,
    ParseOutput,
)
from deliciousmap.identity import decide_identity, lookup_key, reconcile_coordinates
from deliciousmap.pipeline import AdapterFailure, ExecutionContext, FailureCause
from deliciousmap.site import write_site_shell
from deliciousmap.storage import schema_version, write_text


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
        write_text(
            marker_path,
            json.dumps(
                {
                    "schema_version": schema_version("build"),
                    "city": context.target.city.slug,
                    "org": context.target.org,
                    "markers": [
                        {
                            "business_id": candidate.business_id,
                            "merchant": candidate.merchant,
                            "visit_count": len(candidate.record_ids),
                            "latitude": candidate.latitude,
                            "longitude": candidate.longitude,
                            "closed": closure_by_business[candidate.business_id].status == "closed",
                        }
                        for candidate in value.candidates
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
        )
        ledger_path = directory / "ledger.json"
        decision_by_record = {item.record_id: item for item in value.decisions}
        geocode_by_record = {item.record_id: item for item in value.geocodes}

        def map_status(record_id: str) -> str:
            classification = decision_by_record[record_id].status
            if classification != "restaurant":
                return classification
            return (
                "mapped" if geocode_by_record[record_id].status == "success" else "geocode_failed"
            )

        write_text(
            ledger_path,
            json.dumps(
                {
                    "schema_version": schema_version("build"),
                    "city": context.target.city.slug,
                    "org": context.target.org,
                    "records": [
                        {
                            **record.model_dump(mode="json"),
                            "classification": decision_by_record[record.record_id].status,
                            "map_status": map_status(record.record_id),
                        }
                        for record in value.records
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
        )
        site_files = write_site_shell(
            context.paths.output_root,
            context.target.city,
            directory,
            naver_map_client_id=os.environ.get("NAVER_MAP_CLIENT_ID", ""),
            naver_map_key_param=os.environ.get("NAVER_MAP_KEY_PARAM", "ncpKeyId"),
            site_root="../../../" if context.target.org else "../",
        )
        return BuildOutput(
            files=(marker_path, ledger_path, *site_files),
            record_count=len(value.records),
            marker_count=len(value.candidates),
        )
