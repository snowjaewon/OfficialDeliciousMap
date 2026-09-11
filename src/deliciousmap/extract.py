"""표 하나에서 헤더 매핑대로 레코드를 뽑고 폴백 정책의 코드 검증을 적용한다.

지출 후보 전부가 날짜·금액·상호를 갖춰야 표가 통과한다. 값을 추측해 채우지 않는다.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from deliciousmap import period
from deliciousmap.contracts import (
    HeaderMap,
    ParseOutput,
    Record,
    SourceRef,
    SourceReport,
    UnresolvedSource,
)
from deliciousmap.grid import Cell, Table, UnreadableOriginal, UnsupportedFormat, read_tables, text
from deliciousmap.privacy import scrub, scrub_merchant

# 공백을 지운 셀 글자에 적용한다. `2월 소계`·`합 계`처럼 앞말이 붙거나 띄어 쓴 표기도 있다.
TOTAL = re.compile(r"(\d{1,2}월|\d분기|\d{4}년)?(합계|총계|누계|총합계|계)")
SUBTOTAL = re.compile(r".{0,6}소계")
# 표 끝을 알리는 행. 원본에서는 글자마다 칸을 나눠 적기도 한다(`이 | 하 | 빈 | 칸`).
TERMINATOR = re.compile(r"(이하)?(빈칸|여백|없음)\.?")
# 엑셀 1900 체계의 날짜 일련번호가 2000~2099년에 해당하는 범위.
SERIAL_RANGE = (36526, 73051)
EXCEL_EPOCH = datetime(1899, 12, 30)

TotalCheck = Literal["matched", "absent", "ambiguous"]


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
    excluded_rows: int
    total_check: TotalCheck


@dataclass(frozen=True)
class _Candidate:
    row: int
    spent_on: date
    merchant: str
    amount: Decimal


def extract(table: Table, mapping: HeaderMap, source: SourceRef) -> Extraction:
    if mapping.layout == "none":
        return Extraction((), 0, 0, 0, "absent")
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
        if _kind(table, mapping, headers, row) == "total":
            sections[0].totals.append((row, _amount(table.cell(row, columns["amount_krw"]))))
    excluded = 0
    for row in range(mapping.data_start_row, len(table.rows) + 1):
        kind = _kind(table, mapping, headers, row)
        if kind == "candidate":
            sections[-1].candidates.append(_candidate(table, mapping, row))
            continue
        excluded += 1
        if kind == "header":
            sections.append(_Section())
        elif kind == "total":
            sections[-1].totals.append((row, _amount(table.cell(row, columns["amount_krw"]))))
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
        excluded_rows=excluded,
        total_check=check,
    )


def parse_sources(
    sources: tuple[SourceRef, ...],
    mappings: tuple[HeaderMap, ...],
    unresolved: tuple[UnresolvedSource, ...],
    raw_root: Path,
) -> ParseOutput:
    """원본마다 모든 표가 통과해야 레코드를 낸다. 실패한 원본의 일부만 확정하지 않는다."""
    by_source: dict[str, list[HeaderMap]] = {}
    for mapping in mappings:
        by_source.setdefault(mapping.source_hash, []).append(mapping)
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
            )
            continue
        try:
            tables = {table.name: table for table in read_tables(raw_root / source.path)}
            results = [
                extract(tables[mapping.table], mapping, source)
                for mapping in by_source[source.source_hash]
            ]
        except (UnsupportedFormat, UnreadableOriginal, KeyError):
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
        excluded = sum(result.excluded_rows for result in results)
        if candidates == 0:
            # 집행 없음을 확인할 근거가 없으므로 0건 통과로 두지 않는다.
            reports[source.source_hash] = SourceReport(
                source_hash=source.source_hash,
                status="unresolved",
                reason="no_candidates",
                candidates=0,
                excluded_rows=excluded,
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
            excluded_rows=excluded,
            total_check="matched"
            if checks == {"matched"}
            else "ambiguous"
            if "ambiguous" in checks
            else "absent",
        )
    return ParseOutput(
        records=tuple(records),
        empty_reason=None if records else "no records in the reporting period",
        sources=tuple(reports.values()),
    )


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


RowKind = Literal["blank", "header", "subtotal", "total", "note", "candidate"]


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
    """합계 행은 제 구역의 합이나 표 전체의 합과 정확히 같아야 한다. 소계는 더하지 않는다."""
    whole = sum((item.amount for section in sections for item in section.candidates), Decimal(0))
    found = [(section, total) for section in sections for total in section.totals]
    if not found:
        return "absent"
    readable = True
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
