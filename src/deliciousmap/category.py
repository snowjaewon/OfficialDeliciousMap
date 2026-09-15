"""확정 업소의 업종 조회와 재사용. 업종은 표시용이며 업소 판정과 판정 키에 들어가지 않는다.

업종은 업소를 확정한 후보에 그 제공자가 붙인 원문이다. 그 후보를 찾은 조회를 같은 제공자에게
다시 묻고, 확정한 후보와 출처가 같은 항목의 업종만 쓴다. 다른 후보·다른 제공자의 업종으로 채우지
않는다([#96](https://github.com/snowjaewon/OfficialDeliciousMap/issues/96)).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from deliciousmap.contracts import GeocodeResult, ProviderCategories
from deliciousmap.identity import coordinate_origin, digest
from deliciousmap.storage import LookupCache

POLICY_VERSION = "category-1"
# 업종을 모르는 마커의 값. 다른 업종으로 채우지 않는다.
UNKNOWN = "미상"


class CategorySource(Protocol):
    """후보 출처별 업종 원문만 공급한다. 인증·요청 구성·응답 해석은 구현 안에 둔다."""

    provider: str
    interpretation: str

    def categories(self, query: str) -> ProviderCategories: ...


@dataclass(frozen=True)
class Request:
    """업소를 확정한 후보를 찾은 조회와 그 후보의 출처."""

    provider: str
    interpretation: str
    query: str
    source_id: str

    @property
    def key(self) -> str:
        """제공자·해석 버전·질의가 같으면 같은 업종 조회다."""
        return digest(
            {
                "policy": POLICY_VERSION,
                "provider": self.provider,
                "interpretation": self.interpretation,
                "query": self.query,
            }
        )


def requests(results: Iterable[GeocodeResult]) -> dict[str, Request | None]:
    """업소마다 첫 레코드의 근거로 업종 조회를 정한다. 마커가 출처·주소를 밝히는 규칙과 같다.

    담당자가 준비한 후보처럼 조회로 찾지 않은 후보는 다시 물을 요청이 없어 `None`이다.
    """
    found: dict[str, Request | None] = {}
    for result in results:
        if result.status != "success" or result.business_id is None:
            continue
        if result.business_id in found:
            continue
        source, _ = coordinate_origin(result)
        query = next(
            (
                item
                for item in result.lookup.queries
                if item.provider == source.provider and item.status == "ok"
            ),
            None,
        )
        found[result.business_id] = (
            None
            if query is None
            else Request(source.provider, query.interpretation, query.request, source.source_id)
        )
    return found


def resolve(
    cache: LookupCache,
    results: Iterable[GeocodeResult],
    sources: Iterable[CategorySource],
    *,
    retry_failed: bool = False,
) -> bool:
    """확정 업소의 업종을 조회해 캐시에 쌓는다. 실패한 조회가 남으면 `True`를 돌려준다.

    기록된 실패는 명시적 재시도 전까지 다시 묻지 않는다. 해석 버전이 조회 때와 다른 제공자는
    후보 출처를 같은 규칙으로 만들지 않으므로 묻지 않는다.
    """
    configured = {(item.provider, item.interpretation): item for item in sources}
    failed = False
    asked: set[str] = set()
    for request in requests(results).values():
        if request is None or request.key in asked:
            continue
        source = configured.get((request.provider, request.interpretation))
        if source is None:
            continue
        asked.add(request.key)
        previous = cache.cached_candidates(request.key)
        found = None if previous is None else ProviderCategories.model_validate(previous.value)
        if found is None or (retry_failed and found.status == "error"):
            found = source.categories(request.query)
            cache.remember_candidates(request.key, found, _evidence(source, found))
        failed = failed or found.status == "error"
    return failed


def published(cache: LookupCache, results: Iterable[GeocodeResult]) -> Mapping[str, str]:
    """업소 식별자별 업종 원문. 확정한 후보의 업종을 알 수 없는 업소는 싣지 않는다."""
    found = {}
    for business_id, request in requests(results).items():
        if request is None:
            continue
        entry = cache.cached_candidates(request.key)
        if entry is None:
            continue
        answer = ProviderCategories.model_validate(entry.value)
        category = next(
            (item.category for item in answer.categories if item.source_id == request.source_id),
            None,
        )
        if category is not None:
            found[business_id] = category
    return found


def _evidence(source: CategorySource, found: ProviderCategories) -> str:
    """상호·업종·응답 원문 없이 조회의 결과만 남긴다."""
    return (
        f"{source.provider}/{source.interpretation} "
        f"{found.error or found.status} categories={len(found.categories)}"
    )
