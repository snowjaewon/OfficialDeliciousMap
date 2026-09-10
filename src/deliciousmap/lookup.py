"""제공자 조회의 재사용과 공통 계약 합류. 업소 채택 규칙은 여기에 두지 않는다."""

from typing import Protocol

from deliciousmap.contracts import (
    CacheRef,
    CandidateLookup,
    ProviderCandidates,
    Record,
    RestoredName,
)
from deliciousmap.identity import digest
from deliciousmap.storage import ArtifactStore

POLICY_VERSION = "lookup-1"


class CandidateProvider(Protocol):
    """후보 사실만 공급한다. 인증·요청 구성·응답 해석은 구현 안에 둔다."""

    provider: str
    interpretation: str
    limit: int

    def search(self, query: str) -> ProviderCandidates: ...


def request_key(provider: CandidateProvider, query: str) -> str:
    """제공자·요청 맥락·해석 버전이 다르면 다른 조회다."""
    return digest(
        {
            "policy": POLICY_VERSION,
            "provider": provider.provider,
            "interpretation": provider.interpretation,
            "request": {"query": query, "limit": provider.limit},
        }
    )


def resolve(
    store: ArtifactStore,
    records: tuple[Record, ...],
    supplied: tuple[CandidateLookup, ...],
    restorations: tuple[RestoredName, ...],
    provider: CandidateProvider | None,
    *,
    retry_failed: bool = False,
) -> tuple[CandidateLookup, ...]:
    """담당자가 후보를 주지 않은 레코드만 조회한다. 기록된 조회 실패는 덮지 않는다."""
    if provider is None:
        return supplied
    restored = {item.record_id: item.restored_merchant for item in restorations}
    resolved = []
    for record, prepared in zip(records, supplied, strict=True):
        recorded_failure = prepared.status == "error" and prepared.error != "not_supplied"
        if prepared.candidates or recorded_failure:
            resolved.append(prepared)
            continue
        # 확정 복원명이 있으면 그 이름으로 조회한다. 도시·기관 맥락은 질의에 넣지 않는다.
        query = restored.get(record.record_id, record.merchant)
        found, cache = _reuse_or_search(store, provider, query, retry_failed=retry_failed)
        resolved.append(
            CandidateLookup.model_validate(
                {
                    "scope": prepared.scope,
                    "status": found.status,
                    "error": found.error,
                    "facts": prepared.facts,
                    "candidates": found.candidates,
                    "queries": (
                        *prepared.queries,
                        {
                            "provider": provider.provider,
                            "request": query,
                            "interpretation": provider.interpretation,
                            "status": found.status,
                            "error": found.error,
                            "cache": cache,
                        },
                    ),
                }
            )
        )
    return tuple(resolved)


def _reuse_or_search(
    store: ArtifactStore, provider: CandidateProvider, query: str, *, retry_failed: bool
) -> tuple[ProviderCandidates, CacheRef]:
    key = request_key(provider, query)
    previous = store.cached_candidates(key)
    if previous is not None:
        found = ProviderCandidates.model_validate(previous.value)
        if not (retry_failed and found.status == "error"):
            return found, CacheRef(key=key, revision=previous.revision)
    found = provider.search(query)
    revision = store.remember_candidates(key, found, _evidence(provider, found), previous)
    return found, CacheRef(key=key, revision=revision)


def _evidence(provider: CandidateProvider, found: ProviderCandidates) -> str:
    """상호·주소·응답 원문 없이 조회의 결과만 남긴다."""
    return (
        f"{provider.provider}/{provider.interpretation} "
        f"{found.error or found.status} candidates={len(found.candidates)}"
    )
