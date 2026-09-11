"""Stage orchestration. All service operations cross the Adapters boundary."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from deliciousmap import comparison, lookup, restoration, site
from deliciousmap.budget import Budget
from deliciousmap.contracts import (
    BuildInput,
    BuildOutput,
    Classification,
    ClassifyInput,
    ClassifyOutput,
    ClosureInput,
    ClosureOutput,
    FetchInput,
    FetchOutput,
    GeocodeInput,
    GeocodeOutput,
    HeaderMapInput,
    HeaderMapOutput,
    MarkerCandidate,
    ParseInput,
    ParseOutput,
    Record,
)
from deliciousmap.paths import Paths
from deliciousmap.registry import Target
from deliciousmap.storage import ArtifactStore, RegenerationRequired

STAGES = ("fetch", "headermap", "parse", "classify", "geocode", "closure", "build")
StageOutput = (
    FetchOutput
    | HeaderMapOutput
    | ParseOutput
    | ClassifyOutput
    | GeocodeOutput
    | ClosureOutput
    | BuildOutput
)


class FailureCause(StrEnum):
    NOT_IMPLEMENTED = "not-implemented"
    INVALID_ARTIFACT = "invalid-artifact"
    IO_ERROR = "io-error"
    ADAPTER_FAILED = "adapter-failed"
    UNSUPPORTED_FORMAT = "unsupported-format"
    SERVICE_UNAVAILABLE = "service-unavailable"
    LOOKUP_FAILED = "lookup-failed"
    REGENERATION_REQUIRED = "regeneration-required"
    CONFLICTING_REVIEW = "conflicting-review"


class AdapterFailure(Exception):
    """Adapters may supply only a safe reason code, never raw service errors."""

    def __init__(self, cause: FailureCause) -> None:
        self.cause = cause
        super().__init__(cause.value)


class PipelineFailure(Exception):
    def __init__(self, stage: str, target: Target, cause: FailureCause) -> None:
        self.stage = stage
        self.target = target
        self.cause = cause
        super().__init__(
            f"{stage} city={target.city.slug} org={target.org or '*'} cause={cause.value}"
        )


@dataclass(frozen=True)
class ExecutionContext:
    target: Target
    paths: Paths
    retry_failed: bool = False
    # 구성된 후보 조회. 비어 있으면 담당자가 준비한 후보 파일만 사용한다.
    providers: tuple[lookup.CandidateProvider, ...] = ()
    # 구성된 후보 비교 모델. 없으면 담당자가 지정해도 비교를 수행하지 않는다.
    comparator: comparison.ComparisonModel | None = None
    # 화면을 렌더링하는 단계만 요구하는 공개 지도 키. CLI가 build·run 전에 확인한다.
    map_key: site.MapKey | None = None


class Adapters(Protocol):
    def fetch(self, value: FetchInput, context: ExecutionContext) -> FetchOutput: ...
    def headermap(self, value: HeaderMapInput, context: ExecutionContext) -> HeaderMapOutput: ...
    def parse(self, value: ParseInput, context: ExecutionContext) -> ParseOutput: ...
    def classify(self, value: ClassifyInput, context: ExecutionContext) -> ClassifyOutput: ...
    def geocode(self, value: GeocodeInput, context: ExecutionContext) -> GeocodeOutput: ...
    def closure(self, value: ClosureInput, context: ExecutionContext) -> ClosureOutput: ...
    def build(self, value: BuildInput, context: ExecutionContext) -> BuildOutput: ...


def restaurant_records(
    records: tuple[Record, ...], decisions: tuple[Classification, ...]
) -> tuple[Record, ...]:
    included = {item.record_id for item in decisions if item.status == "restaurant"}
    return tuple(record for record in records if record.record_id in included)


def marker_candidates(
    records: tuple[Record, ...], decisions: tuple[Classification, ...], geocodes: GeocodeOutput
) -> tuple[MarkerCandidate, ...]:
    included = {item.record_id for item in decisions if item.status == "restaurant"}
    grouped: dict[str, MarkerCandidate] = {}
    for geo in geocodes.results:
        if (
            geo.status != "success"
            or geo.record_id not in included
            or geo.business_id is None
            or geo.latitude is None
            or geo.longitude is None
        ):
            continue
        previous = grouped.get(geo.business_id)
        if previous and (previous.latitude, previous.longitude) != (geo.latitude, geo.longitude):
            raise ValueError("conflicting coordinates for a confirmed business")
        grouped[geo.business_id] = MarkerCandidate(
            business_id=geo.business_id,
            merchant=geo.confirmed_merchant or geo.merchant,
            record_ids=(*previous.record_ids, geo.record_id) if previous else (geo.record_id,),
            latitude=geo.latitude,
            longitude=geo.longitude,
        )
    return tuple(grouped.values())


def execute(
    command: str, context: ExecutionContext, adapters: Adapters | None = None
) -> StageOutput:
    if command not in (*STAGES, "run"):
        raise ValueError("unknown stage")
    context.paths.validate()
    if adapters is None:
        from deliciousmap.local import LocalAdapters

        adapters = LocalAdapters()
    result: StageOutput
    for stage in STAGES if command == "run" else (command,):
        try:
            result = _execute_one(stage, context, adapters)
        except AdapterFailure as exc:
            raise PipelineFailure(stage, context.target, exc.cause) from None
        except RegenerationRequired:
            raise PipelineFailure(
                stage, context.target, FailureCause.REGENERATION_REQUIRED
            ) from None
        except restoration.ConflictingReview:
            raise PipelineFailure(stage, context.target, FailureCause.CONFLICTING_REVIEW) from None
        except (ValueError, TypeError, KeyError):
            raise PipelineFailure(stage, context.target, FailureCause.INVALID_ARTIFACT) from None
        except OSError:
            raise PipelineFailure(stage, context.target, FailureCause.IO_ERROR) from None
        except Exception:
            raise PipelineFailure(stage, context.target, FailureCause.ADAPTER_FAILED) from None
    return result


def _execute_one(stage: str, context: ExecutionContext, adapters: Adapters) -> StageOutput:
    store = ArtifactStore(context.paths, context.target)
    result: StageOutput
    match stage:
        case "fetch":
            result = adapters.fetch(FetchInput(context.target), context)
        case "headermap":
            fetched = store.load("fetch", FetchOutput)
            result = adapters.headermap(HeaderMapInput(sources=fetched.sources), context)
        case "parse":
            fetched = store.load("fetch", FetchOutput)
            mapped = store.load("headermap", HeaderMapOutput)
            result = adapters.parse(
                ParseInput(sources=fetched.sources, mappings=mapped.mappings), context
            )
            result = ParseOutput.model_validate(result)
            source_targets = {
                (source.source_hash, source.organization) for source in fetched.sources
            }
            if any(
                (record.source_hash, record.organization) not in source_targets
                for record in result.records
            ):
                raise ValueError("record provenance does not match fetched originals")
        case "classify":
            parsed = store.load("parse", ParseOutput)
            result = adapters.classify(
                ClassifyInput(
                    records=parsed.records,
                    manual=store.manual(),
                    restorations=restoration.resolve(parsed.records, store.restorations()),
                ),
                context,
            )
        case "geocode":
            parsed = store.load("parse", ParseOutput)
            classified = store.load("classify", ClassifyOutput)
            # 확인 충돌은 마커 대상이 아닌 레코드에서도 알린다.
            confirmations = store.confirmations(parsed.records)
            reviewed = restoration.resolve(parsed.records, store.restorations())
            restoration.require_agreement(reviewed, confirmations)
            records = restaurant_records(parsed.records, classified.decisions)
            included = {record.record_id for record in records}
            restorations = tuple(item for item in reviewed if item.record_id in included)
            # 조회를 먼저 끝내고 의존성 키를 만든다. 새 후보가 이전 판정을 대신하지 못한다.
            lookups = lookup.resolve(
                store,
                records,
                store.candidate_lookups(records),
                restorations,
                context.providers,
                retry_failed=context.retry_failed,
            )
            result = adapters.geocode(
                GeocodeInput(
                    dependency_key=store.geocode_dependency_key(),
                    records=records,
                    lookups=lookups,
                    confirmations=tuple(
                        item for item in confirmations if item.scope.record_id in included
                    ),
                    restorations=restorations,
                    previous=store.previous_geocodes(),
                    retry_failed=context.retry_failed,
                ),
                context,
            )
            if context.comparator is not None:
                # 지정한 미해결 건만 비교하고 제안으로 남긴다. 판정과 마커는 바뀌지 않는다.
                comparison.resolve(
                    store,
                    Budget(context.paths.shared("llm-budget")),
                    context.comparator,
                    records,
                    lookups,
                    GeocodeOutput.model_validate(result).results,
                    store.designations(records),
                    retry_failed=context.retry_failed,
                )
        case "closure" | "build":
            parsed = store.load("parse", ParseOutput)
            classified = store.load("classify", ClassifyOutput)
            geocoded = store.load("geocode", GeocodeOutput)
            candidates = marker_candidates(parsed.records, classified.decisions, geocoded)
            if stage == "closure":
                result = adapters.closure(
                    ClosureInput(
                        candidates=candidates, license_root=context.paths.raw_root / "licenses"
                    ),
                    context,
                )
            else:
                closed = store.load("closure", ClosureOutput)
                result = adapters.build(
                    BuildInput(
                        records=parsed.records,
                        decisions=classified.decisions,
                        geocodes=geocoded.results,
                        closures=closed.results,
                        candidates=candidates,
                    ),
                    context,
                )
        case _:
            raise ValueError("unknown stage")
    store.save(stage, result, retry_failed=context.retry_failed)
    if isinstance(result, GeocodeOutput) and any(
        item.reason == "lookup_error" for item in result.results
    ):
        raise AdapterFailure(FailureCause.LOOKUP_FAILED)
    return result
