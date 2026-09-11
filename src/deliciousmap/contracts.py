"""Versioned, validated public contracts. No external service implementation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from deliciousmap.registry import Target

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ClassificationStatus = Literal["restaurant", "non_restaurant", "pending"]
Provider = Literal["local", "naver", "license"]
# 업소 판정의 결론. 확정된 두 사유 외에는 모두 미확정의 이유다.
GeocodeReason = Literal[
    "matched",
    "human_confirmed",
    "no_candidates",
    "missing_address",
    "unknown_branch",
    "conflicting_evidence",
    "ambiguous",
    "unconfirmed_name",
    "no_match",
    "missing_coordinates",
    "lookup_error",
    "insufficient_evidence",
]
CONFIRMED_REASONS = ("matched", "human_confirmed")
MapStatus = Literal["mapped", "geocode_failed", "non_restaurant", "pending"]
# 동일성 판단에 필요한 근거만 남기기 위한 상한. 원본 전체를 옮겨 적는 용도가 아니다.
Excerpt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


def require_error_code(status: str, error: str | None) -> None:
    """조회 실패는 언제나 안전한 사유 코드를 함께 남긴다."""
    if (status == "error") != (error is not None):
        raise ValueError("lookup errors require an explicit error code")


class Record(Contract):
    record_id: Text
    spent_on: date
    organization: Text
    department: str
    merchant: Text
    purpose: str
    amount_krw: Decimal = Field(allow_inf_nan=False)
    source_hash: Sha256
    source_location: Text


class CacheEntry(Contract):
    schema_version: Literal[1] = 1
    key: Text
    revision: int = Field(ge=1, strict=True)
    valid: bool
    evidence: Text
    value: dict[str, JsonValue]


class CacheRef(Contract):
    """Reference into data/_shared/headermap.jsonl; schema version 1."""

    schema_version: Literal[1] = 1
    key: Text
    revision: int = Field(ge=1)


class SourceRef(Contract):
    path: Path
    source_hash: Sha256
    organization: Text
    board: Text
    url: Text


class HeaderMap(Contract):
    source_hash: Sha256
    table: Text
    layout: Literal["table", "key_value", "none"]
    header_rows: tuple[Annotated[int, Field(ge=1)], ...]
    data_start_row: int = Field(ge=1)
    year_hint: int | None = Field(default=None, ge=1, le=9999)
    columns: dict[
        Literal[
            "spent_on", "merchant", "purpose", "department", "amount_krw", "month", "day", "time"
        ],
        Annotated[int, Field(ge=0)],
    ]
    amount_multiplier: Decimal = Field(gt=0, allow_inf_nan=False)
    cache: CacheRef | None = None

    @model_validator(mode="after")
    def header_cache_requires_headers(self) -> "HeaderMap":
        if not self.header_rows and self.cache is not None:
            raise ValueError("headerless mapping cannot use shared header cache")
        return self


class ManualCorrection(Contract):
    schema_version: Literal[1] = 1
    city: Text
    merchant: Text
    organization: str | None = None
    source_hash: Sha256 | None = None
    status: Literal["restaurant", "non_restaurant"]
    evidence: Text


class Classification(Contract):
    record_id: Text
    status: ClassificationStatus
    evidence: Text


class ReviewReference(Contract):
    """검토에 사용한 자료의 출처와 근거. 원본 전체 대신 판단에 필요한 부분만 남긴다."""

    kind: Literal["disclosure", "license", "place", "other"]
    source: Text
    detail: Excerpt


class RestorationScope(Contract):
    """확인 근거가 뒷받침하는 적용 범위. 선언한 항목이 모두 맞는 레코드에만 적용한다."""

    city: Text
    merchant: Text
    organization: str | None = None
    source_hash: Sha256 | None = None
    record_id: str | None = None


class NameRestoration(Contract):
    """data/manual/<city>/restore.jsonl 한 줄. 사람이 확정한 전체 상호."""

    schema_version: Literal[1] = 1
    scope: RestorationScope
    restored_merchant: Text
    evidence: Text
    references: tuple[ReviewReference, ...] = ()


class RestoredName(Contract):
    """레코드 하나에 적용한 복원 결과. 원본 표기는 그대로 보존한다."""

    record_id: Text
    merchant: Text
    restored_merchant: Text
    scope: RestorationScope
    evidence: Text
    references: tuple[ReviewReference, ...] = ()


class EvidenceScope(Contract):
    city: Text
    organization: Text
    record_id: Text
    source_hash: Sha256


class ScopedReview(Contract):
    """레코드 범위를 선언한 사람 검토 입력. 다른 레코드·원본·기관에는 적용하지 않는다."""

    scope: EvidenceScope


class ComparisonRequest(ScopedReview):
    """data/manual/<city>/compare.jsonl 한 줄. 담당자가 후보 비교를 지정한 미해결 건."""

    schema_version: Literal[1] = 1
    evidence: Text


class IdentityFacts(Contract):
    merchant: Text
    # None means unknown; an empty branch explicitly means an unbranched business.
    branch: str | None = None
    address: Text | None = None
    source: Text


class CandidateSource(Contract):
    provider: Provider
    source_id: Text
    reference: Text


class PlaceCandidate(Contract):
    source: CandidateSource
    merchant: Text
    branch: str | None = None
    address: Text | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)


class ProviderCandidates(Contract):
    """조회 한 번을 해석한 결과. 원본 응답·인증 정보는 남기지 않는다."""

    status: Literal["ok", "error"]
    error: Literal["unavailable", "invalid_response"] | None = None
    candidates: tuple[PlaceCandidate, ...] = ()

    @model_validator(mode="after")
    def consistent_result(self) -> "ProviderCandidates":
        require_error_code(self.status, self.error)
        if self.status == "error" and self.candidates:
            raise ValueError("failed lookups cannot supply candidates")
        return self


class ProviderQuery(Contract):
    """조회 하나의 요청 맥락·해석 버전·결과 상태. 후보 사실과 분리해 재사용과 추적에 쓴다."""

    provider: Literal["naver", "license"]
    request: Text
    interpretation: Text
    status: Literal["ok", "error"]
    error: Literal["unavailable", "invalid_response"] | None = None
    cache: CacheRef

    @model_validator(mode="after")
    def consistent_query(self) -> "ProviderQuery":
        require_error_code(self.status, self.error)
        return self


class CandidateLookup(Contract):
    scope: EvidenceScope
    status: Literal["ok", "error"]
    error: Literal["unavailable", "invalid_response", "not_supplied"] | None = None
    facts: tuple[IdentityFacts, ...] = ()
    candidates: tuple[PlaceCandidate, ...] = ()
    queries: tuple[ProviderQuery, ...] = ()

    @model_validator(mode="after")
    def consistent_lookup(self) -> "CandidateLookup":
        require_error_code(self.status, self.error)
        if self.status != "error" and any(item.status == "error" for item in self.queries):
            raise ValueError("failed provider lookups cannot be reported as a successful lookup")
        return self


class CandidateFile(Contract):
    schema_version: Literal[1] = 1
    lookups: tuple[CandidateLookup, ...]


class IdentityConfirmation(ScopedReview):
    candidate_source: CandidateSource
    merchant: Text
    branch: str
    address: Text
    evidence: Text


class GeocodeResult(Contract):
    record_id: Text
    merchant: Text
    status: Literal["success", "failed"]
    reason: GeocodeReason
    business_id: Sha256 | None = None
    confirmed_merchant: Text | None = None
    lookup_key: Sha256
    dependency_key: Sha256
    lookup: CandidateLookup
    confirmation: IdentityConfirmation | None = None
    restoration: RestoredName | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    evidence: Text

    @model_validator(mode="after")
    def consistent_coordinates(self) -> "GeocodeResult":
        if self.status == "success" and (self.latitude is None or self.longitude is None):
            raise ValueError("successful geocoding requires both coordinates")
        if self.status == "failed" and (self.latitude is not None or self.longitude is not None):
            raise ValueError("failed geocoding cannot carry coordinates")
        if self.status == "success" and (
            self.business_id is None
            or self.confirmed_merchant is None
            or self.reason not in CONFIRMED_REASONS
        ):
            raise ValueError("success requires a confirmed business")
        if self.status == "failed" and (
            self.business_id is not None
            or self.confirmed_merchant is not None
            or self.reason in CONFIRMED_REASONS
        ):
            raise ValueError("unresolved records cannot be assigned a business")
        if self.record_id != self.lookup.scope.record_id:
            raise ValueError("result scope mismatch")
        if self.restoration is not None and (
            self.restoration.record_id != self.record_id
            or self.restoration.merchant != self.merchant
        ):
            raise ValueError("restoration record or original name mismatch")
        return self


class MarkerCandidate(Contract):
    business_id: Sha256
    merchant: Text
    record_ids: tuple[str, ...]
    latitude: float
    longitude: float


class ClosureResult(Contract):
    business_id: Sha256
    status: Literal["open", "closed", "unknown"]
    evidence: Text


class PublishedMarker(Contract):
    """markers.json에 공개하는 식당 단위 축약 레코드."""

    business_id: Sha256
    merchant: Text
    visit_count: int = Field(ge=1)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    closed: bool
    # 좌표를 준 제공자. 인허가 좌표도 지도에서 구별하지 않고 상세에서만 밝힌다.
    coordinate_source: Provider


class PublishedRecord(Contract):
    """records.json에 공개하는 장부 레코드와 지도 반영 상태. 원본 추적 값은 남기지 않는다."""

    record_id: Text
    spent_on: date
    organization: Text
    department: str
    merchant: Text
    purpose: str
    amount_krw: Decimal = Field(allow_inf_nan=False)
    classification: ClassificationStatus
    map_status: MapStatus
    # 지오코딩을 수행한 레코드만 사유를 가진다. 비식당·판단 보류는 판정 대상이 아니다.
    geocode_reason: GeocodeReason | None = None
    # 마커로 묶인 레코드만 업소 식별자를 가진다.
    business_id: Sha256 | None = None

    @model_validator(mode="after")
    def consistent_map_status(self) -> "PublishedRecord":
        mapped = self.map_status == "mapped"
        if mapped != (self.business_id is not None):
            raise ValueError("only mapped records belong to a business")
        if mapped != (self.geocode_reason in CONFIRMED_REASONS):
            raise ValueError("map status and geocoding reason disagree")
        if (self.map_status in {"mapped", "geocode_failed"}) != (self.geocode_reason is not None):
            raise ValueError("only adjudicated records carry a geocoding reason")
        return self


class MarkerFile(Contract):
    schema_version: Literal[6] = 6
    city: Text
    org: str | None = None
    markers: tuple[PublishedMarker, ...]


class RecordFile(Contract):
    schema_version: Literal[6] = 6
    city: Text
    org: str | None = None
    records: tuple[PublishedRecord, ...]


# LLM 용도의 단일 출처. 새 용도가 생기면 여기에만 더한다.
LlmPurpose = Literal[
    "header_mapping", "classification", "extraction_fallback", "restoration_comparison"
]


class LedgerEntry(Contract):
    """data/_shared/llm-budget.jsonl 한 줄. 공통 LLM 예산의 추가형 이력이며 지우지 않는다."""

    schema_version: Literal[1] = 1
    # 예약과 정산을 잇는 키. 같은 요청의 두 줄은 같은 값을 쓴다.
    entry_id: Text
    kind: Literal["prior_usage", "reservation", "settlement"]
    purpose: Literal["prior_usage"] | LlmPurpose
    # 기존 사용액은 특정 모델의 것이 아니므로 비워 둔다.
    model: str | None = None
    amount_usd: Decimal = Field(ge=0, allow_inf_nan=False)
    evidence: Text


class Usage(Contract):
    """제공자가 알린 과금 항목. 합계 필드를 다시 더하지 않는다."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ComparisonAnswer(Contract):
    """모델이 구조화 출력으로 돌려준 답변. 이 자체는 제안도 확정도 아니다."""

    supported: bool
    candidate_source_id: str
    restored_merchant: str
    rationale: str


class ModelReply(Contract):
    """모델 호출 한 번의 결과. 응답 원문·비밀값은 남기지 않는다."""

    status: Literal["ok", "error"]
    error: Literal["unavailable", "invalid_response", "incomplete_response"] | None = None
    answer: ComparisonAnswer | None = None
    # 과금된 실패도 사용량을 알 수 있으면 남긴다.
    usage: Usage | None = None

    @model_validator(mode="after")
    def consistent_reply(self) -> "ModelReply":
        require_error_code(self.status, self.error)
        if (self.status == "ok") != (self.answer is not None):
            raise ValueError("a successful reply requires exactly one answer")
        return self


class RestorationProposal(Contract):
    """모델 비교의 결과. 사람 검토용 제안이며 복원명·좌표를 확정하지 않는다."""

    schema_version: Literal[1] = 1
    scope: EvidenceScope
    merchant: Text
    status: Literal["proposed", "withheld"]
    reason: Literal[
        "candidate_supported",
        "not_unresolved",
        "no_candidates",
        "no_supported_candidate",
        "ungrounded_response",
        "incomplete_response",
        "invalid_response",
        "unavailable",
        "oversized_request",
        "budget_exhausted",
        "unknown_prior_usage",
        "concurrent_execution",
    ]
    proposed_merchant: Text | None = None
    candidate_source: CandidateSource | None = None
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    model: Text
    prompt_version: Text
    request_key: Sha256
    # 사람 확인 경로를 거치기 전에는 언제나 미확정이다.
    confirmed: Literal[False] = False

    @model_validator(mode="after")
    def consistent_proposal(self) -> "RestorationProposal":
        proposed = (self.proposed_merchant, self.candidate_source, bool(self.rationale))
        if self.status == "proposed":
            if not all(proposed) or self.reason != "candidate_supported":
                raise ValueError("a proposal requires a grounded candidate and its rationale")
        elif any(proposed) or self.reason == "candidate_supported":
            raise ValueError("a withheld comparison cannot carry a proposed name")
        return self


@dataclass(frozen=True)
class FetchInput:
    target: Target


class FetchOutput(Contract):
    sources: tuple[SourceRef, ...]
    empty_reason: Text | None = None


class HeaderMapInput(Contract):
    sources: tuple[SourceRef, ...]


class HeaderMapOutput(Contract):
    mappings: tuple[HeaderMap, ...]


class ParseInput(Contract):
    sources: tuple[SourceRef, ...]
    mappings: tuple[HeaderMap, ...]


class ParseOutput(Contract):
    records: tuple[Record, ...]
    empty_reason: Text | None = None


class ClassifyInput(Contract):
    records: tuple[Record, ...]
    manual: tuple[ManualCorrection, ...] = ()
    restorations: tuple[RestoredName, ...] = ()

    @property
    def merchants(self) -> tuple[str, ...]:
        """확정 복원명이 있으면 그 이름을 판별한다. 원본 표기는 레코드에 그대로 남는다."""
        restored = {item.record_id: item.restored_merchant for item in self.restorations}
        return tuple(
            dict.fromkeys(
                restored.get(record.record_id, record.merchant) for record in self.records
            )
        )


class ClassifyOutput(Contract):
    decisions: tuple[Classification, ...]


class GeocodeInput(Contract):
    dependency_key: Sha256
    records: tuple[Record, ...]
    lookups: tuple[CandidateLookup, ...] = ()
    confirmations: tuple[IdentityConfirmation, ...] = ()
    restorations: tuple[RestoredName, ...] = ()
    previous: tuple[GeocodeResult, ...] = ()
    retry_failed: bool = False


class GeocodeOutput(Contract):
    results: tuple[GeocodeResult, ...]


class ClosureInput(Contract):
    candidates: tuple[MarkerCandidate, ...]
    license_root: Path


class ClosureOutput(Contract):
    results: tuple[ClosureResult, ...]


class BuildInput(Contract):
    records: tuple[Record, ...]
    decisions: tuple[Classification, ...]
    geocodes: tuple[GeocodeResult, ...]
    closures: tuple[ClosureResult, ...]
    candidates: tuple[MarkerCandidate, ...]


class BuildOutput(Contract):
    files: tuple[Path, ...]
    record_count: int = Field(ge=0)
    marker_count: int = Field(ge=0)
