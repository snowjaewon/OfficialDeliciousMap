"""Versioned, validated public contracts. No external service implementation."""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import total_ordering
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from deliciousmap import merchants
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
    "merged_merchant",
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


# 일까지 적은 집행일의 표기. 장부 CSV와 공개 파일이 쓰는 한 가지 모양이다.
DATED = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# 일을 적지 않은 집행일의 표기. 마침표는 2026-09-13 동구 실측의 `2026.03.`이고, 붙임표는
# 원본 표기가 없을 때 이 값이 스스로 쓰는 `2026-03`이다. 실측하지 않은 구분자는 받지 않는다 —
# 읽지 못한 원본은 사유를 달고 미해결로 남지, 짐작한 표기로 통과하지 않는다.
MONTH_ONLY = re.compile(r"(\d{4})\s*[-.]\s*(1[0-2]|0?[1-9])\s*[-.]?\s*")


@total_ordering
@dataclass(frozen=True)
class SpentOn:
    """집행일 하나. 원본이 일을 적지 않았으면 `day`가 빈 값이다.

    없는 일자를 그 달 1일·말일로 채우지 않는다 — 비어 있다는 사실이 값으로 남는다. 사람이 보는
    자리에는 원본이 적은 표기(`notation`)를 그대로 쓰고, 일이 있는 집행일은 `YYYY-MM-DD`로 보인다.
    순서는 일을 0으로 본 순서라 일이 빈 집행일이 같은 달의 어떤 집행일보다 앞에 온다.

    표기는 사람이 읽는 값이지 지출을 가르는 값이 아니므로 동일성과 순서에서 뺀다([ADR-0005](
    ../../docs/adr/0005-key-only-what-the-decision-reads.md)). 같은 달을 달리 적은 두 원본의
    지출은 같은 집행일이다.
    """

    year: int
    month: int
    day: int | None = None
    notation: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        # 달력에 없는 날은 집행일이 아니다. 일이 빈 집행일은 달까지만 달력에 물어본다.
        date(self.year, self.month, 1 if self.day is None else self.day)

    def __str__(self) -> str:
        if self.day is None:
            return self.notation or f"{self.year:04d}-{self.month:02d}"
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    def __lt__(self, other: "SpentOn") -> bool:
        return self._order < other._order

    @property
    def _order(self) -> tuple[int, int, int]:
        return (self.year, self.month, self.day or 0)

    @classmethod
    def of(cls, value: date) -> "SpentOn":
        return cls(value.year, value.month, value.day)

    @classmethod
    def month_only(cls, raw: str) -> "SpentOn | None":
        """일을 적지 않은 달 단위 표기. 실측한 모양이 아니면 읽지 않는다."""
        found = MONTH_ONLY.fullmatch(raw)
        return None if found is None else cls(int(found[1]), int(found[2]), notation=raw)

    @classmethod
    def parse(cls, raw: str) -> "SpentOn":
        dated = DATED.fullmatch(raw)
        if dated:
            return cls(int(dated[1]), int(dated[2]), int(dated[3]))
        undated = cls.month_only(raw)
        if undated is None:
            raise ValueError("a spending day is YYYY-MM-DD or the month as the original wrote it")
        return undated


def _as_spent_on(value: object) -> object:
    """장부·공개 파일의 글자와 달력 날짜를 집행일 값으로 옮긴다."""
    if isinstance(value, str):
        return SpentOn.parse(value)
    if isinstance(value, date):
        return SpentOn.of(value)
    return value


# 레코드·재게시 범위·공개 레코드·마커가 함께 쓰는 집행일 칸. 글자 하나로 오가므로 장부 CSV의
# 한 칸과 공개 JSON의 한 값이 그대로 원본 표기를 싣는다.
SpendingDay = Annotated[
    SpentOn, BeforeValidator(_as_spent_on), PlainSerializer(str, return_type=str)
]


class RecordOrigin(Contract):
    """레코드 하나가 나온 원본과 그 안의 행 위치."""

    source_hash: Sha256
    location: Token


class Expense(Contract):
    """레코드가 나온 지출 하나와 그 지출이 밝힌 금액.

    사람이 합쳐 적은 상호를 업소별로 확인한 지출에만 붙는다. 확인이 업소 둘 이상을 선언하면
    레코드도 그만큼 나뉘고 나뉜 레코드의 금액은 빈 값이며, 금액은 여기 그대로 남는다([ADR-0007](
    ../../docs/adr/0007-do-not-split-unallocated-amounts.md)). 업소 하나라는 확인도 판정이므로
    가르지 않은 레코드에도 붙는다 — 붙어 있다는 것이 사람이 이미 본 지출이라는 뜻이다.
    """

    expense_id: Text
    amount_krw: Decimal = Field(allow_inf_nan=False)


class Record(Contract):
    record_id: Text
    spent_on: SpendingDay
    organization: Text
    department: str
    merchant: Text
    purpose: str
    # 한 지출이 업소 둘 이상에 걸쳐 나뉜 레코드는 금액이 빈 값이다. 반씩 나누거나 한쪽에
    # 몰지 않으며, 비어 있다는 사실이 값으로 남는다(ADR-0007).
    amount_krw: Decimal | None = Field(allow_inf_nan=False)
    source_hash: Sha256
    source_location: Token
    # 이 지출을 함께 실은 다른 원본들. 누적 재게시로 합친 레코드만 가지며([ADR-0004](
    # ../../docs/adr/0004-merge-repeated-reposts.md)) 행 하나가 아니라 지출 하나의 출처다.
    repeats: tuple[RecordOrigin, ...] = ()
    # 사람이 업소별로 확인한 지출. 확인이 없는 레코드는 지출과 1:1이라 이 값을 갖지 않는다.
    expense: Expense | None = None

    @model_validator(mode="after")
    def distinct_origins(self) -> "Record":
        origins = {(self.source_hash, self.source_location)}
        origins |= {(item.source_hash, item.location) for item in self.repeats}
        if len(origins) != len(self.repeats) + 1:
            raise ValueError("a record cannot list the same origin twice")
        return self

    @model_validator(mode="after")
    def unallocated_amount_stays_with_the_expense(self) -> "Record":
        if self.amount_krw is None and self.expense is None:
            raise ValueError("a record without an amount must name the expense that holds it")
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
# `html`만 예외로 매직 바이트가 없다. 첨부를 내려받지 않고 화면 자체가 집행 표인 게시판
# (서울시청·은평·관악·서대문 실측, 울산 시청·중구·동구의 HTML 표 — ADR-0008)의 원본이며,
# 그 게시판에서만 이 값이 나온다.
# `jpeg`·`png`는 집행내역을 스캔본으로 공개한 게시판의 원본이다(용산 실측).
# `hwpml`·`hwpx`는 한글 문서다. 둘 다 `.hwp`·`.hwpx` 이름으로 오지만 하나는 XML이고
# 하나는 묶음이라 안을 여는 방법이 다르다(부산 동구·북구 실측).
Container = Literal[
    "html",
    "hwpml",
    "hwpx",
    "jpeg",
    "ole2",
    "ooxml",
    "pdf",
    "png",
    "spreadsheetml",
    "zip",
]


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
    # 하루치 집행내역을 날짜로 여는 게시판이 상세 키로 밝힌 집행일. 이 원본의 표는 집행일 열이
    # 없어 레코드의 집행일이 되고, 대상 기간도 제목 대신 이 날로 가른다([ADR-0008](
    # ../../docs/adr/0008-declare-html-table-mappings.md)). 그런 게시판이 아니면 비어 있다.
    spent_on: date | None = None


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
    # 레지스트리가 게시판에 선언한 매핑인지(ADR-0008). 모델에 묻거나 캐시에서 꺼낸 것이 아니다.
    declared: bool = False

    @model_validator(mode="after")
    def header_cache_requires_headers(self) -> "HeaderMap":
        if not self.header_rows and self.cache is not None:
            raise ValueError("headerless mapping cannot use shared header cache")
        return self


# 사람 검토 입력(`data/manual/<city>/` 네 파일)에서 판정이 읽지 않는 근거 필드. 산출물 의존성
# 키는 이 필드를 뺀 나머지를 담으므로(#190) 근거 문구·참조만 고친 편집은 산출물을 낡게 하지
# 않는다. 검토 모델에 근거 필드가 늘면 여기에 더한다 — 빠뜨리면 근거 편집에도 산출물이 낡는다.
REVIEW_EVIDENCE_FIELDS: frozenset[str] = frozenset({"evidence", "references"})


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


class ReviewScope(Contract):
    """확인 근거가 뒷받침하는 적용 범위. 선언한 항목이 모두 맞는 레코드에만 적용한다.

    상호 복원과 업소 확인이 같은 범위 규칙을 쓴다. 많이 선언한 줄이 더 좁은 범위다.
    """

    city: Text
    merchant: Text
    organization: str | None = None
    source_hash: Sha256 | None = None
    record_id: str | None = None


class NameRestoration(Contract):
    """data/manual/<city>/restore.jsonl 한 줄. 사람이 확정한 전체 상호."""

    schema_version: Literal[1] = 1
    scope: ReviewScope
    restored_merchant: Text
    evidence: Text
    references: tuple[ReviewReference, ...] = ()


class MerchantReview(Contract):
    """data/manual/<city>/merchants.jsonl 한 줄. 상호 표기 하나가 업소 몇 곳인지의 확인.

    합쳐 적은 상호는 사람이 확인해야 업소마다 나뉜다. 업소 둘 이상을 선언하면 그 지출이 레코드
    그만큼으로 갈리고, 하나만 선언하면 나누지 않는다 — 나누지 않는다는 것도 판정이다.
    범위는 상호 표기 단위이므로 같은 표기의 레코드 여럿이 한 줄로 처리된다.

    이름을 바꾸는 것은 상호 복원(`restore.jsonl`)의 일이다. 업소 하나를 선언한 줄이 범위가
    가리키는 표기와 다른 이름을 적으면 적용하는 쪽이 거부한다.
    """

    schema_version: Literal[1] = 1
    scope: ReviewScope
    merchants: tuple[Text, ...] = Field(min_length=1)
    evidence: Text
    references: tuple[ReviewReference, ...] = ()

    @model_validator(mode="after")
    def distinct_merchants(self) -> "MerchantReview":
        if len(set(self.merchants)) != len(self.merchants):
            raise ValueError("a merchant review cannot declare the same place twice")
        return self


class RestoredName(Contract):
    """레코드 하나에 적용한 복원 결과. 원본 표기는 그대로 보존한다."""

    record_id: Text
    merchant: Text
    restored_merchant: Text
    scope: ReviewScope
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
    기록한 원본이 나중에 통과하게 되면 `parse`가 낡은 기록으로 알린다. 코드도 후보를 센 원본이면
    `candidates`가 그 수와 같아야 한다 — 두 수가 다르면 화면이 어느 쪽을 분모로 냈는지 알 수 없다.
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


# 사람이 지출 묶음을 읽고 내리는 결론. 이 둘뿐이며 나머지 상태는 확정이 아니다.
RepeatDecision = Literal["same_expense", "separate_expenses"]


class ExpenseScope(Contract):
    """확인 근거가 뒷받침하는 지출 하나와 그 지출을 실은 원본들.

    지출의 동일성은 `기관·부서·집행일·상호·금액`이다([ADR-0004](
    ../../docs/adr/0004-merge-repeated-reposts.md)). 범위는 레코드 하나가 아니라 지출 하나이므로
    한 원본이 같은 지출을 두 번 적었어도 그 원본은 한 번만 적는다.
    """

    city: Text
    organization: Text
    department: str
    spent_on: SpendingDay
    merchant: Text
    amount_krw: Decimal = Field(allow_inf_nan=False)
    # 이 지출을 실은 원본들. 재게시 관계는 원본 쌍의 관계이므로 둘 이상을 적는다.
    sources: tuple[Sha256, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def distinct_sources(self) -> "ExpenseScope":
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("an expense scope cannot list the same original twice")
        return self


class RepeatConfirmation(Contract):
    """data/manual/<city>/repeats.jsonl 한 줄. 사람이 원본을 대조해 확정한 재게시 여부.

    코드는 두 원본이 같은 지출을 2건 이상 함께 실을 때만 재게시로 본다(ADR-0004). 근거가 그에
    못 미쳐 남은 묶음을 사람이 원본으로 읽고 확정하는 자리가 여기다. 확정은 자동 판정보다 먼저
    적용하며, 합치더라도 겹친 원본은 레코드의 `repeats`에 모두 남는다. `separate_expenses`도
    확인했다는 사실이 근거이므로 장부에 남기고 집계에서 감추지 않는다([ADR-0006](
    ../../docs/adr/0006-human-confirmed-reposts.md)).

    사람이 직접 쓰거나 에이전트가 써서 사람이 PR로 승인한다(`IdentityConfirmation`과 같다).
    `evidence`에는 판단을 글로 옮기지 않고 대조한 원본의 파일명을 적는다
    (`10887-1.xlsx, 11009-1.xlsx`). 승인하는 사람은 그 파일을 직접 연다.
    """

    schema_version: Literal[2] = 2
    scope: ExpenseScope
    decision: RepeatDecision
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


class SourceCategory(Contract):
    """제공자가 후보 하나에 붙인 업종 원문. 업소 확인의 근거가 아니라 표시용이다."""

    source_id: Text
    category: Text


class ProviderCategories(Contract):
    """업종 조회 한 번을 해석한 결과. 원본 응답·인증 정보는 남기지 않는다."""

    status: Literal["ok", "error"]
    error: Literal["unavailable", "invalid_response"] | None = None
    categories: tuple[SourceCategory, ...] = ()

    @model_validator(mode="after")
    def consistent_result(self) -> "ProviderCategories":
        require_error_code(self.status, self.error)
        if self.status == "error" and self.categories:
            raise ValueError("failed lookups cannot supply categories")
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


class IdentityConfirmation(Contract):
    """data/manual/<city>/geocode.jsonl 한 줄. 후보 하나를 동일 업소로 확정한다.

    사람이 직접 쓰거나 에이전트가 써서 사람이 PR로 승인한다. 어느 쪽이든 `evidence`에
    무엇을 대조했는지와 검토 주체를 적는다. 모델이 낸 제안은 이 파일에 넣지 않는다.
    """

    schema_version: Literal[1] = 1
    scope: ReviewScope
    candidate_source: CandidateSource
    merchant: Text
    branch: str
    address: Text
    evidence: Text
    references: tuple[ReviewReference, ...] = ()


class ConfirmedPlace(Contract):
    """레코드 하나에 적용한 업소 확인. 원본 표기는 레코드에 그대로 남는다."""

    record_id: Text
    candidate_source: CandidateSource
    merchant: Text
    branch: str
    address: Text
    scope: ReviewScope
    evidence: Text
    references: tuple[ReviewReference, ...] = ()


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
    confirmation: ConfirmedPlace | None = None
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
    # 좌표를 준 근거의 주소. 업소 확인은 주소가 일치한 후보만 채택하므로 확정 마커에는 언제나 있다.
    address: Text
    # 업소를 확정한 후보에 그 제공자가 붙인 업종 원문. 모르면 `미상`이다(#96).
    category: Text
    # 화면 필터가 쓰는 갈래. 규칙은 `category.group`이 정한다.
    category_group: Text
    # 아래 셋은 이 식당으로 묶인 레코드의 요약이다. 목록·상세가 장부를 받지 않고도 보여 준다.
    last_visited_on: SpendingDay
    # 금액이 있는 방문만 더한 합계와, 금액을 알 수 없는 방문 수. 합쳐 적은 상호를 업소별로
    # 가른 레코드는 금액이 빈 값이므로(ADR-0007) 합계에 들어가지 않는다. 그 수를 밝히지
    # 않으면 합계가 방문 전부를 더한 값으로 읽힌다.
    total_amount_krw: Decimal = Field(allow_inf_nan=False)
    unpriced_visit_count: int = Field(default=0, ge=0)
    organizations: tuple[Text, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unpriced_visits_are_counted_visits(self) -> "PublishedMarker":
        if self.unpriced_visit_count > self.visit_count:
            raise ValueError("unpriced visits cannot outnumber the visits themselves")
        return self


class PublishedRecord(Contract):
    """records.json에 공개하는 장부 레코드와 지도 반영 상태. 원본 추적 값은 남기지 않는다."""

    record_id: Text
    spent_on: SpendingDay
    organization: Text
    department: str
    merchant: Text
    purpose: str
    # 업소별로 가른 레코드는 금액이 빈 값이다. 지출에 남은 금액을 나누어 적지 않는다(ADR-0007).
    amount_krw: Decimal | None = Field(allow_inf_nan=False)
    classification: ClassificationStatus
    map_status: MapStatus
    # 지오코딩을 수행한 레코드만 사유를 가진다. 비식당·판단 보류는 판정 대상이 아니다.
    geocode_reason: GeocodeReason | None = None
    # 마커로 묶인 레코드만 업소 식별자를 가진다.
    business_id: Sha256 | None = None
    # 상호 끝이 이름 없이 수만 밝힌 업소의 수(#127). 꼬리말이 없으면 0,
    # 원본이 수를 적지 않았으면 알 수 없어 `null`이다.
    unnamed_companions: int | None = Field(default=0, ge=0)

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
    # v11: 마커가 업종을 싣는다(#96).
    schema_version: Literal[11] = 11
    city: Text
    org: str | None = None
    markers: tuple[PublishedMarker, ...]


class RecordFile(Contract):
    schema_version: Literal[10] = 10
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
    # 예약과 정산·해제를 잇는 키. 같은 요청의 줄은 같은 값을 쓴다.
    entry_id: Text
    kind: Literal["prior_usage", "reservation", "settlement", "release"]
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
    # gone: 기관이 404로 답한다. empty: 200이지만 내용이 없다. drm: 200이지만 기관이
    # 잠가 두었다. not_an_original: 표 대신 편집 도구의 부속 파일이 올라와 있다.
    # 모두 받을 것이 없고, drm과 not_an_original은 기관이 고치면 달라진다.
    reason: Literal["gone", "empty", "drm", "not_an_original"]
    # 어느 기간의 장부가 빈 것인지 알 수 있도록 출처와 같은 값을 남긴다.
    posted: date | None = None
    title: Text | None = None


class FetchOutput(Contract):
    sources: tuple[SourceRef, ...]
    # 받지 못한 원본. 성공한 수집에도 남을 수 있다.
    missing: tuple[MissingOriginal, ...] = ()
    empty_reason: Text | None = None
    # 게시일이 이번 수집의 대상 연도 밖이라 받지 않은 게시글 수(`period.collects`). 게시판에
    # 남아 있다는 사실을 0건으로 숨기지 않으려고 싣는다. 이미 받아 둔 원본은 여기에 세지 않는다.
    uncollected_postings: int = Field(default=0, ge=0)
    # 업무추진비 집행기관이 아닌 줄이 섞인 게시판에서 걸러 낸 게시글 수. 섞인 게시판
    # (서울 시청·중구·강남 실측)이 무엇을 뺐는지 0건으로 숨기지 않으려고 싣는다.
    filtered_postings: int = Field(default=0, ge=0)


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
    # 미해결 원본의 표마다 얻은 헤더 매핑. 검증에 실패한 것도, 그 원본의 다른 표가 통과시킨 것도
    # 함께 싣는다. 레코드로 쓰지 않으며 `parse`가 분모를 세는 데만 쓴다(폴백 정책의 후보 수).
    unresolved_mappings: tuple[HeaderMap, ...] = ()

    @model_validator(mode="after")
    def mappings_belong_to_their_original(self) -> "HeaderMapOutput":
        unresolved = {item.source_hash for item in self.unresolved}
        if any(item.source_hash not in unresolved for item in self.unresolved_mappings):
            raise ValueError("an unresolved mapping must belong to an unresolved original")
        identities = [(item.source_hash, item.table) for item in self.unresolved_mappings]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate mapping for a table of an unresolved original")
        return self


class ParseInput(Contract):
    sources: tuple[SourceRef, ...]
    mappings: tuple[HeaderMap, ...]
    unresolved: tuple[UnresolvedSource, ...] = ()
    # 미해결 원본의 헤더 매핑. 분모를 세는 데만 쓰고 레코드는 내지 않는다.
    unresolved_mappings: tuple[HeaderMap, ...] = ()
    # 사람이 확정한 재게시 여부. 누적 재게시 병합이 자동 판정보다 먼저 적용한다.
    confirmations: tuple[RepeatConfirmation, ...] = ()
    # 사람이 확인한 상호 표기별 업소. 확인이 있는 지출만 업소마다 레코드로 갈린다.
    merchants: tuple[MerchantReview, ...] = ()


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
    # 첨부 묶음에서 읽지 못한 항목과 사유(`file3 별지.pdf: unreadable`). 이 항목의 지출은
    # `candidates`에 들지 않는다. 묶음이 아닌 원본은 비어 있고, 비어 있으면 장부에 쓰지 않는다.
    unread: tuple[Text, ...] = Field(default=(), exclude_if=lambda value: not value)

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

    기준은 [ADR-0004](../../docs/adr/0004-merge-repeated-reposts.md)이다. `unmerged_expenses`가
    0이 아니면 재게시인지 별개 지출인지 가를 근거가 없어 남긴 묶음이 그만큼 있다는 뜻이다.
    사람이 원본을 대조해 확정한 묶음은 자동 판정과 섞지 않고 `confirmed_*`·`separate_*`에
    따로 싣는다([ADR-0006](../../docs/adr/0006-human-confirmed-reposts.md)).
    """

    # 합친 지출 묶음 수와 그때 뺀 레코드 수.
    merged_expenses: int = Field(default=0, ge=0)
    merged_records: int = Field(default=0, ge=0)
    # 가를 근거가 없어 남긴 묶음 수와 그 묶음들에 원본을 넘어 남은 레코드 수.
    unmerged_expenses: int = Field(default=0, ge=0)
    unmerged_records: int = Field(default=0, ge=0)
    # 사람이 같은 지출로 확정해 합친 묶음 수와 그때 뺀 레코드 수(ADR-0006).
    confirmed_expenses: int = Field(default=0, ge=0)
    confirmed_records: int = Field(default=0, ge=0)
    # 사람이 별개 지출로 확정해 남긴 묶음 수와 그 묶음들에 원본을 넘어 남은 레코드 수.
    separate_expenses: int = Field(default=0, ge=0)
    separate_records: int = Field(default=0, ge=0)


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


class ConfirmedDefect(Contract):
    """원본 결함 확정 한 사유의 수. 사람이 원본과 대조해 원본 자체의 결함으로 확정한 원본이다.

    후보 수는 사람이 전수로 센 `SourceReview.candidates`다. 코드가 센 수가 아니라 대조한 사람이
    본 수를 내야 무엇을 확인하고 남겼는지가 드러난다.
    """

    finding: SourceFinding
    sources: int = Field(ge=1)
    candidates: int = Field(ge=0)


class UnresolvedCount(Contract):
    """아직 확정에 이르지 못한 미해결 원본 한 사유의 수.

    후보 수를 모르는 원본이 하나라도 섞이면 `candidates`는 None이다. 나머지만 더한 수를 전체인
    것처럼 내면 폴백 정책이 막은 `알 수 없음`을 0건 손실로 보고하는 것이 된다.
    """

    reason: UnresolvedReason
    sources: int = Field(ge=1)
    candidates: int | None = Field(default=None, ge=0)


class UnconfirmedPlace(Contract):
    """좌표를 확정하지 못한 식당 레코드 한 사유의 수. 마커가 되지 못하고 장부에만 남는다."""

    reason: GeocodeReason
    records: int = Field(ge=1)


class UnnamedCompanions(Contract):
    """원본이 상호 끝에 이름 없이 수만 밝힌 업소([#127](
    https://github.com/snowjaewon/OfficialDeliciousMap/issues/127)).

    이름이 없어 조회할 수도 확정할 수도 없으므로 영영 마커가 되지 못한다. 원본이 수도 적지
    않은 표기는 몇 곳인지 알 수 없으므로 `places`에 더하지 않고 따로 센다 — 0곳으로도 1곳으로도
    적지 않는다. 이름이 적힌 첫 업소는 여기 담기지 않으며 다른 레코드와 같게 조회·판정된다.
    """

    # 꼬리말이 붙은 레코드 수. 레코드의 원본 표기는 바뀌지 않는다.
    records: int = Field(default=0, ge=0)
    # 원본이 수를 밝힌 이름 없는 업소의 합.
    places: int = Field(default=0, ge=0)
    # 원본이 수를 적지 않아 몇 곳인지 알 수 없는 레코드 수.
    uncounted_records: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def counted_within_the_records(self) -> "UnnamedCompanions":
        if self.uncounted_records > self.records:
            raise ValueError("more tails without a count than records that carry one")
        if not self.records and (self.places or self.uncounted_records):
            raise ValueError("places cannot be reported without a record that names them")
        return self


class SubmissionTally(Contract):
    """제출 시점 기준이 공개하는 남은 미해결의 수([#106](
    https://github.com/snowjaewon/OfficialDeliciousMap/issues/106)).

    사유별 건수를 밝히면 제출할 수 있다는 기준이지, 0건 기준을 대신하는 수가 아니다. 세지 않은
    값은 0으로 내지 않는다 — `counted_sources`가 False면 원본을 세지 않았다는 뜻이고,
    `classified_records`가 0이면 판정한 레코드가 없다는 뜻이다.
    """

    # 사람 대조가 있는 원본 결함만 담는다. 대조가 없으면 같은 사유라도 미해결로 남는다.
    confirmed_defects: tuple[ConfirmedDefect, ...] = ()
    unresolved_sources: tuple[UnresolvedCount, ...] = ()
    # parse가 원본별 보고를 남겼는지. 위 두 값의 빈 튜플이 0개인지 세지 않은 것인지를 가른다.
    counted_sources: bool = False
    classified_records: int = Field(default=0, ge=0)
    pending_records: int = Field(default=0, ge=0)
    # 지오코딩 판정 대상. 미확정 수의 분모이며 비식당·판단 보류는 대상이 아니다.
    restaurant_records: int = Field(default=0, ge=0)
    unconfirmed_places: tuple[UnconfirmedPlace, ...] = ()
    # 상호 칸에 업소 둘 이상이 적혔는데 사람 확인이 없어 업소별로 가르지 못한 지출 수(#117).
    unsplit_expenses: int = Field(default=0, ge=0)
    # 원본이 이름 없이 수만 밝혀 조회할 이름조차 없는 업소(#127). 미확정 사유와 별개다.
    unnamed_companions: UnnamedCompanions = UnnamedCompanions()

    @model_validator(mode="after")
    def counted_before_reported(self) -> "SubmissionTally":
        if not self.counted_sources and (self.confirmed_defects or self.unresolved_sources):
            raise ValueError("originals cannot be reported without having been counted")
        return self


class ClassifyInput(Contract):
    records: tuple[Record, ...]
    manual: tuple[ManualCorrection, ...] = ()
    restorations: tuple[RestoredName, ...] = ()

    def names(self) -> dict[str, str]:
        """레코드마다 판별할 이름. 규칙은 조회·좌표 판정과 같은 `merchants.chosen_name`이다.

        레코드의 원본 표기는 어느 단계에서도 바뀌지 않는다(#137).
        """
        restored = {item.record_id: item.restored_merchant for item in self.restorations}
        return {
            record.record_id: merchants.chosen_name(record.merchant, restored.get(record.record_id))
            for record in self.records
        }

    @property
    def merchants(self) -> tuple[str, ...]:
        """판별 대상 고유 이름. 무엇을 묻게 되는지 보는 자리이며 `names`와 같은 규칙을 쓴다."""
        return tuple(dict.fromkeys(self.names().values()))


class ClassifyOutput(Contract):
    decisions: tuple[Classification, ...]


class GeocodeInput(Contract):
    dependency_key: Sha256
    records: tuple[Record, ...]
    lookups: tuple[CandidateLookup, ...] = ()
    confirmations: tuple[ConfirmedPlace, ...] = ()
    restorations: tuple[RestoredName, ...] = ()
    previous: tuple[GeocodeResult, ...] = ()
    retry_failed: bool = False
    # 도시 안으로 보는 후보 주소의 접두(레지스트리 `City.address_prefixes`).
    address_prefixes: tuple[Text, ...] = ()
    # 기관 슬러그별 청사 좌표(레지스트리 `City.halls`). 레코드가 적은 기관으로 찾아 쓴다.
    halls: dict[Text, tuple[float, float]] = Field(default_factory=dict)


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
    # 누적 재게시로 합쳐 장부에서 뺀 수. 화면의 자료 범위가 이 수를 함께 낸다.
    repeated_expenses: RepeatedExpenses = RepeatedExpenses()
    # 제출 시점 기준이 공개하는 남은 미해결(#106). 화면의 자료 범위가 사유별로 낸다.
    tally: SubmissionTally = SubmissionTally()
    # 업소 식별자별 업종 원문. 여기 없는 마커는 업종을 모른다(#96).
    categories: dict[Sha256, Text] = Field(default_factory=dict)
    # 기관 실행에서 같은 업소를 이루는 다른 기관의 도시 판정. 합쳐진 좌표를 낸 레코드일 수 있다.
    peers: tuple[GeocodeResult, ...] = ()


class BuildOutput(Contract):
    files: tuple[Path, ...]
    record_count: int = Field(ge=0)
    marker_count: int = Field(ge=0)
