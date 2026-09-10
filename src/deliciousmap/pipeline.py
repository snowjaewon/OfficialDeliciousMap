"""Stage orchestration. All service operations cross the Adapters boundary."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

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
from deliciousmap.storage import ArtifactStore

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


class Adapters(Protocol):
    def fetch(self, value: FetchInput, context: ExecutionContext) -> FetchOutput: ...
    def headermap(self, value: HeaderMapInput, context: ExecutionContext) -> HeaderMapOutput: ...
    def parse(self, value: ParseInput, context: ExecutionContext) -> ParseOutput: ...
    def classify(self, value: ClassifyInput, context: ExecutionContext) -> ClassifyOutput: ...
    def geocode(self, value: GeocodeInput, context: ExecutionContext) -> GeocodeOutput: ...
    def closure(self, value: ClosureInput, context: ExecutionContext) -> ClosureOutput: ...
    def build(self, value: BuildInput, context: ExecutionContext) -> BuildOutput: ...


def restaurant_merchants(
    records: tuple[Record, ...], decisions: tuple[Classification, ...]
) -> tuple[str, ...]:
    included = {item.record_id for item in decisions if item.status == "restaurant"}
    return tuple(
        dict.fromkeys(record.merchant for record in records if record.record_id in included)
    )


def marker_candidates(
    records: tuple[Record, ...], decisions: tuple[Classification, ...], geocodes: GeocodeOutput
) -> tuple[MarkerCandidate, ...]:
    included = {item.record_id for item in decisions if item.status == "restaurant"}
    return tuple(
        MarkerCandidate(
            merchant=geo.merchant,
            record_ids=tuple(
                record.record_id
                for record in records
                if record.merchant == geo.merchant and record.record_id in included
            ),
            latitude=geo.latitude,
            longitude=geo.longitude,
        )
        for geo in geocodes.results
        if geo.status == "success" and geo.latitude is not None and geo.longitude is not None
    )


def execute(
    command: str, context: ExecutionContext, adapters: Adapters | None = None
) -> StageOutput:
    if command not in (*STAGES, "run"):
        raise ValueError("unknown stage")
    context.paths.validate()
    result: StageOutput
    for stage in STAGES if command == "run" else (command,):
        if adapters is None:
            raise PipelineFailure(stage, context.target, FailureCause.NOT_IMPLEMENTED)
        try:
            result = _execute_one(stage, context, adapters)
        except AdapterFailure as exc:
            raise PipelineFailure(stage, context.target, exc.cause) from None
        except (ValueError, TypeError, KeyError):
            raise PipelineFailure(stage, context.target, FailureCause.INVALID_ARTIFACT) from None
        except OSError:
            raise PipelineFailure(stage, context.target, FailureCause.IO_ERROR) from None
        except Exception:
            raise PipelineFailure(stage, context.target, FailureCause.ADAPTER_FAILED) from None
    return result


def _execute_one(command: str, context: ExecutionContext, adapters: Adapters) -> StageOutput:
    context.paths.validate()
    store = ArtifactStore(context.paths, context.target)
    result: StageOutput
    for stage in STAGES if command == "run" else (command,):
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
                    ClassifyInput(records=parsed.records, manual=store.manual()), context
                )
            case "geocode":
                parsed = store.load("parse", ParseOutput)
                classified = store.load("classify", ClassifyOutput)
                result = adapters.geocode(
                    GeocodeInput(
                        merchants=restaurant_merchants(parsed.records, classified.decisions),
                        previous=store.previous_geocodes(),
                        retry_failed=context.retry_failed,
                    ),
                    context,
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
        store.save(stage, result)
    return result
