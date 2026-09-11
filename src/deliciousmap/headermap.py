"""headermap 단계. 표마다 헤더 매핑을 캐시에서 찾거나 모델에 묻고, 코드 검증을 통과한 것만 쓴다.

ADR-0002와 폴백 정책을 따른다. 캐시 적중도 검증하며, 실패한 표는 표마다 한 번만 다시 묻는다.
전량 추출 폴백은 구현하지 않았으므로 끝내 검증에 실패한 원본은 파일 단위 미해결로 남긴다.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from deliciousmap import grid
from deliciousmap.budget import Budget, BudgetUnavailable
from deliciousmap.contracts import (
    CachedHeaderMap,
    CacheEntry,
    CacheRef,
    HeaderMap,
    HeaderMapAnswer,
    HeaderMapOutput,
    HeaderMapReply,
    LlmPurpose,
    RecordedAnswer,
    SourceRef,
    UnresolvedReason,
    UnresolvedSource,
    Usage,
)
from deliciousmap.extract import ValidationFailed, extract, header_signature
from deliciousmap.identity import digest
from deliciousmap.storage import append_cache, read_cache

# 캐시 서명·값의 의미가 바뀌면 올린다. 옛 항목은 지우지 않고 다른 키가 된다.
POLICY_VERSION = "headermap-1"
PURPOSE: LlmPurpose = "header_mapping"
# 모델에 보이는 입력: 비어 있지 않은 상위 12행. 긴 셀은 잘라 입력 크기를 묶는다.
MAX_ROWS = 12
MAX_CELL_CHARS = 40
MULTIPLIERS = {"won": Decimal(1), "thousand_won": Decimal(1000)}


class HeaderMapper(Protocol):
    """표 하나의 입력에 대한 판정만 공급한다. 인증·요청 구성·사용량 해석은 구현 안에 둔다."""

    model: str
    prompt_version: str
    max_prompt_chars: int

    def ceiling_usd(self, prompt: str) -> Decimal: ...
    def cost_usd(self, usage: Usage) -> Decimal: ...
    def map(self, prompt: str) -> HeaderMapReply: ...


class Unresolved(Exception):
    def __init__(self, reason: UnresolvedReason, detail: str = "") -> None:
        self.reason: UnresolvedReason = reason
        self.detail = detail
        super().__init__(reason)


@dataclass(frozen=True)
class _Stores:
    # 도시 무관 헤더 서명 캐시와 원본별 모델 답변 이력.
    cache: Path
    answers: Path
    budget: Budget


def resolve(
    sources: tuple[SourceRef, ...],
    raw_root: Path,
    cache_path: Path,
    answers_path: Path,
    budget: Budget,
    mapper: HeaderMapper | None,
) -> HeaderMapOutput:
    stores = _Stores(cache_path, answers_path, budget)
    mappings: list[HeaderMap] = []
    unresolved: list[UnresolvedSource] = []
    done: set[str] = set()
    for source in sources:
        # 같은 원본이 여러 게시글에 붙어 있어도 한 번만 판정한다.
        if source.source_hash in done:
            continue
        done.add(source.source_hash)
        try:
            tables = grid.read_tables(raw_root / source.path)
            if not tables:
                raise Unresolved("no_table")
            found = [_map_table(source, table, stores, mapper) for table in tables]
        except grid.UnsupportedFormat:
            unresolved.append(
                UnresolvedSource(source_hash=source.source_hash, reason="unsupported_format")
            )
        except grid.UnreadableOriginal:
            unresolved.append(UnresolvedSource(source_hash=source.source_hash, reason="unreadable"))
        except Unresolved as exc:
            unresolved.append(
                UnresolvedSource(
                    source_hash=source.source_hash, reason=exc.reason, detail=exc.detail
                )
            )
        else:
            mappings.extend(found)
    return HeaderMapOutput(mappings=tuple(mappings), unresolved=tuple(unresolved))


def _map_table(
    source: SourceRef, table: grid.Table, stores: _Stores, mapper: HeaderMapper | None
) -> HeaderMap:
    failure: str | None = None
    cached = _cached(source, table, stores.cache)
    if cached is not None:
        failure = _failure(source, table, cached)
        if failure is None:
            return cached
    # 이미 받은 답은 다시 묻지 않고 현재 코드로 다시 검증한다(호출 이력으로 중복 호출 방지).
    key = answers_key(source, table)
    recorded = [
        RecordedAnswer.model_validate(entry.value)
        for entry in read_cache(stores.answers)
        if entry.key == key
    ]
    for previous in recorded:
        mapping, failure = _verified(source, table, previous.answer)
        if mapping is not None:
            return _accept(stores, table, mapping, previous.model, previous.prompt_version)
    if mapper is None:
        raise Unresolved("validation_failed" if recorded else "model_not_configured", table.name)
    # 캐시 미적중이면 최초 호출과 재호출 한 번, 캐시 검증 실패면 재호출 한 번뿐이다.
    # 같은 모델·지시문으로 이미 받은 답도 한도에 들어간다.
    limit = 1 if cached is not None else 2
    used = sum(
        1
        for previous in recorded
        if (previous.model, previous.prompt_version) == (mapper.model, mapper.prompt_version)
    )
    for _ in range(used, limit):
        fresh = RecordedAnswer(
            answer=_ask(mapper, stores.budget, source, table, failure),
            model=mapper.model,
            prompt_version=mapper.prompt_version,
        )
        recorded.append(fresh)
        append_cache(
            stores.answers,
            CacheEntry(
                key=key,
                revision=len(recorded),
                valid=True,
                evidence=f"{fresh.model}/{fresh.prompt_version} {source.source_hash[:16]} "
                f"{table.name}",
                value=fresh.model_dump(mode="json"),
            ),
        )
        mapping, failure = _verified(source, table, fresh.answer)
        if mapping is not None:
            return _accept(stores, table, mapping, fresh.model, fresh.prompt_version)
    raise Unresolved("validation_failed", failure or table.name)


def answers_key(source: SourceRef, table: grid.Table) -> str:
    return digest({"policy": POLICY_VERSION, "source": source.source_hash, "table": table.name})


def _verified(
    source: SourceRef, table: grid.Table, answer: HeaderMapAnswer
) -> tuple[HeaderMap | None, str | None]:
    try:
        mapping = to_mapping(source, table, answer)
    except ValidationFailed as exc:
        return None, exc.detail
    failure = _failure(source, table, mapping)
    return (mapping, None) if failure is None else (None, failure)


def _accept(
    stores: _Stores, table: grid.Table, mapping: HeaderMap, model: str, prompt_version: str
) -> HeaderMap:
    if not mapping.header_rows or mapping.layout != "table":
        return mapping
    return mapping.model_copy(
        update={"cache": _remember(stores.cache, table, mapping, model, prompt_version)}
    )


def to_mapping(source: SourceRef, table: grid.Table, answer: HeaderMapAnswer) -> HeaderMap:
    """모델 답변을 계약으로 옮긴다. 역할이 겹치거나 단위를 모르면 검증 실패다."""
    roles = [column.role for column in answer.columns]
    if len(roles) != len(set(roles)):
        raise ValidationFailed(f"{table.name}: duplicate column role")
    if answer.layout == "table" and (
        answer.data_start_row is None or answer.amount_unit not in MULTIPLIERS
    ):
        raise ValidationFailed(f"{table.name}: missing data start or amount unit")
    if any(row > len(table.rows) for row in answer.header_rows):
        raise ValidationFailed(f"{table.name}: header row outside table")
    return HeaderMap(
        source_hash=source.source_hash,
        table=table.name,
        layout=answer.layout,
        header_rows=answer.header_rows,
        data_start_row=answer.data_start_row or 1,
        year_hint=answer.year_hint,
        columns={column.role: column.column for column in answer.columns},
        amount_multiplier=MULTIPLIERS.get(answer.amount_unit, Decimal(1)),
    )


def _failure(source: SourceRef, table: grid.Table, mapping: HeaderMap) -> str | None:
    try:
        extract(table, mapping, source)
    except ValidationFailed as exc:
        return exc.detail
    return None


def cache_key(table: grid.Table, header_rows: tuple[int, ...]) -> str:
    return digest(
        {
            "policy": POLICY_VERSION,
            "header": [list(row) for row in header_signature(table, header_rows)],
        }
    )


def _cached(source: SourceRef, table: grid.Table, cache_path: Path) -> HeaderMap | None:
    """이 표의 같은 위치 헤더가 캐시 서명과 같으면 적중이다. 적중도 검증 전에는 쓰지 않는다."""
    latest: dict[str, CacheEntry] = {}
    for entry in read_cache(cache_path):
        if entry.valid:
            latest[entry.key] = entry
    for entry in latest.values():
        value = CachedHeaderMap.model_validate(entry.value)
        rows = value.header_rows
        if max(rows) > len(table.rows) or cache_key(table, rows) != entry.key:
            continue
        return HeaderMap(
            source_hash=source.source_hash,
            table=table.name,
            layout="table",
            header_rows=rows,
            data_start_row=max(rows) + value.data_offset,
            columns=value.columns,
            amount_multiplier=value.amount_multiplier,
            cache=CacheRef(key=entry.key, revision=entry.revision),
        )
    return None


def _remember(
    cache_path: Path, table: grid.Table, mapping: HeaderMap, model: str, prompt_version: str
) -> CacheRef | None:
    """검증을 통과한 판정만 쌓는다. 같은 서명의 새 판정은 새 revision이며 옛 판정은 남긴다."""
    if mapping.data_start_row <= max(mapping.header_rows):
        return None
    key = cache_key(table, mapping.header_rows)
    previous = [entry for entry in read_cache(cache_path) if entry.key == key]
    value = CachedHeaderMap(
        header_rows=mapping.header_rows,
        data_offset=mapping.data_start_row - max(mapping.header_rows),
        columns=mapping.columns,
        amount_multiplier=mapping.amount_multiplier,
        model=model,
        prompt_version=prompt_version,
    ).model_dump(mode="json")
    latest = previous[-1] if previous else None
    if latest is not None and latest.valid and latest.value == value:
        return CacheRef(key=key, revision=latest.revision)
    entry = CacheEntry(
        key=key,
        revision=1 if latest is None else latest.revision + 1,
        valid=True,
        evidence=f"{model}/{prompt_version} verified on {mapping.source_hash[:16]}",
        value=value,
    )
    append_cache(cache_path, entry)
    return CacheRef(key=key, revision=entry.revision)


def _ask(
    mapper: HeaderMapper,
    budget: Budget,
    source: SourceRef,
    table: grid.Table,
    failure: str | None,
) -> HeaderMapAnswer:
    """과금이 일어나는 요청은 모두 공통 예산을 거친다. 호출 장애는 잘못된 매핑의 증거가 아니다."""
    prompt = build_prompt(table, failure)
    if len(prompt) > mapper.max_prompt_chars:
        raise Unresolved("oversized_request", table.name)
    try:
        with budget.reserve(
            f"{PURPOSE}:{source.source_hash[:16]}:{table.name}:{uuid.uuid4().hex[:12]}",
            PURPOSE,
            mapper.model,
            mapper.ceiling_usd(prompt),
            f"header mapping for {source.source_hash[:16]} {table.name}",
        ) as reservation:
            reply = mapper.map(prompt)
            if reply.usage is not None:
                reservation.settle(
                    mapper.cost_usd(reply.usage),
                    f"reported usage in={reply.usage.input_tokens} out={reply.usage.output_tokens}",
                )
    except BudgetUnavailable as exc:
        raise Unresolved(exc.reason, table.name) from None
    if reply.answer is None:
        raise Unresolved(reply.error or "invalid_response", table.name)
    return reply.answer


def build_prompt(table: grid.Table, failure: str | None = None) -> str:
    """비어 있지 않은 상위 12행을 원본 행 번호와 함께 싣는다. 시트 이름은 문서 맥락이다."""
    lines = [f"시트: {table.label}"]
    if failure:
        lines.append(f"이전 판정의 코드 검증 실패: {failure}")
    lines.append("격자(R 뒤는 1부터 센 원본 행 번호, [ ] 안은 0부터 센 열 번호):")
    shown = 0
    for number, cells in enumerate(table.rows, start=1):
        values = [(column, grid.text(value)) for column, value in enumerate(cells)]
        values = [(column, value) for column, value in values if value]
        if not values:
            continue
        rendered = " | ".join(f"[{column}]{value[:MAX_CELL_CHARS]}" for column, value in values)
        lines.append(f"R{number}: {rendered}")
        shown += 1
        if shown == MAX_ROWS:
            break
    return "\n".join(lines)
