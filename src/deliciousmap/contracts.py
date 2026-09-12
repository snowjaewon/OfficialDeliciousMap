"""Versioned, validated public contracts. No external service implementation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from deliciousmap.registry import Target

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# 공백이 없는 한 낱말. 다른 값과 한 칸에 이어 적는 값(레코드 위치 등)에 쓴다.
Token = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^\S+$")]
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


class RecordOrigin(Contract):
    """레코드 하나가 나온 원본과 그 안의 행 위치."""

    source_hash: Sha256
    location: Token


class Record(Contract):
    record_id: Text
    spent_on: date
    organization: Text
    department: str
    merchant: Text
    purpose: str
    amount_krw: Decimal = Field(allow_inf_nan=False)
    source_hash: Sha256
    source_location: Token
    # 누적 재게시로 합친 레코드가 같은 지출을 함께 실은 다른 원본들([ADR-0003](
    # ../../docs/adr/0003-merge-repeated-reposts.md)). 합치지 않은 레코드는 비어 있다.
    repeats: tuple[RecordOrigin, ...] = ()

    @model_validator(mode="after")
    def distinct_origins(self) -> "Record":
        origins = {(self.source_hash, self.source_location)}
        origins |= {(item.source_hash, item.location) for item in self.repeats}
        if len(origins) != len(self.repeats) + 1:
            raise ValueError("a record cannot list the same origin twice")
        return self


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


# 원본의 실제 컨테이너. 게시판이 붙인 확장자가 아니라 매직 바이트로 판정한 값이다.
Container = Literal["ole2", "ooxml", "pdf", "spreadsheetml"]


class SourceRef(Contract):
    # 원본이 있는 곳. 상대 경로는 `--raw-root` 기준으로 읽는다. 현재 게시판 수집은 수집 PC의
    # 경로를 그대로 남기므로, 이 값은 산출물을 만든 PC 밖에서 그대로 쓸 수 없다.
    path: Path
    source_hash: Sha256
    organization: Text
    board: Text
    url: Text
    container: Container
    # 게시글이 밝힌 작성 부서. 원본에 부서 열이 없을 때 출처 메타데이터로 보완한다.
    # 게시판 구조에 기대지 않는 스크래퍼는 채우지 않으며, 그때 부서는 표의 열에서만 온다.
    department: Text | None = None
    # 게시판 목록이 밝힌 게시일과 제목. 지출 기간은 제목에만 있어 이번 제출의 대상 원본을
    # 고르는 일이 이 값을 쓴다. 목록 구조를 읽지 않는 스크래퍼는 채우지 않는다.
    posted: date | None = None
    title: Text | None = None


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


# 사람이 원본과 대조해 확인한 미해결 사유. 원본 자체의 결함만 담는다.
SourceFinding = Literal["merchant_blank", "total_mismatch"]


class SourceReview(Contract):
    """data/manual/<city>/sources.jsonl 한 줄. 미해결 원본을 전수로 대조하고 남긴 기록.

    값을 채워 통과시키는 칸은 두지 않는다. 원본에 없는 상호·금액을 적어 넣는 것은 폴백 정책이
    막으므로, 이 입력이 남기는 것은 무엇을 왜 남겼는지와 어디까지 보았는지다. 폴백 정책이
    요구하는 사람의 최종 대조는 `confirmed_by`가 가른다 — 비어 있으면 아직 코드 훑기뿐이다.
    기록한 원본이 나중에 통과하게 되면 `parse`가 낡은 기록으로 알린다.
    """

    schema_version: Literal[1] = 1
    city: Text
    # 원본이 속한 기관. `--org`로 한 기관만 돌릴 때 다른 기관의 기록을 보지 않으려고 둔다.
    organization: Text
    source_hash: Sha256
    finding: SourceFinding
    # 전수로 본 지출 후보 수와 사유가 걸린 행의 위치(`sheet1:R14`). 원본 값은 적지 않는다.
    candidates: int = Field(ge=0)
    rows: tuple[Text, ...] = Field(min_length=1)
    evidence: Excerpt
    # 원본과 전수로 대조한 사람. 코드 훑기만 끝났으면 비워 둔다.
    confirmed_by: str = ""


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
        require_single_answer(self.status, self.error, self.answer)
        return self


def require_single_answer(status: str, error: str | None, answer: object) -> None:
    require_error_code(status, error)
    if (status == "ok") != (answer is not None):
        raise ValueError("a successful reply requires exactly one answer")


ReplyError = Literal["unavailable", "invalid_response", "incomplete_response"]
# 헤더 매핑이 판정하는 열 역할. 사용자·직위·인원 같은 열은 역할을 주지 않는다.
ColumnRole = Literal[
    "spent_on", "merchant", "purpose", "department", "amount_krw", "month", "day", "time"
]


class MappedColumn(Contract):
    column: int = Field(ge=0)
    role: ColumnRole


class HeaderMapAnswer(Contract):
    """모델이 표 하나에 대해 돌려준 판정. 코드 검증을 통과해야 헤더 매핑이 된다."""

    layout: Literal["table", "key_value", "none"]
    header_rows: tuple[Annotated[int, Field(ge=1)], ...]
    data_start_row: int | None = Field(default=None, ge=1)
    columns: tuple[MappedColumn, ...]
    amount_unit: Literal["won", "thousand_won", "unknown"]
    year_hint: int | None = Field(default=None, ge=1, le=9999)


class CachedHeaderMap(Contract):
    """data/_shared/headermap.jsonl 항목의 값. 원본마다 다른 연도 근거는 싣지 않는다."""

    header_rows: tuple[Annotated[int, Field(ge=1)], ...] = Field(min_length=1)
    # 마지막 헤더 행에서 첫 지출 행까지의 거리.
    data_offset: int = Field(ge=1)
    columns: dict[ColumnRole, Annotated[int, Field(ge=0)]]
    amount_multiplier: Decimal = Field(gt=0, allow_inf_nan=False)
    model: Text
    prompt_version: Text


class RecordedAnswer(Contract):
    """data/<city>/headermap-answers-v1.jsonl 항목의 값. 원본·표 하나에 받은 모델 응답 하나.

    잘리거나 해석할 수 없던 응답도 과금된 시도이므로 사유와 함께 남긴다.
    """

    answer: HeaderMapAnswer | None = None
    error: Literal["invalid_response", "incomplete_response"] | None = None
    model: Text
    prompt_version: Text

    @model_validator(mode="after")
    def answer_or_error(self) -> "RecordedAnswer":
        if (self.answer is None) == (self.error is None):
            raise ValueError("a recorded reply is either an answer or an error")
        return self


class HeaderMapReply(Contract):
    status: Literal["ok", "error"]
    error: ReplyError | None = None
    answer: HeaderMapAnswer | None = None
    usage: Usage | None = None

    @model_validator(mode="after")
    def consistent_reply(self) -> "HeaderMapReply":
        require_single_answer(self.status, self.error, self.answer)
        return self


class Verdict(Contract):
    """상호 하나의 판정. 번호는 요청에 적은 순서이며 상호 표기와 함께 대조한다."""

    index: int = Field(ge=1)
    merchant: str
    status: ClassificationStatus
    # 판정의 짧은 근거(업종 등). 사람 검토용이다.
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] = ""


class ClassificationAnswer(Contract):
    verdicts: tuple[Verdict, ...]


class ClassificationReply(Contract):
    status: Literal["ok", "error"]
    error: ReplyError | None = None
    answer: ClassificationAnswer | None = None
    usage: Usage | None = None

    @model_validator(mode="after")
    def consistent_reply(self) -> "ClassificationReply":
        require_single_answer(self.status, self.error, self.answer)
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


class MissingOriginal(Contract):
    """게시판이 링크했지만 받지 못한 원본. 0건으로 숨기지 않기 위해 장부처럼 남긴다."""

    organization: Text
    board: Text
    # 근거가 되는 게시글 주소와 게시판이 밝힌 파일 이름.
    url: Text
    filename: Text
    # gone: 기관이 404로 답한다. empty: 200이지만 내용이 없다. 둘 다 받을 것이 없다.
    reason: Literal["gone", "empty"]
    # 어느 기간의 장부가 빈 것인지 알 수 있도록 출처와 같은 값을 남긴다.
    posted: date | None = None
    title: Text | None = None


class FetchOutput(Contract):
    sources: tuple[SourceRef, ...]
    # 받지 못한 원본. 성공한 수집에도 남을 수 있다.
    missing: tuple[MissingOriginal, ...] = ()
    empty_reason: Text | None = None


class HeaderMapInput(Contract):
    sources: tuple[SourceRef, ...]


# 원본을 끝내 읽지 못한 사유. 기관의 수집 보류와 달리 원본 해시별 파일 단위 미해결이다.
UnresolvedReason = Literal[
    "unsupported_format",
    "unreadable",
    "unsupported_layout",
    "no_table",
    "model_not_configured",
    "unavailable",
    "invalid_response",
    "incomplete_response",
    "oversized_request",
    "budget_exhausted",
    "unknown_prior_usage",
    "concurrent_execution",
    "validation_failed",
    "no_candidates",
]


class UnresolvedSource(Contract):
    source_hash: Sha256
    reason: UnresolvedReason
    # 어느 표의 어떤 검증이 실패했는지. 원본 내용은 적지 않는다.
    detail: str = ""


class HeaderMapOutput(Contract):
    mappings: tuple[HeaderMap, ...]
    unresolved: tuple[UnresolvedSource, ...] = ()


class ParseInput(Contract):
    sources: tuple[SourceRef, ...]
    mappings: tuple[HeaderMap, ...]
    unresolved: tuple[UnresolvedSource, ...] = ()


# 합계 대조 결과. 합계가 없거나 범위를 확정할 수 없으면 대조하지 않았다는 뜻이다.
TotalCheck = Literal["matched", "absent", "ambiguous"]


class SourceReport(Contract):
    """원본 하나의 추출 결과. 미해결 원본의 잘 읽힌 일부는 레코드로 확정하지 않는다."""

    source_hash: Sha256
    status: Literal["parsed", "unresolved"]
    reason: UnresolvedReason | None = None
    detail: str = ""
    # 원본에서 식별한 지출 후보 수. 모르면 None(알 수 없음)이며 0건 손실로 읽지 않는다.
    candidates: int | None = Field(default=None, ge=0)
    records: int = Field(default=0, ge=0)
    # 대상 기간 밖의 유효한 지출. 날짜 파싱 실패와 구별한다.
    out_of_range: int = Field(default=0, ge=0)
    # 다른 원본이 이미 공개한 지출이어서 합쳐 뺀 레코드 수. `records`는 합친 뒤의 수이며,
    # 둘을 더하면 이 원본이 실제로 실은 대상 기간 레코드 수다.
    repeated: int = Field(default=0, ge=0)
    # 빈 행·반복 헤더·합계처럼 지출 1건이 아니어서 분모에서 뺀 행의 위치와 종류(`sheet1:R7 total`).
    excluded: tuple[Text, ...] = ()
    # 원본에 실제로 있는 0원·음수처럼 재검증 리포트에서 사람이 볼 레코드의 위치와 사유.
    review: tuple[Text, ...] = ()
    total_check: TotalCheck | None = None

    @model_validator(mode="after")
    def consistent_report(self) -> "SourceReport":
        if (self.status == "unresolved") != (self.reason is not None):
            raise ValueError("only unresolved originals carry a reason")
        if self.status == "unresolved" and self.records:
            raise ValueError("unresolved originals cannot contribute records")
        return self


class ExcludedSources(Contract):
    """대상에서 빠진 원본의 사유별 수. 수집 장부는 줄지 않으며 이 수는 그 장부에서 센다.

    `undeclared_in_year`는 게시일이 대상 연도인데 제목이 기간을 밝히지 않아 빠진 수다.
    이 값이 0이 아니면 읽지 못한 표기 때문에 대상이 조용히 빠졌다는 뜻이다.
    """

    posted_out_of_range: int = Field(default=0, ge=0)
    declared_out_of_range: int = Field(default=0, ge=0)
    undeclared_in_year: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return self.posted_out_of_range + self.declared_out_of_range + self.undeclared_in_year


class RepeatedExpenses(Contract):
    """원본을 넘어 반복된 지출의 병합 결과. 합친 수와 가르지 못해 남긴 수를 함께 싣는다.

    기준은 [ADR-0003](../../docs/adr/0003-merge-repeated-reposts.md)이다. `unmerged_expenses`가
    0이 아니면 재게시인지 별개 지출인지 가를 근거가 없어 남긴 묶음이 그만큼 있다는 뜻이다.
    """

    # 합친 지출 묶음 수와 그때 뺀 레코드 수.
    merged_expenses: int = Field(default=0, ge=0)
    merged_records: int = Field(default=0, ge=0)
    # 가를 근거가 없어 남긴 묶음 수와 그 묶음들에 원본을 넘어 남은 레코드 수.
    unmerged_expenses: int = Field(default=0, ge=0)
    unmerged_records: int = Field(default=0, ge=0)


class ParseOutput(Contract):
    records: tuple[Record, ...]
    empty_reason: Text | None = None
    sources: tuple[SourceReport, ...] = ()
    # 대상 기간(`시작/끝`). 원본별 범위 밖 건수는 이 기간 밖의 유효한 지출이다.
    reporting_period: str = ""
    # 대상을 고르는 쪽(`ArtifactStore`)이 수집 장부에서 세어 채운다. 어댑터는 대상만 받으므로
    # 이 수를 알지 못한다.
    excluded_sources: ExcludedSources = ExcludedSources()
    # 누적 재게시로 합친 지출과 가를 근거가 없어 남긴 지출의 수.
    repeated_expenses: RepeatedExpenses = RepeatedExpenses()


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
    # 이번 제출이 읽은 원본 수와 뺀 원본의 사유별 수. 화면의 자료 범위가 둘을 같이 낸다.
    target_sources: int = Field(default=0, ge=0)
    excluded_sources: ExcludedSources = ExcludedSources()


class BuildOutput(Contract):
    files: tuple[Path, ...]
    record_count: int = Field(ge=0)
    marker_count: int = Field(ge=0)
