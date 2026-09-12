"""개발자 PC에서 도는 운영 어댑터. 게시판 수집부터 정제 출력까지다.

외부 서비스(게시판·모델·후보 조회)는 컨텍스트가 건네는 경계로만 닿는다.
"""

from deliciousmap import classify, extract, headermap
from deliciousmap.boards import default_transport
from deliciousmap.budget import Budget
from deliciousmap.collection import collect
from deliciousmap.contracts import (
    BuildInput,
    BuildOutput,
    ClassifyInput,
    ClassifyOutput,
    ClosureInput,
    ClosureOutput,
    ClosureResult,
    FetchInput,
    FetchOutput,
    GeocodeInput,
    GeocodeOutput,
    HeaderMapInput,
    HeaderMapOutput,
    ParseInput,
    ParseOutput,
)
from deliciousmap.identity import decide_identity, lookup_key, reconcile_coordinates
from deliciousmap.pipeline import AdapterFailure, ExecutionContext, FailureCause
from deliciousmap.site import collection_status, write_city_data, write_site_shell

# 원본·표마다 받은 헤더 매핑 답의 이력. 도시 무관 서명 캐시와 달리 원본에 묶인다.
HEADERMAP_ANSWERS = "headermap-answers-v1.jsonl"


class LocalAdapters:
    def fetch(self, value: FetchInput, context: ExecutionContext) -> FetchOutput:
        return collect(value.target, context.paths, context.board_transport or default_transport())

    def headermap(self, value: HeaderMapInput, context: ExecutionContext) -> HeaderMapOutput:
        return headermap.resolve(
            value.sources,
            context.paths.raw_root,
            context.paths.shared("headermap"),
            context.paths.city_dir(context.target) / HEADERMAP_ANSWERS,
            Budget(context.paths.shared("llm-budget")),
            context.header_mapper,
        )

    def parse(self, value: ParseInput, context: ExecutionContext) -> ParseOutput:
        return extract.parse_sources(
            value.sources, value.mappings, value.unresolved, context.paths.raw_root
        )

    def classify(self, value: ClassifyInput, context: ExecutionContext) -> ClassifyOutput:
        return classify.resolve(
            value,
            context.target.city.slug,
            context.paths.shared("classify"),
            Budget(context.paths.shared("llm-budget")),
            context.classifier,
        )

    def geocode(self, value: GeocodeInput, context: ExecutionContext) -> GeocodeOutput:
        lookups = {item.scope.record_id: item for item in value.lookups}
        confirmations = {item.scope.record_id: item for item in value.confirmations}
        restorations = {item.record_id: item for item in value.restorations}
        previous = {item.lookup_key: item for item in value.previous}
        results = []
        for record in value.records:
            lookup = lookups[record.record_id]
            confirmation = confirmations.get(record.record_id)
            restored = restorations.get(record.record_id)
            key = lookup_key(record, lookup, confirmation, restored, value.dependency_key)
            cached = previous.get(key)
            if cached is not None and (cached.status == "success" or not value.retry_failed):
                results.append(cached)
            else:
                results.append(
                    decide_identity(
                        record,
                        lookup,
                        confirmation,
                        restored,
                        dependency_key=value.dependency_key,
                    )
                )
        return GeocodeOutput(results=reconcile_coordinates(tuple(results)))

    def closure(self, value: ClosureInput, context: ExecutionContext) -> ClosureOutput:
        return ClosureOutput(
            results=tuple(
                ClosureResult(
                    business_id=candidate.business_id,
                    status="unknown",
                    evidence="license-evidence-not-supplied",
                )
                for candidate in value.candidates
            )
        )

    def build(self, value: BuildInput, context: ExecutionContext) -> BuildOutput:
        directory = context.paths.output_root / context.target.city.slug
        if context.target.org:
            directory = directory / "orgs" / context.target.org
        files = write_city_data(directory, context.target, value)
        # 기관 실행은 도시 전체 화면을 덮어쓰지 않도록 데이터 파일만 낸다.
        if context.target.org is None:
            if context.map_key is None:
                raise AdapterFailure(FailureCause.MISSING_CONFIGURATION)
            files += write_site_shell(
                context.paths.output_root,
                context.target.city,
                directory,
                context.map_key,
                collection_status(context.target.organizations, value.records),
            )
        return BuildOutput(
            files=files,
            record_count=len(value.records),
            marker_count=len(value.candidates),
        )
