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
    cached = _cached(source, table, stores.cache)
    failures: list[str] = []
    for candidate in cached:
        found = _failure(source, table, candidate)
        if found is None:
            return candidate
        failures.append(found)
    # 캐시가 모두 실패하면 이 원본에서는 쓰지 않는다. 재호출에는 최신 판정의 실패 사유를 싣는다.
    failure: str | None = failures[0] if failures else None
    # 이미 받은 답은 다시 묻지 않고 현재 코드로 다시 검증한다(호출 이력으로 중복 호출 방지).
    key = answers_key(source, table)
    recorded = [
        RecordedAnswer.model_validate(entry.value)
        for entry in read_cache(stores.answers)
        if entry.key == key
    ]
    for previous in recorded:
        _settled(table, previous)
        mapping, failure = _verified(source, table, previous)
        if mapping is not None:
            return _accept(stores, table, mapping, previous)
    if mapper is None:
        raise Unresolved("validation_failed" if recorded else "model_not_configured", table.name)
    # 캐시 미적중이면 최초 호출과 재호출 한 번, 캐시 검증 실패면 재호출 한 번뿐이다.
    # 한도는 모델·지시문이 바뀌어도 이 표에 받은 답 전체로 센다.
    for _ in range(len(recorded), 1 if cached else 2):
        reply = _ask(mapper, stores.budget, source, table, failure)
        if reply.status == "error" and reply.error == "unavailable":
            # 통신 장애는 매핑의 증거가 아니다. 답이 없으므로 이력에 넣지 않는다.
            raise Unresolved("unavailable", table.name)
        fresh = RecordedAnswer(
            answer=reply.answer,
            error=reply.error,
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
        _settled(table, fresh)
        mapping, failure = _verified(source, table, fresh)
        if mapping is not None:
            return _accept(stores, table, mapping, fresh)
    raise Unresolved("validation_failed", failure or table.name)


def _settled(table: grid.Table, answer: RecordedAnswer) -> None:
    """잘리거나 해석할 수 없던 응답, 카드형 표는 자동으로 다시 묻지 않고 미해결로 남긴다."""
    if answer.error is not None:
        raise Unresolved(answer.error, table.name)
    if answer.answer is not None and answer.answer.layout == "key_value":
        raise Unresolved("unsupported_layout", table.name)


def answers_key(source: SourceRef, table: grid.Table) -> str:
    return digest({"policy": POLICY_VERSION, "source": source.source_hash, "table": table.name})


def _verified(
    source: SourceRef, table: grid.Table, recorded: RecordedAnswer
) -> tuple[HeaderMap | None, str | None]:
    if recorded.answer is None:
        return None, None
    try:
        mapping = to_mapping(source, table, recorded.answer)
    except ValidationFailed as exc:
        return None, exc.detail
    failure = _failure(source, table, mapping)
    return (mapping, None) if failure is None else (None, failure)


def _accept(
    stores: _Stores, table: grid.Table, mapping: HeaderMap, recorded: RecordedAnswer
) -> HeaderMap:
    if not mapping.header_rows or mapping.layout != "table":
        return mapping
    return mapping.model_copy(update={"cache": _remember(stores.cache, table, mapping, recorded)})


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


def _cached(source: SourceRef, table: grid.Table, cache_path: Path) -> list[HeaderMap]:
    """이 표의 같은 위치 헤더가 서명과 같은 캐시 판정들. 최신부터이며 검증 전에는 쓰지 않는다.

    같은 헤더가 원본마다 다른 행에 있거나 요약 행 때문에 첫 지출 위치가 다를 수 있다.
    그런 변형은 모두 유효한 판정이므로 최신 하나만 보지 않는다.
    """
    found: list[HeaderMap] = []
    seen: list[CachedHeaderMap] = []
    for entry in reversed(read_cache(cache_path)):
        if not entry.valid:
            continue
        value = CachedHeaderMap.model_validate(entry.value)
        rows = value.header_rows
        if value in seen or max(rows) > len(table.rows) or cache_key(table, rows) != entry.key:
            continue
        seen.append(value)
        found.append(
            HeaderMap(
                source_hash=source.source_hash,
                table=table.name,
                layout="table",
                header_rows=rows,
                data_start_row=max(rows) + value.data_offset,
                columns=value.columns,
                amount_multiplier=value.amount_multiplier,
                cache=CacheRef(key=entry.key, revision=entry.revision),
            )
        )
    return found


def _remember(
    cache_path: Path, table: grid.Table, mapping: HeaderMap, recorded: RecordedAnswer
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
        model=recorded.model,
        prompt_version=recorded.prompt_version,
    ).model_dump(mode="json")
    same = next((entry for entry in previous if entry.valid and entry.value == value), None)
    if same is not None:
        # 이미 있는 판정을 다시 쌓지 않는다. 쌓으면 변형끼리 번갈아 revision이 늘어난다.
        return CacheRef(key=key, revision=same.revision)
    # 조각 사이의 줄 순서가 아니라 revision으로 다음 번호를 정한다.
    entry = CacheEntry(
        key=key,
        revision=max((item.revision for item in previous), default=0) + 1,
        valid=True,
        evidence=f"{recorded.model}/{recorded.prompt_version} verified on "
        f"{mapping.source_hash[:16]}",
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
) -> HeaderMapReply:
    """과금이 일어나는 요청은 모두 공통 예산을 거친다. 예산이 호출을 막으면 미해결로 남긴다."""
    prompt = build_prompt(table, failure)
    if len(prompt) > mapper.max_prompt_chars:
        raise Unresolved("oversized_request", table.name)
    try:
        return budget.spend(
            f"{PURPOSE}:{source.source_hash[:16]}:{table.name}:{uuid.uuid4().hex[:12]}",
            PURPOSE,
            mapper.model,
            mapper.ceiling_usd(prompt),
            f"header mapping for {source.source_hash[:16]} {table.name}",
            lambda: mapper.map(prompt),
            mapper.cost_usd,
        )
    except BudgetUnavailable as exc:
        raise Unresolved(exc.reason, table.name) from None


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
