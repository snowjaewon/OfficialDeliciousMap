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
# 동일성 판단에 필요한 근거만 남기기 위한 상한. 원본 전체를 옮겨 적는 용도가 아니다.
Excerpt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


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
    status: Literal["restaurant", "non_restaurant", "pending"]
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


class IdentityFacts(Contract):
    merchant: Text
    # None means unknown; an empty branch explicitly means an unbranched business.
    branch: str | None = None
    address: Text | None = None
    source: Text


class CandidateSource(Contract):
    provider: Literal["local", "naver", "license"]
    source_id: Text
    reference: Text


class PlaceCandidate(Contract):
    source: CandidateSource
    merchant: Text
    branch: str | None = None
    address: Text | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)


class CandidateLookup(Contract):
    scope: EvidenceScope
    status: Literal["ok", "error"]
    error: Literal["unavailable", "invalid_response", "not_supplied"] | None = None
    facts: tuple[IdentityFacts, ...] = ()
    candidates: tuple[PlaceCandidate, ...] = ()

    @model_validator(mode="after")
    def consistent_lookup(self) -> "CandidateLookup":
        if (self.status == "error") != (self.error is not None):
            raise ValueError("lookup errors require an explicit error code")
        return self


class CandidateFile(Contract):
    schema_version: Literal[1] = 1
    lookups: tuple[CandidateLookup, ...]


class IdentityConfirmation(Contract):
    scope: EvidenceScope
    candidate_source: CandidateSource
    merchant: Text
    branch: str
    address: Text
    evidence: Text


class GeocodeResult(Contract):
    record_id: Text
    merchant: Text
    status: Literal["success", "failed"]
    reason: Literal[
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
            or self.reason not in {"matched", "human_confirmed"}
        ):
            raise ValueError("success requires a confirmed business")
        if self.status == "failed" and (
            self.business_id is not None
            or self.confirmed_merchant is not None
            or self.reason in {"matched", "human_confirmed"}
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
