"""UTF-8 contract serialization; writes replace a complete validated file."""

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

from deliciousmap import identity, restoration
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
    FetchOutput,
    GeocodeOutput,
    GeocodeResult,
    HeaderMapOutput,
    IdentityConfirmation,
    LedgerEntry,
    ManualCorrection,
    NameRestoration,
    ParseOutput,
    ProviderCandidates,
    Record,
    RestorationProposal,
    ScopedReview,
)
from deliciousmap.paths import Paths
from deliciousmap.registry import Target

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

# geocode·closure는 조회 요청 기록을 포함하는 v4, build는 좌표 출처·장부 사유를 담은 v6다.
SCHEMA_VERSIONS = {"fetch": 2, "geocode": 4, "closure": 4, "build": 6}

# 제공자 조회 캐시. 확정 업소 판정 이력(geocode-history-v2.jsonl)과 분리해 둔다.
LOOKUP_CACHE = "geocode-lookup-v1.jsonl"
# 모델 제안 이력. 사람 확인 입력·업소 판정과 분리해 두며 판정의 의존성에 넣지 않는다.
PROPOSAL_CACHE = "restore-proposal-v1.jsonl"

DEPENDENCIES = {
    "fetch": (),
    "headermap": ("fetch.json",),
    "parse": (),
    "classify": ("records.csv", "parse.json"),
    "geocode": ("records.csv", "parse.json", "classify.json"),
    "closure": ("records.csv", "parse.json", "classify.json", "geocode.json"),
    "build": ("records.csv", "parse.json", "classify.json", "geocode.json", "closure.json"),
}


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
    entries: tuple[NameRestoration, ...] | tuple[ScopedReview, ...], city: str
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
    require_size(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def require_size(content: str) -> None:
    if len(content.encode("utf-8")) > 20_000_000:
        raise ValueError("artifact exceeds 20MB; partition before writing")


def write_records(path: Path, records: tuple[Record, ...]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=RECORD_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(Record.model_validate(record).model_dump(mode="json"))
    write_text(path, stream.getvalue())


def read_records(path: Path) -> tuple[Record, ...]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(RECORD_FIELDS):
            raise ValueError("invalid record CSV columns")
        records = []
        for row in reader:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", row["spent_on"] or ""):
                raise ValueError("record date must use YYYY-MM-DD")
            records.append(Record.model_validate(row))
        return tuple(records)


def read_cache(path: Path) -> tuple[CacheEntry, ...]:
    if not path.exists():
        return ()
    entries = tuple(
        CacheEntry.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    )
    identities = [(entry.key, entry.revision) for entry in entries]
    if identities != sorted(set(identities)):
        raise ValueError("cache must have unique, sorted key/revision pairs")
    return entries


def append_cache(path: Path, entry: CacheEntry) -> None:
    append_cache_entries(path, (entry,))


def append_cache_entries(path: Path, additions: tuple[CacheEntry, ...]) -> None:
    entries = {(entry.key, entry.revision): entry for entry in read_cache(path)}
    for entry in additions:
        entry = CacheEntry.model_validate(entry)
        key = (entry.key, entry.revision)
        if key in entries and entries[key] != entry:
            raise ValueError("cannot overwrite cache history")
        entries[key] = entry
    content = "".join(
        json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
        for item in sorted(entries.values(), key=lambda item: (item.key, item.revision))
    )
    write_text(path, content)


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
    write_text(
        path,
        "".join(
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
            for item in (*entries, entry)
        ),
    )


def attempt(previous: CacheEntry | None) -> int:
    """같은 요청을 다시 수행한 횟수. 재시도마다 다른 이력·예약 항목이 된다."""
    return 1 if previous is None else previous.revision + 1


def select_cache(path: Path, key: str) -> CacheEntry | None:
    return next(
        (entry for entry in reversed(read_cache(path)) if entry.key == key and entry.valid), None
    )


class ArtifactStore:
    def __init__(self, paths: Paths, target: Target) -> None:
        self.paths = paths
        self.target = target
        self.directory = paths.city_dir(target)

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
        content = json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n"
        require_size(content)
        if isinstance(output, ParseOutput):
            write_records(self.directory / "records.csv", output.records)
        if isinstance(output, GeocodeOutput):
            cache_path = self.directory / "geocode-history-v2.jsonl"
            latest = {entry.key: entry for entry in read_cache(cache_path) if entry.valid}
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
        write_text(path, content)

    def load[T: Contract](self, stage: str, model: type[T]) -> T:
        envelope = json.loads((self.directory / f"{stage}.json").read_text(encoding="utf-8"))
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

    def _dependencies(self, stage: str) -> dict[str, str]:
        result = {
            name: hashlib.sha256((self.directory / name).read_bytes()).hexdigest()
            for name in DEPENDENCIES[stage]
        }
        if stage == "classify":
            result["manual"] = file_digest(self.paths.manual(self.target, "classify"))
        if stage == "geocode":
            result["candidates"] = file_digest(self.directory / "geocode-input.json")
            result["lookups"] = file_digest(self.directory / LOOKUP_CACHE)
            result["confirmations"] = file_digest(self.paths.manual(self.target, "geocode"))
            result["policy"] = identity.POLICY_VERSION
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
            sources = self.load("fetch", FetchOutput).sources
            mapped = {item.source_hash for item in output.mappings}
            unresolved = [item.source_hash for item in output.unresolved]
            if (
                len(unresolved) != len(set(unresolved))
                or mapped & set(unresolved)
                or mapped | set(unresolved) != {source.source_hash for source in sources}
            ):
                raise ValueError("mapping must cover all fetched originals")
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
        fetched = {source.source_hash for source in self.load("fetch", FetchOutput).sources}
        if len(reported) != len(set(reported)) or set(reported) != fetched:
            raise ValueError("parse report must cover every fetched original once")
        counts: dict[str, int] = {}
        for record in output.records:
            counts[record.source_hash] = counts.get(record.source_hash, 0) + 1
        if any(item.records != counts.get(item.source_hash, 0) for item in output.sources):
            raise ValueError("parse report record counts do not match the records")

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
        entries = read_reviews(self.paths.manual(self.target, "restore"), NameRestoration)
        require_scoped_reviews(entries, self.target.city.slug)
        return tuple(
            item
            for item in entries
            if self.target.org is None or item.scope.organization in (None, self.target.org)
        )

    def previous_geocodes(self) -> tuple[GeocodeResult, ...]:
        latest: dict[str, GeocodeResult] = {}
        for entry in read_cache(self.directory / "geocode-history-v2.jsonl"):
            if entry.valid:
                latest[entry.key] = GeocodeResult.model_validate(entry.value)
        return tuple(latest.values())

    def scope(self, record: Record) -> EvidenceScope:
        return EvidenceScope(
            city=self.target.city.slug,
            organization=record.organization,
            record_id=record.record_id,
            source_hash=record.source_hash,
        )

    def geocode_dependency_key(self) -> str:
        return identity.digest(self._dependencies("geocode"))

    def cached_candidates(self, key: str) -> CacheEntry | None:
        """조회 캐시의 유효한 최신 항목. 적중 자체는 업소 확정이 아니다."""
        return select_cache(self.directory / LOOKUP_CACHE, key)

    def remember_candidates(
        self,
        key: str,
        found: ProviderCandidates,
        evidence: str,
        previous: CacheEntry | None,
    ) -> int:
        """같은 결과는 다시 쌓지 않고, 달라지면 새 revision으로 이력에 남긴다."""
        value = ProviderCandidates.model_validate(found).model_dump(mode="json")
        if previous is not None and previous.value == value:
            return previous.revision
        entry = CacheEntry(
            key=key,
            revision=1 if previous is None else previous.revision + 1,
            valid=True,
            evidence=evidence,
            value=value,
        )
        append_cache(self.directory / LOOKUP_CACHE, entry)
        return entry.revision

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

    def confirmations(self, records: tuple[Record, ...]) -> tuple[IdentityConfirmation, ...]:
        return self._scoped("geocode", IdentityConfirmation, records)

    def _scoped[T: ScopedReview](
        self, name: str, model: type[T], records: tuple[Record, ...]
    ) -> tuple[T, ...]:
        """레코드 범위를 선언한 검토 입력 중 이 실행의 레코드에 해당하는 줄만 돌려준다."""
        supplied = read_reviews(self.paths.manual(self.target, name), model)
        require_scoped_reviews(supplied, self.target.city.slug)
        expected = {self.scope(record) for record in records}
        return tuple(item for item in supplied if item.scope in expected)
