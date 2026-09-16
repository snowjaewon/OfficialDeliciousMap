"""UTF-8 contract serialization; writes replace a complete validated file."""

import csv
import errno
import hashlib
import io
import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from deliciousmap import identity, merchants, period, restoration
from deliciousmap.contracts import (
    BuildOutput,
    CacheEntry,
    CandidateFile,
    CandidateLookup,
    ClassifyOutput,
    ClosureOutput,
    ComparisonRequest,
    Contract,
    EvidenceScope,
    ExcludedSources,
    Expense,
    FetchOutput,
    GeocodeOutput,
    GeocodeResult,
    HeaderMapOutput,
    IdentityConfirmation,
    LedgerEntry,
    ManualCorrection,
    MerchantReview,
    NameRestoration,
    ParseOutput,
    ProviderCandidates,
    ProviderCategories,
    Record,
    RecordOrigin,
    RepeatConfirmation,
    RestorationProposal,
    ScopedReview,
    SourceRef,
    SourceReview,
)
from deliciousmap.paths import Paths
from deliciousmap.registry import Target

# 정제 산출물의 파일당 상한(ADR-0001). 이력도 이 상한 안에서 조각으로 나눈다.
SIZE_LIMIT = 20_000_000
TOO_LARGE = "artifact exceeds 20MB; partition before writing"

RECORD_FIELDS = (
    "record_id",
    "spent_on",
    "organization",
    "department",
    "merchant",
    "purpose",
    "amount_krw",
    "source_hash",
    "source_location",
    "repeats",
    # 사람이 업소별로 확인한 지출과 그 지출이 밝힌 금액. 확인이 없는 레코드는 두 칸이 빈다.
    "expense_id",
    "expense_amount_krw",
)

OUTPUT_MODELS: dict[str, type[Contract]] = {
    "fetch": FetchOutput,
    "headermap": HeaderMapOutput,
    "parse": ParseOutput,
    "classify": ClassifyOutput,
    "geocode": GeocodeOutput,
    "closure": ClosureOutput,
    "build": BuildOutput,
}

# fetch는 받지 않은 게시글 수를 담은 v4, headermap은 미해결 원본의 매핑을 담은 v2,
# parse는 업소별로 가른 레코드를 담은 v5, geocode는 확인한 업소를 담은 v5, closure는 조회 요청
# 기록을 포함하는 v4, build는 금액 미상 방문과 이름 없는 동행 업소의 수를 함께 담은 v9다 —
# 두 변경이 각각 v8을 쓰고 합쳐졌으므로 어느 쪽 v8도 이 산출물을 설명하지 못한다.
SCHEMA_VERSIONS = {"fetch": 4, "headermap": 2, "parse": 5, "geocode": 5, "closure": 4, "build": 9}

# 제공자 조회 캐시. 확정 업소 판정 이력(geocode-history-v2.jsonl)과 분리해 둔다.
LOOKUP_CACHE = "geocode-lookup-v1.jsonl"
# 모델 제안 이력. 사람 확인 입력·업소 판정과 분리해 두며 판정의 의존성에 넣지 않는다.
PROPOSAL_CACHE = "restore-proposal-v1.jsonl"
# 확정 업소의 업종 조회 캐시. 표시용이라 판정의 의존성에 넣지 않고 build만 읽는다(#96).
CATEGORY_CACHE = "category-lookup-v1.jsonl"

DEPENDENCIES = {
    "fetch": (),
    "headermap": ("fetch.json",),
    "parse": (),
    "classify": ("records.csv", "parse.json"),
    "geocode": ("records.csv", "parse.json", "classify.json"),
    "closure": ("records.csv", "parse.json", "classify.json", "geocode.json"),
    "build": ("records.csv", "parse.json", "classify.json", "geocode.json", "closure.json"),
}


# 상한을 넘으면 조각으로 나눌 수 있는 산출물과 그 목록 칸(ADR-0001). 여기 없는 단계는
# 넘는 순간 거부한다. 나눌 칸이 없으면 무엇을 잘라야 할지 정해져 있지 않기 때문이다.
SPLIT_PAYLOAD_FIELD = {"geocode": "results"}


def schema_version(stage: str) -> int:
    return SCHEMA_VERSIONS.get(stage, 1)


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def read_reviews[T: Contract](path: Path, model: type[T]) -> tuple[T, ...]:
    """사람 검토 입력은 한 줄에 계약 하나인 JSONL이다. 없는 파일은 검토 없음이다."""
    if not path.exists():
        return ()
    return tuple(
        model.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines()
    )


def require_scoped_reviews(
    entries: Sequence[
        NameRestoration | IdentityConfirmation | MerchantReview | RepeatConfirmation | ScopedReview
    ],
    city: str,
) -> None:
    if any(item.scope.city != city for item in entries):
        raise ValueError("review city mismatch")
    scopes = [item.scope for item in entries]
    if len(scopes) != len(set(scopes)):
        raise ValueError("duplicate review scope")


class RegenerationRequired(ValueError):
    """An older contract must be regenerated; its bytes remain available."""


def require_exact_keys(actual: list[str], expected: set[str]) -> None:
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("artifact keys must cover exactly the input targets")


def write_text(path: Path, content: str) -> None:
    write_bytes(path, content.encode("utf-8"))


def write_bytes(path: Path, content: bytes) -> None:
    if len(content) > SIZE_LIMIT:
        raise ValueError(TOO_LARGE)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _within_limit(content: str) -> bool:
    return len(content.encode("utf-8")) <= SIZE_LIMIT


def require_size(content: str) -> None:
    if not _within_limit(content):
        raise ValueError(TOO_LARGE)


def dump_repeats(origins: tuple[RecordOrigin, ...]) -> str:
    """`repeats` 칸. 원본 해시와 행 위치를 `:`로 잇고 공백으로 나열한다. 위치에는 공백이 없다."""
    return " ".join(f"{item.source_hash}:{item.location}" for item in origins)


def load_repeats(raw: str) -> tuple[RecordOrigin, ...]:
    """`repeats` 칸을 되읽는다. 해시와 위치를 가르지 못하는 값은 계약 검증이 거부한다."""
    origins = []
    for token in raw.split():
        digest, _, location = token.partition(":")
        origins.append(RecordOrigin(source_hash=digest, location=location))
    return tuple(origins)


def dump_expense(expense: Expense | None) -> dict[str, str]:
    """`expense_id`·`expense_amount_krw` 두 칸. 확인이 없는 레코드는 둘 다 빈 값이다."""
    if expense is None:
        return {"expense_id": "", "expense_amount_krw": ""}
    return {"expense_id": expense.expense_id, "expense_amount_krw": str(expense.amount_krw)}


def load_expense(row: Mapping[str, str]) -> dict[str, str] | None:
    """두 칸을 되읽는다. 지출을 가리키지 않는 줄은 확인이 없는 레코드다."""
    if not row["expense_id"]:
        return None
    return {"expense_id": row["expense_id"], "amount_krw": row["expense_amount_krw"]}


def write_records(path: Path, records: tuple[Record, ...]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=RECORD_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        row = Record.model_validate(record).model_dump(mode="json")
        row.pop("expense")
        writer.writerow(
            {**row, "repeats": dump_repeats(record.repeats), **dump_expense(record.expense)}
        )
    write_text(path, stream.getvalue())


def read_records(path: Path) -> tuple[Record, ...]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(RECORD_FIELDS):
            raise ValueError("invalid record CSV columns")
        # 집행일 칸이 받는 두 모양(`YYYY-MM-DD`와 일을 비운 원본 표기)은 계약이 가른다.
        return tuple(_record_from(row) for row in reader)


def _record_from(row: Mapping[str, str]) -> Record:
    """장부 CSV 한 줄. 빈 금액 칸은 금액이 지출에 남아 있다는 뜻이다(ADR-0007)."""
    fields = {name: row[name] for name in RECORD_FIELDS if not name.startswith("expense")}
    return Record.model_validate(
        {
            **fields,
            "amount_krw": fields["amount_krw"] or None,
            "repeats": load_repeats(row["repeats"] or ""),
            "expense": load_expense(row),
        }
    )


def _numbered_part(path: Path, number: int) -> Path:
    """첫 조각은 원래 이름 그대로다. 이어지는 조각만 세 자리 번호를 붙인다."""
    if number == 1:
        return path
    if number > 999:
        raise ValueError("parts exhausted; split the scope of this file")
    return path.with_name(f"{path.stem}.{number:03d}{path.suffix}")


def _continuation_parts(path: Path) -> list[Path]:
    """첫 조각에 이어지는 번호 붙은 파일. 이름 규칙은 여기 한 곳에만 적는다."""
    return sorted(path.parent.glob(f"{path.stem}.[0-9][0-9][0-9]{path.suffix}"))


def numbered_parts(path: Path) -> tuple[Path, ...]:
    """이력이나 산출물을 이루는 조각. 번호가 비면 잃어버린 조각을 조용히 넘기지 않고 알린다."""
    found = _continuation_parts(path)
    if not path.exists():
        if found:
            raise ValueError("numbered parts without the first file")
        return ()
    parts = (path, *found)
    if list(parts) != [_numbered_part(path, number) for number in range(1, len(parts) + 1)]:
        raise ValueError("parts must be numbered without gaps")
    return parts


def read_cache(path: Path) -> tuple[CacheEntry, ...]:
    entries: tuple[CacheEntry, ...] = ()
    seen: set[tuple[str, int]] = set()
    for part in numbered_parts(path):
        found = _read_cache_part(part)
        identities = {_cache_order(entry) for entry in found}
        if identities & seen:
            raise ValueError("cache parts must not repeat a key/revision pair")
        seen |= identities
        entries += found
    return entries


def _read_cache_part(part: Path) -> tuple[CacheEntry, ...]:
    entries = tuple(
        CacheEntry.model_validate_json(line)
        for line in part.read_text(encoding="utf-8").splitlines()
    )
    identities = [_cache_order(entry) for entry in entries]
    if identities != sorted(set(identities)):
        raise ValueError("cache must have unique, sorted key/revision pairs")
    return entries


def latest_valid(entries: Iterable[CacheEntry]) -> dict[str, CacheEntry]:
    """키마다 `valid=true`인 가장 큰 revision. 조각 사이의 줄 순서에 기대지 않는다."""
    found: dict[str, CacheEntry] = {}
    for entry in entries:
        kept = found.get(entry.key)
        if entry.valid and (kept is None or entry.revision > kept.revision):
            found[entry.key] = entry
    return found


def highest_revision(entries: Iterable[CacheEntry]) -> dict[str, int]:
    """키마다 가장 큰 revision. 다음 revision을 정할 때 쓰며 유효 여부는 보지 않는다."""
    found: dict[str, int] = {}
    for entry in entries:
        found[entry.key] = max(found.get(entry.key, 0), entry.revision)
    return found


def append_cache(path: Path, entry: CacheEntry) -> None:
    append_cache_entries(path, (entry,))


def append_cache_entries(path: Path, additions: tuple[CacheEntry, ...]) -> None:
    """마지막 조각에만 이어 쓴다. 이번 배치가 들어가지 않으면 그 조각을 닫고 새 조각을 연다.

    앞 조각은 절대 다시 쓰지 않는다. 마지막 조각은 정렬을 지키려고 통째로 다시 쓴다.
    그래서 조각이 상한에 딱 차지 않을 수 있는데, 커밋된 앞 조각을 다시 쓰지 않는 대가다.
    """
    settled = {_cache_order(entry): entry for entry in read_cache(path)}
    fresh: dict[tuple[str, int], CacheEntry] = {}
    for entry in additions:
        entry = CacheEntry.model_validate(entry)
        pair = _cache_order(entry)
        kept = settled.get(pair, fresh.get(pair))
        if kept is not None:
            if kept != entry:
                raise ValueError("cannot overwrite cache history")
            continue
        fresh[pair] = entry
    if not fresh:
        return
    parts = numbered_parts(path)
    added = sorted(fresh.values(), key=_cache_order)
    if parts:
        carried = sorted((*_read_cache_part(parts[-1]), *added), key=_cache_order)
        merged = _jsonl(carried)
        if _within_limit(merged):
            write_text(parts[-1], merged)
            return
    # 쓰기 전에 모든 조각을 만들어 크기를 확인한다. 일부만 써 두고 실패하지 않는다.
    opened = [
        (_numbered_part(path, len(parts) + offset + 1), _jsonl(chunk))
        for offset, chunk in enumerate(_cache_chunks(added))
    ]
    for _, content in opened:
        require_size(content)
    for part, content in opened:
        write_text(part, content)


def _cache_order(entry: CacheEntry) -> tuple[str, int]:
    return entry.key, entry.revision


def _cache_chunks(entries: Sequence[CacheEntry]) -> Iterator[list[CacheEntry]]:
    """한 조각에 담을 만큼씩 나눈다. 혼자서도 상한을 넘는 항목은 쓰는 쪽이 거부한다."""
    chunk: list[CacheEntry] = []
    size = 0
    for entry in entries:
        length = len(_jsonl((entry,)).encode("utf-8"))
        if chunk and size + length > SIZE_LIMIT:
            yield chunk
            chunk, size = [], 0
        chunk.append(entry)
        size += length
    if chunk:
        yield chunk


def _jsonl(entries: Iterable[Contract]) -> str:
    return "".join(
        json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
        for item in entries
    )


# `json.dumps`가 목록 항목 사이에 넣는 기본 구분자. 조각 크기를 셀 때 이 자리도 센다.
ITEM_SEPARATOR = ", "


def artifact_text(envelope: Mapping[str, Any]) -> str:
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n"


def _artifact_chunks(envelope: Mapping[str, Any], field: str) -> Iterator[str]:
    """한 조각에 담을 만큼씩 나눈다. 항목 하나가 혼자 넘으면 쓰는 쪽이 거부한다."""
    payload = dict(envelope["payload"])
    items = list(payload[field])
    # 목록을 비운 봉투가 조각마다 되풀이되는 자리다. 남는 만큼만 항목에 쓴다.
    budget = SIZE_LIMIT - len(
        artifact_text({**envelope, "payload": {**payload, field: []}}).encode("utf-8")
    )
    chunk: list[object] = []
    size = 0
    for item in items:
        # 항목 하나가 차지하는 자리. `json.dumps`의 기본 구분자가 쉼표와 공백 두 자이므로
        # 그만큼을 함께 센다. 한 자로 세면 작은 항목이 많을 때 조각이 그 수만큼 넘친다.
        length = len(json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")) + len(
            ITEM_SEPARATOR
        )
        if chunk and size + length > budget:
            yield artifact_text({**envelope, "payload": {**payload, field: chunk}})
            chunk, size = [], 0
        chunk.append(item)
        size += length
    yield artifact_text({**envelope, "payload": {**payload, field: chunk}})


def artifact_contents(envelope: Mapping[str, Any], field: str | None) -> tuple[str, ...]:
    """쓸 조각을 모두 만들고 크기를 확인한다. 아무것도 쓰기 전에 거부할 수 있게 나눠 둔다.

    쓰는 일과 가른 이유: 이력은 산출물보다 먼저 쌓이므로, 쓸 수 없는 산출물이면
    이력에 손대기 전에 알아야 한다. 결과 하나가 혼자 상한을 넘으면 나눌 수 없으므로 거부한다.
    """
    content = artifact_text(envelope)
    contents = (
        (content,)
        if _within_limit(content) or field is None
        else tuple(_artifact_chunks(envelope, field))
    )
    for text in contents:
        require_size(text)
    return contents


def write_artifact(path: Path, contents: Sequence[str]) -> None:
    """만들어 둔 조각을 번호 순으로 쓴다."""
    for number, text in enumerate(contents, start=1):
        write_text(_numbered_part(path, number), text)
    # 지난 실행이 더 많은 조각을 남겼으면 지운다. 남겨 두면 이어 읽기가 옛 항목을 섞는다.
    for stale in _continuation_parts(path)[len(contents) - 1 :]:
        stale.unlink()


def _missing_artifact(path: Path) -> FileNotFoundError:
    # 실패 진단이 종류와 경로를 알릴 수 있도록 errno와 파일 이름을 채운다.
    return FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(path))


def artifact_digest(path: Path) -> str:
    """조각으로 나뉜 산출물도 통째로 해시한다. 뒤 조각만 바뀐 낡음을 놓치지 않는다."""
    parts = numbered_parts(path)
    if not parts:
        # 있어야 하는 선행 산출물이다. 없는 것을 빈 해시로 덮으면 낡음 검사가 그대로 통과한다.
        raise _missing_artifact(path)
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.read_bytes())
    return digest.hexdigest()


def read_artifact(path: Path, field: str | None) -> dict[str, Any]:
    """조각을 번호 순으로 이어 읽는다. 봉투 머리가 다른 조각은 섞인 것이므로 거부한다."""
    parts = numbered_parts(path)
    if not parts:
        raise _missing_artifact(path)
    envelopes: list[dict[str, Any]] = [
        json.loads(part.read_text(encoding="utf-8")) for part in parts
    ]
    first = envelopes[0]
    if len(envelopes) == 1:
        return first
    if field is None:
        raise ValueError("this artifact must not be split into parts")
    items = []
    for envelope in envelopes:
        if _artifact_header(envelope, field) != _artifact_header(first, field):
            raise ValueError("artifact parts must share one envelope")
        items.extend(envelope["payload"][field])
    return {**first, "payload": {**first["payload"], field: items}}


def _artifact_header(envelope: dict[str, Any], field: str) -> dict[str, Any]:
    """조각마다 같아야 하는 부분. 나뉘는 목록 칸만 뺀다."""
    return {
        **{key: value for key, value in envelope.items() if key != "payload"},
        "payload": {key: value for key, value in envelope["payload"].items() if key != field},
    }


def read_ledger(path: Path) -> tuple[LedgerEntry, ...]:
    """공통 예산 장부. 실행·재시작을 가로질러 이어 쓰는 추가형 이력이다."""
    if not path.exists():
        return ()
    entries = tuple(
        LedgerEntry.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    )
    identities = [(entry.entry_id, entry.kind) for entry in entries]
    if len(identities) != len(set(identities)):
        raise ValueError("budget ledger entries must be unique per request and kind")
    return entries


def append_ledger(path: Path, entry: LedgerEntry) -> None:
    """집행 순서를 그대로 남긴다. 같은 요청의 같은 항목을 다시 쓰지 않는다."""
    entry = LedgerEntry.model_validate(entry)
    entries = read_ledger(path)
    if any((item.entry_id, item.kind) == (entry.entry_id, entry.kind) for item in entries):
        raise ValueError("cannot overwrite budget history")
    write_text(path, _jsonl((*entries, entry)))


def attempt(previous: CacheEntry | None) -> int:
    """같은 요청을 다시 수행한 횟수. 재시도마다 다른 이력·예약 항목이 된다."""
    return 1 if previous is None else previous.revision + 1


def select_cache(path: Path, key: str) -> CacheEntry | None:
    """그 키의 유효한 최신 판정. 줄 순서가 아니라 revision으로 고른다."""
    return latest_valid(read_cache(path)).get(key)


class LookupCache:
    """조회 캐시의 유효한 최신 항목을 한 실행이 시작할 때 한 번만 읽어 든다.

    레코드마다 파일을 다시 파싱하면 읽기 비용이 레코드 수 곱하기 캐시 줄 수가 된다. 캐시가
    커질수록 적중뿐인 재실행이 더 느려진다. 이 사전은 그 읽기를 레코드 수 더하기 캐시 줄 수로
    낮춘다.

    쓰기도 같다. 새로 얻은 조회는 캐시 옆 대기 파일(`<이름>.pending.jsonl`)에 한 줄씩 덧붙이고,
    `with` 블록을 닫을 때 한 번만 정렬해 캐시에 합친다. 조회마다 캐시를 통째로 다시 쓰면 쓰기가
    조회 수의 제곱으로 늘고 파일 교체가 다른 프로세스의 읽기와 부딪힌다(#181). 여는 일은 쓰지
    않는다. 끊긴 실행이 남긴 대기 파일은 읽어 들이기만 하고, 다음에 블록을 닫는 실행이 함께
    합친다. 쓰다 끊긴 끝 줄은 그 조회를 다시 하면 되므로 버린다.

    실행 중 새로 얻은 조회는 대기 파일과 사전 양쪽에 남기고, 합칠 때는 이번 실행이 얻은 조회를
    파일이 아니라 메모리에서 다시 넣는다. 다른 실행이 대기 파일을 먼저 합쳐 지워도 잃지 않는다.
    대신 실행이 도는 동안 다른 세션이 같은 캐시에 쓴 항목은 이 사전에 들어오지 않는다. 그 경우
    합치기가 같은 revision을 만나 `cannot overwrite cache history`로 멈추고 대기 파일을 남긴다.
    조용히 덮지는 않는다.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.pending = path.with_name(f"{path.stem}.pending{path.suffix}")
        self._added: list[CacheEntry] = []
        self._latest = latest_valid((*read_cache(path), *self._read_pending()))

    def __enter__(self) -> "LookupCache":
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, _: object
    ) -> None:
        if error is None:
            self.merge_pending()
            return
        # 실행을 끊은 원인을 합치기 실패로 덮지 않는다. 대기 파일은 다음 실행이 합친다.
        try:
            self.merge_pending()
        except Exception as failure:
            error.add_note(f"pending lookups not merged: {type(failure).__name__}")

    def merge_pending(self) -> None:
        """대기 파일과 이번 실행의 조회를 캐시에 합치고 대기 파일을 지운다.

        합친 뒤 지우기 전에 끊겨도 다시 합치면 같은 결과다. 이미 담긴 항목은 건너뛴다.
        """
        entries = (*self._read_pending(), *self._added)
        if entries:
            append_cache_entries(self.path, entries)
        self.pending.unlink(missing_ok=True)
        self._added.clear()

    def _read_pending(self) -> tuple[CacheEntry, ...]:
        if not self.pending.exists():
            return ()
        # 바이트로 먼저 가른다. 쓰다 끊긴 줄은 한글 한 글자 중간에서 끝날 수도 있다.
        # 마지막 줄바꿈 뒤는 비었거나, 쓰다 끊긴 줄이다.
        lines = self.pending.read_bytes().split(b"\n")[:-1]
        entries = []
        for number, line in enumerate(lines, start=1):
            try:
                entries.append(CacheEntry.model_validate_json(line))
            except ValueError:
                # 원문에는 상호가 들어 있으므로 위치만 알린다.
                raise ValueError(f"damaged cache line {self.pending.name}:{number}") from None
        return tuple(entries)

    def cached_candidates(self, key: str) -> CacheEntry | None:
        """그 키의 유효한 최신 항목. 적중 자체는 업소 확정이 아니다."""
        return self._latest.get(key)

    def remember_candidates(
        self, key: str, found: ProviderCandidates | ProviderCategories, evidence: str
    ) -> int:
        """같은 결과는 다시 쌓지 않고, 달라지면 새 revision으로 이력에 남긴다.

        앞선 판정은 부르는 쪽이 넘기지 않고 사전에서 직접 본다. 넘겨받으면 사전이 들고 있는
        것과 어긋난 revision으로 쌓을 여지가 생긴다.
        """
        value = type(found).model_validate(found).model_dump(mode="json")
        previous = self._latest.get(key)
        if previous is not None and previous.value == value:
            return previous.revision
        entry = CacheEntry(
            key=key,
            revision=attempt(previous),
            valid=True,
            evidence=evidence,
            value=value,
        )
        with self.pending.open("ab") as stream:
            stream.write(_jsonl((entry,)).encode("utf-8"))
        self._added.append(entry)
        self._latest[key] = entry
        return entry.revision


class ArtifactStore:
    def __init__(self, paths: Paths, target: Target) -> None:
        self.paths = paths
        self.target = target
        self.directory = paths.city_dir(target)

    def city(self) -> "ArtifactStore":
        """같은 도시 전체를 대상으로 하는 저장소. 기관 실행이 도시 판정을 인용할 때 읽는다."""
        return ArtifactStore(self.paths, Target(self.target.city))

    def save(self, stage: str, output: Contract, *, retry_failed: bool = False) -> None:
        output = OUTPUT_MODELS[stage].model_validate(output)
        self._validate(output)
        payload = output.model_dump(mode="json")
        if isinstance(output, ParseOutput):
            payload.pop("records")
        envelope = {
            "schema_version": schema_version(stage),
            "city": self.target.city.slug,
            "org": self.target.org,
            "dependencies": self._dependencies(stage),
            "payload": payload,
        }
        # 이력은 산출물보다 먼저 쌓인다. 쓸 수 없는 산출물이면 여기서 먼저 거부한다.
        contents = artifact_contents(envelope, SPLIT_PAYLOAD_FIELD.get(stage))
        if isinstance(output, ParseOutput):
            write_records(self.directory / "records.csv", output.records)
        if isinstance(output, GeocodeOutput):
            cache_path = self.directory / "geocode-history-v2.jsonl"
            latest = latest_valid(read_cache(cache_path))
            additions = []
            for result in output.results:
                key = result.lookup_key
                previous = latest.get(key)
                value = result.model_dump(mode="json")
                if (
                    previous is None
                    or previous.value != value
                    or (retry_failed and result.status == "failed")
                ):
                    additions.append(
                        CacheEntry(
                            key=key,
                            revision=1 if previous is None else previous.revision + 1,
                            valid=True,
                            evidence=result.evidence,
                            value=value,
                        ),
                    )
            if additions:
                append_cache_entries(cache_path, tuple(additions))
        path = self.directory / f"{stage}.json"
        if path.exists():
            old = path.read_bytes().decode("utf-8")
            if json.loads(old)["schema_version"] != envelope["schema_version"]:
                archive = (
                    self.directory
                    / "history"
                    / (
                        f"{stage}-v{json.loads(old)['schema_version']}-"
                        f"{hashlib.sha256(old.encode('utf-8')).hexdigest()}.json"
                    )
                )
                write_text(archive, old)
        write_artifact(path, contents)

    def load[T: Contract](self, stage: str, model: type[T]) -> T:
        envelope = read_artifact(self.directory / f"{stage}.json", SPLIT_PAYLOAD_FIELD.get(stage))
        if envelope["schema_version"] != schema_version(stage):
            raise RegenerationRequired("rerun the producing stage for the current contract")
        if (envelope["city"], envelope["org"]) != (
            self.target.city.slug,
            self.target.org,
        ):
            raise ValueError("artifact version or target mismatch")
        if envelope["dependencies"] != self._dependencies(stage):
            raise ValueError("stale artifact; rerun its producing stage")
        payload = envelope["payload"]
        if model is ParseOutput:
            payload["records"] = read_records(self.directory / "records.csv")
        output = model.model_validate(payload)
        self._validate(output)
        return output

    def reporting_sources(self) -> tuple[SourceRef, ...]:
        """이번 제출이 다룰 원본. 수집 장부에서 대상 기간의 게시글 것만 고른다.

        고르는 이유와 규칙은 README의 CLI 절에 있다. 수집 장부는 줄이지 않으므로
        무엇을 받아 두었는지는 `fetch.json`에 그대로 남는다.
        """
        return tuple(
            item
            for item in self.load("fetch", FetchOutput).sources
            if period.targets(item.posted, item.title, item.spent_on)
        )

    def excluded_sources(self) -> ExcludedSources:
        """대상에서 뺀 원본의 사유별 수. 뺀 것을 0으로 감추지 않으려고 산출물에 싣는다."""
        counted = Counter(
            reason
            for item in self.load("fetch", FetchOutput).sources
            if (reason := period.exclusion(item.posted, item.title, item.spent_on)) is not None
        )
        return ExcludedSources(
            posted_out_of_range=counted["posted_out_of_range"],
            declared_out_of_range=counted["declared_out_of_range"],
            undeclared_in_year=counted["undeclared_in_year"],
        )

    def _dependencies(self, stage: str) -> dict[str, str]:
        result = {name: artifact_digest(self.directory / name) for name in DEPENDENCIES[stage]}
        if stage == "classify":
            result["manual"] = file_digest(self.paths.manual(self.target, "classify"))
            result["tail_policy"] = merchants.TAIL_VERSION
        if stage == "parse":
            result["merchants"] = file_digest(self.paths.manual(self.target, "merchants"))
        if stage == "geocode" and self.target.org is not None:
            # 기관 판정은 도시 판정의 인용이다. 도시 판정이 바뀌면 기관 산출물도 낡는다.
            result["city_geocode"] = artifact_digest(self.city().directory / "geocode.json")
        elif stage == "geocode":
            result["candidates"] = file_digest(self.directory / "geocode-input.json")
            result["lookups"] = file_digest(self.directory / LOOKUP_CACHE)
        if stage == "geocode":
            result["confirmations"] = file_digest(self.paths.manual(self.target, "geocode"))
            result["policy"] = identity.POLICY_VERSION
        if stage == "build":
            result["categories"] = file_digest(self.directory / CATEGORY_CACHE)
        if stage in {"parse", "geocode"}:
            result["merchant_policy"] = merchants.POLICY_VERSION
        if stage in {"classify", "geocode"}:
            result["restorations"] = file_digest(self.paths.manual(self.target, "restore"))
            result["restoration_policy"] = restoration.POLICY_VERSION
        return result

    def _validate(self, output: Contract) -> None:
        organizations = {org.slug for org in self.target.organizations}
        if isinstance(output, FetchOutput):
            if not output.sources and output.empty_reason is None:
                raise ValueError("unexplained empty fetch")
            if any(item.organization not in organizations for item in output.missing):
                raise ValueError("missing original organization mismatch")
            for source in output.sources:
                if source.organization not in organizations:
                    raise ValueError("source organization mismatch")
                source_path = (self.paths.raw_root / source.path).resolve()
                if source_path.is_relative_to(
                    self.paths.repository.resolve()
                ) or not source_path.is_relative_to(self.paths.raw_root.resolve()):
                    raise ValueError("source must be outside repository and within raw-root")
                boards = {
                    board.slug
                    for org in self.target.organizations
                    if org.slug == source.organization
                    for board in org.boards
                }
                if source.board not in boards:
                    raise ValueError("source board mismatch")
        elif isinstance(output, HeaderMapOutput):
            sources = self.reporting_sources()
            mapped = {item.source_hash for item in output.mappings}
            unresolved = [item.source_hash for item in output.unresolved]
            if (
                len(unresolved) != len(set(unresolved))
                or mapped & set(unresolved)
                or mapped | set(unresolved) != {source.source_hash for source in sources}
            ):
                raise ValueError("mapping must cover every original of the reporting period")
            identities = [(item.source_hash, item.table) for item in output.mappings]
            if len(identities) != len(set(identities)):
                raise ValueError("duplicate mapping for a table")
        elif isinstance(output, ParseOutput):
            if not output.records and output.empty_reason is None:
                raise ValueError("unexplained empty parse")
            require_exact_keys(
                [record.record_id for record in output.records],
                {record.record_id for record in output.records},
            )
            if any(record.organization not in organizations for record in output.records):
                raise ValueError("record organization mismatch")
            if output.sources:
                self._validate_reports(output)
            self._validate_source_reviews(output)
        elif isinstance(output, ClassifyOutput):
            records = self.load("parse", ParseOutput).records
            require_exact_keys(
                [item.record_id for item in output.decisions],
                {record.record_id for record in records},
            )
        elif isinstance(output, GeocodeOutput):
            records = self.load("parse", ParseOutput).records
            decisions = self.load("classify", ClassifyOutput).decisions
            included = {item.record_id for item in decisions if item.status == "restaurant"}
            require_exact_keys(
                [item.record_id for item in output.results],
                included,
            )
            by_id = {record.record_id: record for record in records}
            dependency_key = self.geocode_dependency_key()
            halls = self.target.city.halls
            for item in output.results:
                record = by_id[item.record_id]
                if item.merchant != record.merchant or item.lookup.scope != self.scope(record):
                    raise ValueError("geocode record provenance mismatch")
                if item.dependency_key != dependency_key:
                    raise ValueError("stale geocode result")
                if item.lookup_key != identity.lookup_key(
                    record,
                    item.lookup,
                    item.confirmation,
                    item.restoration,
                    item.dependency_key,
                    address_prefixes=self.target.city.address_prefixes,
                    hall=halls.get(record.organization),
                ):
                    raise ValueError("geocode dependency mismatch")
        elif isinstance(output, ClosureOutput):
            geocodes = self.load("geocode", GeocodeOutput).results
            require_exact_keys(
                [item.business_id for item in output.results],
                {item.business_id for item in geocodes if item.business_id is not None},
            )
        elif isinstance(output, BuildOutput):
            records = self.load("parse", ParseOutput).records
            closures = self.load("closure", ClosureOutput).results
            if output.record_count != len(records) or output.marker_count != len(closures):
                raise ValueError("build counts do not match its input")
            if not output.files or any(
                not path.resolve().is_relative_to(self.paths.output_root.resolve())
                or not path.is_file()
                for path in output.files
            ):
                raise ValueError("build must produce files within output-root")

    def _validate_reports(self, output: ParseOutput) -> None:
        """원본별 보고는 받은 원본을 한 번씩 모두 덮고, 레코드 수가 실제 레코드와 같아야 한다."""
        reported = [item.source_hash for item in output.sources]
        targets = {source.source_hash for source in self.reporting_sources()}
        if len(reported) != len(set(reported)) or set(reported) != targets:
            raise ValueError("parse report must cover every original of the reporting period once")
        counts: dict[str, int] = {}
        for record in output.records:
            counts[record.source_hash] = counts.get(record.source_hash, 0) + 1
        if any(item.records != counts.get(item.source_hash, 0) for item in output.sources):
            raise ValueError("parse report record counts do not match the records")

    def _validate_source_reviews(self, output: ParseOutput) -> None:
        """보류 기록은 이번 실행에서도 미해결인 원본을 가리키고 후보 수가 보고와 같아야 한다.

        코드가 읽게 된 원본에 낡은 기록이 남으면 장부와 어긋난다. 가리키는 원본이 이번 보고에
        아예 없는 것도 알린다 — 기관을 좁혔다면 그 기관의 기록만 읽으므로 잘못 적은 해시다.

        후보 수도 맞춘다. 사람이 센 수와 코드가 센 수가 다르면 원본 결함 확정으로 갈리는 순간
        화면의 분모가 조용히 바뀐다(#106). 코드가 후보를 세지 못한 원본(`candidates`가 None)은
        대조할 것이 없으므로 사람이 센 수만 남는다.
        """
        unresolved = {
            item.source_hash: item for item in output.sources if item.status == "unresolved"
        }
        for review in self.source_reviews():
            report = unresolved.get(review.source_hash)
            if report is None:
                raise ValueError("source review for an original that is no longer unresolved")
            if report.candidates is not None and report.candidates != review.candidates:
                raise ValueError("source review candidate count disagrees with the parse report")

    def source_reviews(self) -> tuple[SourceReview, ...]:
        """전수 대조로 남긴 미해결 원본의 기록. 값을 채워 통과시키지는 않는다."""
        entries = read_reviews(self.paths.manual(self.target, "sources"), SourceReview)
        if any(item.city != self.target.city.slug for item in entries):
            raise ValueError("source review city mismatch")
        scoped = tuple(
            item
            for item in entries
            if self.target.org is None or item.organization == self.target.org
        )
        if len({item.source_hash for item in scoped}) != len(scoped):
            raise ValueError("duplicate source review")
        return scoped

    def repeat_confirmations(self) -> tuple[RepeatConfirmation, ...]:
        """사람이 확정한 재게시 여부. 파일이 없으면 확정이 없는 것과 같다."""
        return self._declared("repeats", RepeatConfirmation)

    def manual(self) -> tuple[ManualCorrection, ...]:
        corrections = read_reviews(self.paths.manual(self.target, "classify"), ManualCorrection)
        if any(item.city != self.target.city.slug for item in corrections):
            raise ValueError("manual correction city mismatch")
        return tuple(
            item
            for item in corrections
            if self.target.org is None or item.organization in (None, self.target.org)
        )

    def restorations(self) -> tuple[NameRestoration, ...]:
        """확정 복원명의 직렬화는 여기에 둔다. 복원 로직은 파일을 보지 않는다."""
        return self._declared("restore", NameRestoration)

    def confirmations(self) -> tuple[IdentityConfirmation, ...]:
        """확정한 업소 확인의 직렬화. 적용 범위 판단은 파일을 보지 않는다."""
        return self._declared("geocode", IdentityConfirmation)

    def merchant_reviews(self) -> tuple[MerchantReview, ...]:
        """상호 가르기의 직렬화. 레코드를 가르는 규칙은 파일을 보지 않는다."""
        return self._declared("merchants", MerchantReview)

    def _declared[T: NameRestoration | IdentityConfirmation | MerchantReview | RepeatConfirmation](
        self, name: str, model: type[T]
    ) -> tuple[T, ...]:
        """범위를 선언한 검토 입력 중 이 실행의 기관에 해당하는 줄만 돌려준다."""
        entries = read_reviews(self.paths.manual(self.target, name), model)
        require_scoped_reviews(entries, self.target.city.slug)
        return tuple(
            item
            for item in entries
            if self.target.org is None or item.scope.organization in (None, self.target.org)
        )

    def previous_geocodes(self) -> tuple[GeocodeResult, ...]:
        return tuple(
            GeocodeResult.model_validate(entry.value)
            for entry in latest_valid(
                read_cache(self.directory / "geocode-history-v2.jsonl")
            ).values()
        )

    def scope(self, record: Record) -> EvidenceScope:
        return EvidenceScope(
            city=self.target.city.slug,
            organization=record.organization,
            record_id=record.record_id,
            source_hash=record.source_hash,
        )

    def geocode_dependency_key(self) -> str:
        """판정이 레코드 밖에서 기대는 전부. 상류 산출물의 파일 해시는 여기에 넣지 않는다.

        레코드·후보 조회·사람 확인·확정 복원명은 레코드마다 `lookup_key`가 값으로 담는다.
        그 파일들의 해시를 여기에 묶으면 판정이 하나도 바뀌지 않은 재실행도 모든 키를 갈아
        이력을 통째로 다시 쌓는다. 근거는 ADR-0003이다. 산출물 단위의 낡음은 이 키가 아니라
        envelope의 `dependencies`가 그대로 검사한다.
        """
        return identity.digest(
            {
                "policy": identity.POLICY_VERSION,
                "restoration_policy": restoration.POLICY_VERSION,
                "merchant_policy": merchants.POLICY_VERSION,
            }
        )

    def lookup_cache(self) -> LookupCache:
        """이 실행이 쓸 조회 캐시. 읽기는 여기서 한 번 끝내고 레코드 루프는 사전만 본다.

        부를 때마다 파일을 다시 읽는다. 한 실행이 두 번 부르면 읽기가 두 번이 되므로
        받은 객체를 그 실행 내내 들고 다닌다. 조회를 쌓는 실행은 `with`로 열어야 닫을 때
        캐시에 합친다. 읽기만 하면 `with`가 필요 없다.
        """
        return LookupCache(self.directory / LOOKUP_CACHE)

    def category_cache(self) -> LookupCache:
        """이 실행이 쓸 업종 조회 캐시. 조회 캐시와 같은 규칙으로 읽고, 쌓을 때는 `with`로 연다."""
        return LookupCache(self.directory / CATEGORY_CACHE)

    def cached_proposal(self, key: str) -> CacheEntry | None:
        """같은 입력의 유효한 최신 제안. 제안 자체는 복원 확정이 아니다."""
        return select_cache(self.directory / PROPOSAL_CACHE, key)

    def remember_proposal(
        self, key: str, proposal: RestorationProposal, previous: CacheEntry | None
    ) -> int:
        """새로 수행한 비교마다 revision을 올려 남긴다. 이전 제안은 지우지 않는다."""
        value = RestorationProposal.model_validate(proposal).model_dump(mode="json")
        entry = CacheEntry(
            key=key,
            revision=attempt(previous),
            valid=True,
            evidence=f"{proposal.model}/{proposal.prompt_version} {proposal.reason}",
            value=value,
        )
        append_cache(self.directory / PROPOSAL_CACHE, entry)
        return entry.revision

    def designations(self, records: tuple[Record, ...]) -> tuple[ComparisonRequest, ...]:
        """담당자가 후보 비교를 지정한 건. 파일이 없으면 지정이 없는 것과 같다."""
        return self._scoped("compare", ComparisonRequest, records)

    def candidate_lookups(self, records: tuple[Record, ...]) -> tuple[CandidateLookup, ...]:
        """담당자가 준비한 후보·근거. 파일이 없으면 준비된 조회가 없다는 뜻이다."""
        path = self.directory / "geocode-input.json"
        supplied = (
            CandidateFile.model_validate_json(path.read_text(encoding="utf-8")).lookups
            if path.exists()
            else ()
        )
        all_records = {
            record.record_id: record for record in self.load("parse", ParseOutput).records
        }
        found: dict[str, CandidateLookup] = {}
        for lookup in supplied:
            record = all_records.get(lookup.scope.record_id)
            if record is None or lookup.scope != self.scope(record) or record.record_id in found:
                raise ValueError("candidate scope mismatch or duplicate")
            found[record.record_id] = lookup
        return tuple(
            found.get(record.record_id)
            or CandidateLookup(
                scope=self.scope(record),
                status="error",
                error="not_supplied",
            )
            for record in records
        )

    def _scoped[T: ScopedReview](
        self, name: str, model: type[T], records: tuple[Record, ...]
    ) -> tuple[T, ...]:
        """레코드 범위를 선언한 검토 입력 중 이 실행의 레코드에 해당하는 줄만 돌려준다."""
        supplied = read_reviews(self.paths.manual(self.target, name), model)
        require_scoped_reviews(supplied, self.target.city.slug)
        expected = {self.scope(record) for record in records}
        return tuple(item for item in supplied if item.scope in expected)
