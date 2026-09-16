"""Stage orchestration. All service operations cross the Adapters boundary."""

import errno
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from deliciousmap import (
    category,
    classify,
    comparison,
    headermap,
    lookup,
    restoration,
    site,
    submission,
)
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
from deliciousmap.transport import Transport

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
    MISSING_CONFIGURATION = "missing-configuration"


class AdapterFailure(Exception):
    """Adapters may supply only a safe reason code, never raw service errors."""

    def __init__(self, cause: FailureCause) -> None:
        self.cause = cause
        super().__init__(cause.value)


class PipelineFailure(Exception):
    def __init__(
        self, stage: str, target: Target, cause: FailureCause, diagnosis: str = ""
    ) -> None:
        self.stage = stage
        self.target = target
        self.cause = cause
        message = f"{stage} city={target.city.slug} org={target.org or '*'} cause={cause.value}"
        super().__init__(f"{message} {diagnosis}" if diagnosis else message)


def diagnose(error: BaseException, paths: Paths) -> str:
    """사유 코드로 접힌 예외에서 출력해도 안전한 진단만 뽑는다.

    안전하다고 보는 것은 코드가 정한 값뿐이다: 예외 클래스 이름, `errno`의 기호 이름,
    그리고 저장소·데이터·원본·출력 루트 아래로 확인된 실패 경로의 루트 상대 경로.
    원본 첨부 이름은 이미 커밋되는 수집 산출물에 실리므로 원본 루트 아래 경로도 남긴다.
    예외 메시지(`str(error)`, `strerror`, `KeyError`의 키)는 원본 내용·비밀값·제공자 응답
    본문을 담을 수 있으므로 어떤 경우에도 남기지 않는다. 알려진 루트 밖의 경로와 URL도
    남기지 않는다.
    """
    parts = [f"error={type(error).__name__}"]
    if isinstance(error, OSError):
        if isinstance(error.errno, int) and error.errno in errno.errorcode:
            parts.append(f"errno={errno.errorcode[error.errno]}")
        for key, name in (("path", error.filename), ("path2", error.filename2)):
            relative = _root_relative(name, paths)
            if relative:
                parts.append(f"{key}={relative}")
    return " ".join(parts)


def _root_relative(name: object, paths: Paths) -> str | None:
    if not isinstance(name, str | os.PathLike):
        return None
    # `HTTPError`는 filename에 요청 URL(질의 문자열 포함)을 담는다. 상대 경로로 읽히지 않게
    # 스킴이 있는 이름은 버린다. 한 글자 스킴은 Windows 드라이브 문자다.
    if len(urlsplit(os.fspath(name)).scheme) > 1:
        return None
    try:
        path = Path(name).resolve()
    except (OSError, ValueError, TypeError):
        return None
    for label, root in (
        ("", paths.repository),
        ("data-root/", paths.data_root),
        ("raw-root/", paths.raw_root),
        ("output-root/", paths.output_root),
    ):
        base = root.resolve()
        if path.is_relative_to(base):
            return label + path.relative_to(base).as_posix()
    return None


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
    # 게시판 요청 경계. 테스트는 이 자리에 응답만 주입하고 수집 규칙은 그대로 실행한다.
    board_transport: Transport | None = None
    # 구성된 헤더 매핑·비식당 판별 모델. 없으면 캐시만 쓰고 나머지는 미해결·판단 보류로 남긴다.
    header_mapper: headermap.HeaderMapper | None = None
    classifier: classify.Classifier | None = None
    # 구성된 업종 조회. 비어 있으면 캐시에 쌓인 업종만 쓰고 나머지 마커는 `미상`으로 남긴다.
    category_sources: tuple[category.CategorySource, ...] = ()


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
        except Exception as exc:
            # 원인은 연결하지 않는다. 진단은 `diagnose`가 고른 안전한 값만 싣는다.
            raise PipelineFailure(
                stage, context.target, _folded_cause(exc), diagnose(exc, context.paths)
            ) from None
    return result


def _folded_cause(error: Exception) -> FailureCause:
    if isinstance(error, ValueError | TypeError | KeyError):
        return FailureCause.INVALID_ARTIFACT
    if isinstance(error, OSError):
        return FailureCause.IO_ERROR
    return FailureCause.ADAPTER_FAILED


def _execute_one(stage: str, context: ExecutionContext, adapters: Adapters) -> StageOutput:
    store = ArtifactStore(context.paths, context.target)
    result: StageOutput
    match stage:
        case "fetch":
            result = adapters.fetch(FetchInput(context.target), context)
        case "headermap":
            result = adapters.headermap(HeaderMapInput(sources=store.reporting_sources()), context)
        case "parse":
            targets = store.reporting_sources()
            mapped = store.load("headermap", HeaderMapOutput)
            result = adapters.parse(
                ParseInput(
                    sources=targets,
                    mappings=mapped.mappings,
                    unresolved=mapped.unresolved,
                    confirmations=store.repeat_confirmations(),
                    unresolved_mappings=mapped.unresolved_mappings,
                    merchants=store.merchant_reviews(),
                ),
                context,
            )
            result = ParseOutput.model_validate(result).model_copy(
                update={"excluded_sources": store.excluded_sources()},
            )
            source_targets = {(source.source_hash, source.organization) for source in targets}
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
            confirmations = restoration.confirm(parsed.records, store.confirmations())
            reviewed = restoration.resolve(parsed.records, store.restorations())
            restoration.require_agreement(reviewed, confirmations)
            records = restaurant_records(parsed.records, classified.decisions)
            included = {record.record_id for record in records}
            restorations = tuple(item for item in reviewed if item.record_id in included)
            # 조회를 먼저 끝낸다. 그 결과가 레코드마다 판정 키에 들어가므로
            # 조회가 달라진 레코드는 이전 판정을 재사용하지 않는다.
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
                        item for item in confirmations if item.record_id in included
                    ),
                    restorations=restorations,
                    previous=store.previous_geocodes(),
                    retry_failed=context.retry_failed,
                    address_prefixes=context.target.city.address_prefixes,
                    halls=context.target.city.halls,
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
                        target_sources=len(parsed.sources),
                        excluded_sources=parsed.excluded_sources,
                        repeated_expenses=parsed.repeated_expenses,
                        tally=submission.tally(
                            parsed.sources,
                            store.source_reviews(),
                            parsed.records,
                            classified.decisions,
                            geocoded.results,
                        ),
                        categories=category.published(store.category_cache(), geocoded.results),
                    ),
                    context,
                )
        case _:
            raise ValueError("unknown stage")
    store.save(stage, result, retry_failed=context.retry_failed)
    if isinstance(result, GeocodeOutput):
        # 판정을 저장한 뒤 확정 업소의 업종만 조회한다. 업종은 판정·판정 키를 바꾸지 않는다.
        with store.category_cache() as category_lookups:
            category_failed = category.resolve(
                category_lookups,
                result.results,
                context.category_sources,
                retry_failed=context.retry_failed,
            )
        if category_failed or any(item.reason == "lookup_error" for item in result.results):
            raise AdapterFailure(FailureCause.LOOKUP_FAILED)
    return result
