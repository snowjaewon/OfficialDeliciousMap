"""표 하나에서 헤더 매핑대로 레코드를 뽑고 폴백 정책의 코드 검증을 적용한다.

지출 후보 전부가 날짜·금액·상호를 갖춰야 표가 통과한다. 값을 추측해 채우지 않는다.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import combinations
from pathlib import Path
from typing import Literal, NamedTuple

from deliciousmap import period
from deliciousmap.contracts import (
    ExpenseScope,
    HeaderMap,
    ParseOutput,
    Record,
    RecordOrigin,
    RepeatConfirmation,
    RepeatedExpenses,
    SourceRef,
    SourceReport,
    TotalCheck,
    UnresolvedSource,
)
from deliciousmap.grid import Cell, Table, UnreadableOriginal, UnsupportedFormat, read_tables, text
from deliciousmap.privacy import scrub, scrub_merchant

# 공백을 지운 셀 글자에 적용한다. `2월 소계`·`합 계`처럼 앞말이 붙거나 띄어 쓴 표기도 있다.
TOTAL = re.compile(r"합계|총계|총합계|계")
# 누계·기간 합계는 앞 표까지 더했거나 일부 구간만 더했을 수 있어 대조 범위를 확정할 수 없다.
PERIOD = r"(\d{1,2}(~\d{1,2})?월|\d(~\d)?분기|\d{4}년)"
UNCLEAR_TOTAL = re.compile(rf"{PERIOD}?누계|{PERIOD}(합계|총계|계)")
SUBTOTAL = re.compile(r".{0,6}소계")
# 표 끝을 알리는 행. 원본에서는 글자마다 칸을 나눠 적기도 한다(`이 | 하 | 빈 | 칸`).
TERMINATOR = re.compile(r"(이하)?(빈칸|여백|없음)\.?")
# 엑셀 1900 체계의 날짜 일련번호가 2000~2099년에 해당하는 범위.
SERIAL_RANGE = (36526, 73051)
EXCEL_EPOCH = datetime(1899, 12, 30)


class ValidationFailed(Exception):
    """표가 코드 검증을 통과하지 못했다. 사유는 위치와 항목만 담고 원본 값은 담지 않는다."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class Extraction:
    records: tuple[Record, ...]
    candidates: int
    out_of_range: int
    # 분모에서 뺀 행의 위치와 종류, 사람이 다시 볼 레코드의 위치와 사유.
    excluded: tuple[str, ...]
    review: tuple[str, ...]
    total_check: TotalCheck


@dataclass(frozen=True)
class _Candidate:
    row: int
    spent_on: date
    merchant: str
    amount: Decimal


def extract(table: Table, mapping: HeaderMap, source: SourceRef) -> Extraction:
    if mapping.layout == "none":
        return Extraction((), 0, 0, (), (), "absent")
    if mapping.layout != "table":
        raise ValidationFailed(f"{table.name}: unsupported layout")
    columns = mapping.columns
    dated = "spent_on" in columns or {"month", "day"} <= columns.keys()
    if not dated or not {"merchant", "amount_krw"} <= columns.keys():
        raise ValidationFailed(f"{table.name}: missing required roles")
    headers = {
        _signature(table.rows[row - 1]) for row in mapping.header_rows if row <= len(table.rows)
    }
    # 헤더를 되풀이한 시트는 구역마다 따로 합계를 갖는다. 첫 구역은 헤더 아래 요약 행부터 본다.
    sections: list[_Section] = [_Section()]
    for row in range(max(mapping.header_rows, default=0) + 1, mapping.data_start_row):
        kind = _kind(table, mapping, headers, row)
        if kind == "candidate":
            # 다른 표에서 배운 시작 위치가 이 표의 첫 지출을 건너뛰게 두지 않는다.
            raise ValidationFailed(f"{table.name}:R{row} expense before data start")
        if kind == "total":
            sections[0].totals.append((row, _amount(table.cell(row, columns["amount_krw"]))))
        elif kind == "unclear_total":
            sections[0].unclear = True
    excluded: list[str] = []
    for row in range(mapping.data_start_row, len(table.rows) + 1):
        kind = _kind(table, mapping, headers, row)
        if kind == "candidate":
            sections[-1].candidates.append(_candidate(table, mapping, row))
            continue
        excluded.append(f"{table.name}:R{row} {kind}")
        if kind == "header":
            sections.append(_Section())
        elif kind == "total":
            sections[-1].totals.append((row, _amount(table.cell(row, columns["amount_krw"]))))
        elif kind == "unclear_total":
            sections[-1].unclear = True
    candidates = [item for section in sections for item in section.candidates]
    check = _check_totals(table, sections, mapping.amount_multiplier)
    records = tuple(
        _record(table, mapping, source, candidate)
        for candidate in candidates
        if period.contains(candidate.spent_on)
    )
    return Extraction(
        records=records,
        candidates=len(candidates),
        out_of_range=len(candidates) - len(records),
        excluded=tuple(excluded),
        # 원본에 실제로 있는 0원·음수는 추출 오류로 단정하지 않고 재검증 리포트의 검토 대상이다.
        review=tuple(
            f"{record.source_location} non_positive_amount"
            for record in records
            if record.amount_krw <= 0
        ),
        total_check=check,
    )


def count_candidates(table: Table, mapping: HeaderMap) -> int | None:
    """검증에 실패한 매핑으로도 지출 후보만 센다. 값이 온전하지 않다고 후보에서 빼지 않는다.

    폴백 정책의 분모는 추출 성공 레코드가 아니라 원본에서 식별한 지출 후보 전체다. 역할이
    모자라 후보 범위 자체를 가를 수 없으면 세지 않고 `알 수 없음`으로 돌린다.
    """
    if mapping.layout == "none":
        return 0
    columns = mapping.columns
    dated = "spent_on" in columns or {"month", "day"} <= columns.keys()
    if mapping.layout != "table" or not dated or not {"merchant", "amount_krw"} <= columns.keys():
        return None
    headers = {
        _signature(table.rows[row - 1]) for row in mapping.header_rows if row <= len(table.rows)
    }
    # `extract`와 같은 범위를 본다 — 헤더 아래 전부이며, 첫 지출 위치를 잘못 잡아도 세는 수는 같다.
    return sum(
        _kind(table, mapping, headers, row) == "candidate"
        for row in range(max(mapping.header_rows, default=0) + 1, len(table.rows) + 1)
    )


def _unresolved_candidates(rejected: list[HeaderMap], path: Path) -> int | None:
    """미해결 원본의 후보 수. 표 하나라도 매핑이 없으면 모르는 것이며 0건으로 바꾸지 않는다."""
    if not rejected:
        return None
    try:
        tables = {table.name: table for table in read_tables(path)}
    except (UnsupportedFormat, UnreadableOriginal):
        return None
    if {mapping.table for mapping in rejected} != set(tables):
        return None
    counted = [count_candidates(tables[mapping.table], mapping) for mapping in rejected]
    return None if any(item is None for item in counted) else sum(item or 0 for item in counted)


def parse_sources(
    sources: tuple[SourceRef, ...],
    mappings: tuple[HeaderMap, ...],
    unresolved: tuple[UnresolvedSource, ...],
    raw_root: Path,
    confirmations: tuple[RepeatConfirmation, ...] = (),
    rejected: tuple[HeaderMap, ...] = (),
) -> ParseOutput:
    """원본마다 모든 표가 통과해야 레코드를 낸다. 실패한 원본의 일부만 확정하지 않는다."""
    by_source: dict[str, list[HeaderMap]] = {}
    for mapping in mappings:
        by_source.setdefault(mapping.source_hash, []).append(mapping)
    unused: dict[str, list[HeaderMap]] = {}
    for mapping in rejected:
        unused.setdefault(mapping.source_hash, []).append(mapping)
    failed = {item.source_hash: item for item in unresolved}
    records: list[Record] = []
    reports: dict[str, SourceReport] = {}
    for source in sources:
        if source.source_hash in reports:
            continue
        if source.source_hash in failed:
            item = failed[source.source_hash]
            reports[source.source_hash] = SourceReport(
                source_hash=source.source_hash,
                status="unresolved",
                reason=item.reason,
                detail=item.detail,
                candidates=_unresolved_candidates(
                    unused.get(source.source_hash, []), raw_root / source.path
                ),
            )
            continue
        try:
            tables = {table.name: table for table in read_tables(raw_root / source.path)}
            results = [
                extract(tables[mapping.table], mapping, source)
                for mapping in by_source[source.source_hash]
            ]
        except UnsupportedFormat:
            reports[source.source_hash] = SourceReport(
                source_hash=source.source_hash, status="unresolved", reason="unsupported_format"
            )
            continue
        except (UnreadableOriginal, KeyError):
            reports[source.source_hash] = SourceReport(
                source_hash=source.source_hash, status="unresolved", reason="unreadable"
            )
            continue
        except ValidationFailed as exc:
            reports[source.source_hash] = SourceReport(
                source_hash=source.source_hash,
                status="unresolved",
                reason="validation_failed",
                detail=exc.detail,
            )
            continue
        candidates = sum(result.candidates for result in results)
        excluded = tuple(row for result in results for row in result.excluded)
        if candidates == 0:
            # 집행 없음을 확인할 근거가 없으므로 0건 통과로 두지 않는다.
            reports[source.source_hash] = SourceReport(
                source_hash=source.source_hash,
                status="unresolved",
                reason="no_candidates",
                candidates=0,
                excluded=excluded,
            )
            continue
        found = [record for result in results for record in result.records]
        checks = {result.total_check for result in results if result.candidates}
        records.extend(found)
        reports[source.source_hash] = SourceReport(
            source_hash=source.source_hash,
            status="parsed",
            candidates=candidates,
            records=len(found),
            out_of_range=candidates - len(found),
            excluded=excluded,
            review=tuple(row for result in results for row in result.review),
            total_check="matched"
            if checks == {"matched"}
            else "ambiguous"
            if "ambiguous" in checks
            else "absent",
        )
    merged = merge_repeats(tuple(records), sources, confirmations)
    kept = Counter(record.source_hash for record in merged.records)
    return ParseOutput(
        records=merged.records,
        empty_reason=None if merged.records else "no records in the reporting period",
        sources=tuple(
            item
            if item.status == "unresolved"
            else item.model_copy(
                update={
                    "records": kept[item.source_hash],
                    "repeated": item.records - kept[item.source_hash],
                }
            )
            for item in reports.values()
        ),
        reporting_period=f"{period.START.isoformat()}/{period.END.isoformat()}",
        repeated_expenses=merged.tally,
    )


class ExpenseKey(NamedTuple):
    """지출 하나의 동일성(ADR-0004). 집행목적은 재게시가 다시 쓰므로 넣지 않는다."""

    organization: str
    department: str
    spent_on: date
    merchant: str
    amount_krw: Decimal

    @classmethod
    def of(cls, item: Record | ExpenseScope) -> "ExpenseKey":
        """레코드와 사람이 선언한 범위에서 같은 칸을 읽는다. 동일성 목록은 이 클래스 하나다."""
        return cls(*(getattr(item, name) for name in cls._fields))


# 원본 하나가 실은 지출과 그 횟수. 재게시 판정은 이 둘을 견주어 한다.
Carried = Counter[ExpenseKey]


@dataclass(frozen=True)
class Merge:
    """누적 재게시를 합친 결과와 그 집계."""

    records: tuple[Record, ...]
    tally: RepeatedExpenses


def merge_repeats(
    records: tuple[Record, ...],
    sources: tuple[SourceRef, ...],
    confirmations: tuple[RepeatConfirmation, ...] = (),
) -> Merge:
    """원본을 넘어 반복된 지출을 한 건으로 모은다([ADR-0004](
    ../../docs/adr/0004-merge-repeated-reposts.md)).

    누적 파일·정정본은 이미 공개한 기간을 다시 싣는다. 두 원본이 같은 지출을 2건 이상 함께 실을
    때만 재게시로 보고 합친다. 근거가 그에 못 미치면 줄이지 않고 남긴 수를 집계에 싣는다.

    사람이 원본을 대조해 확정한 묶음은 그 확정을 기준보다 먼저 적용한다([ADR-0006](
    ../../docs/adr/0006-human-confirmed-reposts.md)). 확정으로 합친 수와 확정으로 남긴 수는
    자동 판정과 섞지 않는다.
    """
    posted = {source.source_hash: source.posted or date.max for source in sources}
    # 게시 순서. 게시일을 모르거나 같은 날 올라왔으면 해시로 차례를 고정한다.
    published = {
        item: index
        for index, item in enumerate(
            sorted(
                {record.source_hash for record in records},
                key=lambda item: (posted.get(item, date.max), item),
            )
        )
    }
    carried: dict[str, Carried] = {}
    groups: dict[ExpenseKey, dict[str, list[Record]]] = {}
    for record in records:
        expense = ExpenseKey.of(record)
        carried.setdefault(record.source_hash, Counter())[expense] += 1
        groups.setdefault(expense, {}).setdefault(record.source_hash, []).append(record)
    decided = _decisions(confirmations, groups)
    reposted = {
        pair
        for found in groups.values()
        if len(found) > 1
        for pair in combinations(sorted(found, key=published.__getitem__), 2)
        if _reposted(carried[pair[0]], carried[pair[1]], _confirmed_separate(decided, pair))
    }
    kept: list[Record] = []
    counted: list[_Counted] = []
    for expense, found in groups.items():
        decision = decided.get(expense)
        declared = set(decision.scope.sources) if decision else set()
        hashes = sorted(found, key=published.__getitem__)
        pairs = {pair for pair in combinations(hashes, 2) if set(pair) <= declared}
        components = _components(hashes, reposted | pairs if _joins(decision) else reposted - pairs)
        if _separates(decision) and any(len(declared & set(item)) > 1 for item in components):
            # 다른 원본을 거쳐 이어지면 사람이 가른 두 원본이 한 건이 된다. 확정이 우선이므로
            # 기준을 조용히 따르지 않고, 그 지출을 다시 읽어야 한다고 알린다(ADR-0006).
            raise ValueError("a repost relation joins originals confirmed to be separate expenses")
        keepers: dict[str, int] = {}
        for component in components:
            ranked = sorted(component, key=published.__getitem__)
            # 한 원본이 적은 최대 건수를 남기고, 같으면 가장 먼저 게시된 원본의 것을 남긴다.
            keeper = max(ranked, key=lambda item: len(found[item]))
            repeats = tuple(
                RecordOrigin(source_hash=record.source_hash, location=record.source_location)
                for item in ranked
                if item != keeper
                for record in found[item]
            )
            kept.extend(record.model_copy(update={"repeats": repeats}) for record in found[keeper])
            keepers[keeper] = len(found[keeper])
        dropped = _dropped(found, components)
        # 기준이 이미 합쳤을 수는 자동의 몫이다. 확정이 더 합친 만큼만 사람이 적용한 수다.
        merged = _dropped(found, _components(hashes, reposted)) if _joins(decision) else dropped
        # 별개 지출로 확정해 장부에 남은 수. 확정이 적은 원본들이 남긴 레코드에서 한 몫을 뺀다.
        apart = [keepers.get(item, 0) for item in declared] if _separates(decision) else []
        separated = sum(apart) - max(apart, default=0)
        # 한 묶음에 재게시 관계가 아닌 원본이 남아 있으면 가를 근거가 없어 남긴 것이다.
        remaining = sum(len(item) for item in found.values()) - dropped
        counted.append(
            _Counted(
                merged=merged,
                confirmed=dropped - merged,
                separated=separated,
                left=remaining - max(len(item) for item in found.values()) - separated,
            )
        )
    position = {record.record_id: index for index, record in enumerate(records)}
    return Merge(
        # 합치기 전 순서를 그대로 둔다. 레코드 차례가 원본·행 순서를 따르게 하기 위해서다.
        records=tuple(sorted(kept, key=lambda record: position[record.record_id])),
        tally=RepeatedExpenses(
            merged_expenses=sum(1 for item in counted if item.merged),
            merged_records=sum(item.merged for item in counted),
            unmerged_expenses=sum(1 for item in counted if item.left),
            unmerged_records=sum(item.left for item in counted),
            confirmed_expenses=sum(1 for item in counted if item.confirmed),
            confirmed_records=sum(item.confirmed for item in counted),
            separate_expenses=sum(1 for item in counted if item.separated),
            separate_records=sum(item.separated for item in counted),
        ),
    )


class _Counted(NamedTuple):
    """지출 묶음 하나의 집계. 합치고 남긴 수를 자동 판정과 사람 확정으로 나누어 센다."""

    # 기준이 합친 수와, 확정이 기준보다 더 합친 수.
    merged: int
    confirmed: int
    # 사람이 별개 지출로 확정해 남긴 수와, 가를 근거가 없어 남긴 수.
    separated: int
    left: int


def _decisions(
    confirmations: tuple[RepeatConfirmation, ...],
    groups: dict[ExpenseKey, dict[str, list[Record]]],
) -> dict[ExpenseKey, RepeatConfirmation]:
    """사람이 확정한 판정을 지출 묶음에 붙인다.

    장부에 없는 묶음이나 그 지출을 싣지 않은 원본을 가리키는 확정은 낡은 기록이다. 조용히
    지나가면 사람이 확정했다고 여긴 묶음이 그대로 남으므로 그 사실을 알린다.
    """
    decided: dict[ExpenseKey, RepeatConfirmation] = {}
    for item in confirmations:
        expense = ExpenseKey.of(item.scope)
        if expense in decided:
            raise ValueError("one expense cannot carry two repeat confirmations")
        if not set(item.scope.sources) <= groups.get(expense, {}).keys():
            raise ValueError("repeat confirmation for an expense that is not in the ledger")
        decided[expense] = item
    return decided


def _joins(decision: RepeatConfirmation | None) -> bool:
    """이 확정이 원본을 잇는 쪽인지. 별개 지출 확정은 잇지 않으므로 기준과 견주지 않는다."""
    return decision is not None and decision.decision == "same_expense"


def _separates(decision: RepeatConfirmation | None) -> bool:
    """이 확정이 원본을 가르는 쪽인지."""
    return decision is not None and decision.decision == "separate_expenses"


def _dropped(found: dict[str, list[Record]], components: list[list[str]]) -> int:
    """이 덩어리들로 합치면 빠지는 레코드 수. 덩어리마다 한 원본이 적은 최대 건수만 남는다."""
    return sum(
        sum(len(found[item]) for item in component) - max(len(found[item]) for item in component)
        for component in components
    )


def _components(hashes: list[str], reposted: set[tuple[str, str]]) -> list[list[str]]:
    """재게시 관계로 이어진 원본끼리 묶는다. 관계는 두 원본씩 보고 이어 붙인다."""
    components: list[list[str]] = []
    for source in hashes:
        joined = [source]
        apart: list[list[str]] = []
        for item in components:
            if any({(name, source), (source, name)} & reposted for name in item):
                joined += item
            else:
                apart.append(item)
        components = [*apart, joined]
    return components


def _reposted(carried: Carried, other: Carried, apart: set[ExpenseKey]) -> bool:
    """두 원본이 같은 장부를 다시 실은 관계인지. 같은 지출을 2건 이상 함께 실으면 그렇다.

    한 건은 같은 날 같은 곳에서 같은 금액을 쓴 우연일 수 있다(원본 안에서 실제로 나온다).
    한 쌍에서 그 우연이 둘 겹치지는 않는다. 근거가 한 건뿐이면 가르지 않고 남긴다(ADR-0004).

    사람이 별개 지출로 확정한 묶음은 같은 지출이 아니라고 확인된 것이므로 근거에서 뺀다.
    """
    return sum(count for expense, count in (carried & other).items() if expense not in apart) >= 2


def _confirmed_separate(
    decided: dict[ExpenseKey, RepeatConfirmation], pair: tuple[str, str]
) -> set[ExpenseKey]:
    """이 원본 쌍에서 사람이 별개 지출로 확정한 묶음. 그 쌍의 재게시 근거가 되지 못한다."""
    return {
        expense
        for expense, item in decided.items()
        if _separates(item) and set(pair) <= set(item.scope.sources)
    }


def _candidate(table: Table, mapping: HeaderMap, row: int) -> _Candidate:
    columns = mapping.columns
    if "spent_on" in columns:
        spent_on = parse_date(table.cell(row, columns["spent_on"]), mapping.year_hint)
    else:
        spent_on = _month_day(
            table.cell(row, columns["month"]), table.cell(row, columns["day"]), mapping.year_hint
        )
    if spent_on is None:
        raise ValidationFailed(f"{table.name}:R{row} spent_on")
    amount = _amount(table.cell(row, columns["amount_krw"]))
    if amount is None:
        raise ValidationFailed(f"{table.name}:R{row} amount_krw")
    merchant = text(table.cell(row, columns["merchant"]))
    if not merchant:
        raise ValidationFailed(f"{table.name}:R{row} merchant")
    return _Candidate(row, spent_on, merchant, amount * mapping.amount_multiplier)


@dataclass
class _Section:
    candidates: list[_Candidate] = field(default_factory=list)
    totals: list[tuple[int, Decimal | None]] = field(default_factory=list)
    # 범위를 확정할 수 없는 누계·기간 합계가 있었다.
    unclear: bool = False


RowKind = Literal["blank", "header", "subtotal", "total", "unclear_total", "note", "candidate"]


def _kind(table: Table, mapping: HeaderMap, headers: set[tuple[str, ...]], row: int) -> RowKind:
    """지출 1건이 아닌 행을 구별한다. 식당 여부로 레코드를 버리는 일은 여기서 하지 않는다."""
    cells = table.rows[row - 1]
    joined = "".join(_compact(value) for value in cells)
    if not re.search(r"[0-9A-Za-z가-힣]", joined) or TERMINATOR.fullmatch(joined):
        return "blank"
    if _signature(cells) in headers:
        return "header"
    labels = {_compact(value) for value in cells}
    if any(SUBTOTAL.fullmatch(label) for label in labels):
        return "subtotal"
    if any(UNCLEAR_TOTAL.fullmatch(label) for label in labels):
        return "unclear_total"
    columns = mapping.columns
    date_columns = [columns[role] for role in ("spent_on", "month", "day") if role in columns]
    identity = [*date_columns, columns["merchant"]]
    unlabeled_total = _count(cells) is not None and all(
        text(table.cell(row, column)) == "" for column in identity
    )
    if unlabeled_total or any(TOTAL.fullmatch(label) for label in labels):
        return "total"
    if all(text(table.cell(row, column)) == "" for column in (*identity, columns["amount_krw"])):
        # 구역 제목·안내문처럼 지출 항목이 비어 있는 행. 위치만 세고 분모에서 뺀다.
        return "note"
    return "candidate"


def _check_totals(table: Table, sections: list[_Section], multiplier: Decimal) -> TotalCheck:
    """합계 행은 제 구역의 합이나 표 전체의 합과 정확히 같아야 한다. 소계는 더하지 않는다.

    누계·기간 합계와 금액을 읽을 수 없는 합계는 대조하지 않고 대조 불가로 남긴다.
    """
    whole = sum((item.amount for section in sections for item in section.candidates), Decimal(0))
    found = [(section, total) for section in sections for total in section.totals]
    unclear = any(section.unclear for section in sections)
    if not found:
        return "ambiguous" if unclear else "absent"
    readable = not unclear
    for section, (row, amount) in found:
        if amount is None:
            readable = False
            continue
        own = sum((item.amount for item in section.candidates), Decimal(0))
        if amount * multiplier not in (own, whole):
            raise ValidationFailed(f"{table.name}:R{row} total amount mismatch")
    return "matched" if readable else "ambiguous"


def _record(table: Table, mapping: HeaderMap, source: SourceRef, candidate: _Candidate) -> Record:
    columns = mapping.columns
    department = (
        text(table.cell(candidate.row, columns["department"])) if "department" in columns else ""
    )
    purpose = text(table.cell(candidate.row, columns["purpose"])) if "purpose" in columns else ""
    return Record(
        record_id=f"{source.source_hash[:16]}-{table.name}-R{candidate.row}",
        spent_on=candidate.spent_on,
        organization=source.organization,
        department=department or source.department or "",
        # 받는 사람이 개인인 경조사 지출은 이름 대신 가린 표시를 남긴다(SECURITY.md).
        merchant=scrub_merchant(candidate.merchant, purpose),
        purpose=scrub(purpose),
        amount_krw=candidate.amount,
        source_hash=source.source_hash,
        source_location=f"{table.name}:R{candidate.row}",
    )


def parse_date(value: Cell, year_hint: int | None = None) -> date | None:
    """날짜 셀·일련번호·흔한 한국식 표기를 읽는다. 연도가 없으면 연도 근거가 있을 때만 읽는다."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, float):
        if value.is_integer() and SERIAL_RANGE[0] <= value <= SERIAL_RANGE[1]:
            return (EXCEL_EPOCH + timedelta(days=int(value))).date()
        if value.is_integer() and 20000101 <= value <= 20991231:
            return _date(int(value) // 10000, int(value) // 100 % 100, int(value) % 100)
        return None
    # 엑셀에서 문자로 적으려고 붙인 따옴표(`'25. 10. 17.`)는 값이 아니다.
    raw = text(value).lstrip("'‘’`")
    full = re.match(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})(?!\d)", raw)
    if full:
        return _date(*(int(part) for part in full.groups()))
    compact = re.match(r"(20\d{2})(\d{2})(\d{2})(?!\d)", raw)
    if compact:
        return _date(*(int(part) for part in compact.groups()))
    short = re.match(r"(\d{2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})(?!\d)", raw)
    if short:
        year, month, day = (int(part) for part in short.groups())
        return _date(2000 + year, month, day)
    if year_hint is not None:
        partial = re.match(r"(\d{1,2})\s*[-./월]\s*(\d{1,2})(?!\d)", raw)
        if partial:
            return _date(year_hint, *(int(part) for part in partial.groups()))
    return None


def _month_day(month: Cell, day: Cell, year_hint: int | None) -> date | None:
    parts = [re.fullmatch(r"(\d{1,2})\s*[월일]?", text(value)) for value in (month, day)]
    if year_hint is None or not all(parts):
        return None
    return _date(year_hint, *(int(part.group(1)) for part in parts if part))


def _date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _amount(value: Cell) -> Decimal | None:
    """유한한 숫자만 금액이다. 회계 표기의 △는 음수로 읽는다."""
    if isinstance(value, datetime):
        return None
    if isinstance(value, float):
        return Decimal(int(value)) if value.is_integer() else Decimal(repr(value))
    raw = re.sub(r"[\s,원]", "", text(value)).replace("△", "-").replace("▲", "-")
    if not re.fullmatch(r"-?\d+(\.\d+)?", raw):
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _count(cells: tuple[Cell, ...]) -> int | None:
    for value in cells:
        found = re.fullmatch(r"(\d+)\s*건", text(value))
        if found:
            return int(found.group(1))
    return None


def _compact(value: Cell) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text(value)))


def _signature(cells: tuple[Cell, ...]) -> tuple[str, ...]:
    return tuple(_compact(value) for value in cells)


def header_signature(table: Table, header_rows: tuple[int, ...]) -> tuple[tuple[str, ...], ...]:
    """헤더 캐시의 서명. 정규화한 헤더 행 글자와 열 수(행 길이)로 이룬다."""
    return tuple(_signature(table.rows[row - 1]) for row in header_rows)
