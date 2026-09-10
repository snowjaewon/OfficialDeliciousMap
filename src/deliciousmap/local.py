"""Local refined-input stages. No HTTP, originals, LLM or budget operations."""

import json

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
        path = directory / "markers.json"
        write_text(
            path,
            json.dumps(
                {
                    "schema_version": schema_version("build"),
                    "city": context.target.city.slug,
                    "org": context.target.org,
                    **value.model_dump(mode="json"),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
        )
        return BuildOutput(
            files=(path,), record_count=len(value.records), marker_count=len(value.candidates)
        )
