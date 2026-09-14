"""제공자 조회의 재사용과 공통 계약 합류. 업소 채택 규칙은 여기에 두지 않는다."""

from typing import Protocol

from deliciousmap import merchants
from deliciousmap.contracts import (
    CacheRef,
    CandidateLookup,
    ProviderCandidates,
    ProviderQuery,
    Record,
    RestoredName,
)
from deliciousmap.identity import digest
from deliciousmap.storage import ArtifactStore, LookupCache

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
    providers: tuple[CandidateProvider, ...],
    *,
    retry_failed: bool = False,
) -> tuple[CandidateLookup, ...]:
    """담당자가 후보를 주지 않은 레코드만 조회한다. 기록된 조회 실패는 덮지 않는다."""
    if not providers:
        return supplied
    # 조회 캐시는 여기서 한 번만 읽는다. 레코드 루프가 파일을 다시 파싱하지 않는다.
    cache = store.lookup_cache()
    restored = {item.record_id: item.restored_merchant for item in restorations}
    resolved = []
    for record, prepared in zip(records, supplied, strict=True):
        recorded_failure = prepared.status == "error" and prepared.error != "not_supplied"
        if prepared.candidates or recorded_failure:
            resolved.append(prepared)
            continue
        # 확정 복원명이 있으면 그 이름을, 없으면 꼬리말을 뗀 첫 업소의 이름을 조회한다.
        # 사람 확인이 규칙보다 앞선다. 도시·기관 맥락은 질의에 넣지 않는다.
        query = merchants.chosen_name(record.merchant, restored.get(record.record_id))
        # 사람이 이미 업소별로 본 지출은 나누어 조회할 것이 없다. 확인이 없는 표기만 더 조회한다.
        resolved.append(
            _merge_provider_lookups(
                cache,
                prepared,
                query,
                providers,
                retry_failed=retry_failed,
                probe=record.expense is None,
            )
        )
    return tuple(resolved)


def _merge_provider_lookups(
    cache: LookupCache,
    prepared: CandidateLookup,
    query: str,
    providers: tuple[CandidateProvider, ...],
    *,
    retry_failed: bool,
    probe: bool,
) -> CandidateLookup:
    """제공자마다 조회하고 후보를 출처와 함께 모은다. 한 곳의 실패도 성공으로 숨기지 않는다."""
    candidates = list(prepared.candidates)
    queries = list(prepared.queries)
    status: str = "ok"
    error: str | None = None
    for provider in providers:
        found, cache_ref = _reuse_or_search(cache, provider, query, retry_failed=retry_failed)
        candidates.extend(found.candidates)
        if probe:
            _probe_merged(cache, provider, query, retry_failed=retry_failed)
        queries.append(
            ProviderQuery.model_validate(
                {
                    "provider": provider.provider,
                    "request": query,
                    "interpretation": provider.interpretation,
                    "status": found.status,
                    "error": found.error,
                    "cache": cache_ref,
                }
            )
        )
        if found.status == "error" and status != "error":
            status, error = "error", found.error
    return CandidateLookup.model_validate(
        {
            "scope": prepared.scope,
            "status": status,
            "error": error,
            "facts": prepared.facts,
            "candidates": tuple(candidates),
            "queries": tuple(queries),
        }
    )


def _probe_merged(
    cache: LookupCache, provider: CandidateProvider, query: str, *, retry_failed: bool
) -> None:
    """합쳐 적은 상호를 나눈 이름으로도 조회해 캐시에 쌓는다. 판정에는 쓰지 않는다.

    규칙은 조회만 한다([#117](https://github.com/snowjaewon/OfficialDeliciousMap/issues/117)).
    나눈 이름의 후보를 그대로 판정에 넣으면 규칙이 업소를 확정하게 되고, `그저,쉼` 같은 한
    업소를 둘로 만든다. 쌓아 둔 후보는 사람이 업소별로 확인할 때 읽는다.
    """
    found = merchants.parts(query)
    if len(found) == 1:
        return
    for part in found:
        _reuse_or_search(cache, provider, part, retry_failed=retry_failed)


def _reuse_or_search(
    cache: LookupCache, provider: CandidateProvider, query: str, *, retry_failed: bool
) -> tuple[ProviderCandidates, CacheRef]:
    key = request_key(provider, query)
    previous = cache.cached_candidates(key)
    if previous is not None:
        found = ProviderCandidates.model_validate(previous.value)
        if not (retry_failed and found.status == "error"):
            return found, CacheRef(key=key, revision=previous.revision)
    found = provider.search(query)
    revision = cache.remember_candidates(key, found, _evidence(provider, found))
    return found, CacheRef(key=key, revision=revision)


def _evidence(provider: CandidateProvider, found: ProviderCandidates) -> str:
    """상호·주소·응답 원문 없이 조회의 결과만 남긴다."""
    return (
        f"{provider.provider}/{provider.interpretation} "
        f"{found.error or found.status} candidates={len(found.candidates)}"
    )
