"""UTF-8 contract serialization; writes replace a complete validated file."""

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

from deliciousmap.contracts import (
    BuildOutput,
    CacheEntry,
    ClassifyOutput,
    ClosureOutput,
    Contract,
    FetchOutput,
    GeocodeOutput,
    GeocodeResult,
    HeaderMapOutput,
    ManualCorrection,
    ParseOutput,
    Record,
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

DEPENDENCIES = {
    "fetch": (),
    "headermap": ("fetch.json",),
    "parse": (),
    "classify": ("records.csv", "parse.json"),
    "geocode": ("records.csv", "parse.json", "classify.json"),
    "closure": ("records.csv", "parse.json", "classify.json", "geocode.json"),
    "build": ("records.csv", "parse.json", "classify.json", "geocode.json", "closure.json"),
}


def require_exact_keys(actual: list[str], expected: set[str]) -> None:
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("artifact keys must cover exactly the input targets")


def write_text(path: Path, content: str) -> None:
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
    entry = CacheEntry.model_validate(entry)
    entries = read_cache(path)
    for existing in entries:
        if (existing.key, existing.revision) == (entry.key, entry.revision):
            if existing == entry:
                return
            raise ValueError("cannot overwrite cache history")
    content = "".join(
        json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
        for item in sorted((*entries, entry), key=lambda item: (item.key, item.revision))
    )
    write_text(path, content)


def select_cache(path: Path, key: str) -> CacheEntry | None:
    return next(
        (entry for entry in reversed(read_cache(path)) if entry.key == key and entry.valid), None
    )


class ArtifactStore:
    def __init__(self, paths: Paths, target: Target) -> None:
        self.paths = paths
        self.target = target
        self.directory = paths.city_dir(target)

    def save(self, stage: str, output: Contract) -> None:
        output = OUTPUT_MODELS[stage].model_validate(output)
        self._validate(output)
        if isinstance(output, GeocodeOutput):
            cache_path = self.directory / "geocode-history.jsonl"
            for result in output.results:
                key = f"{result.merchant}|{self.target.city.slug}"
                previous = select_cache(cache_path, key)
                value = result.model_dump(mode="json")
                if previous is None or previous.value != value:
                    append_cache(
                        cache_path,
                        CacheEntry(
                            key=key,
                            revision=1 if previous is None else previous.revision + 1,
                            valid=True,
                            evidence=result.evidence,
                            value=value,
                        ),
                    )
        payload = output.model_dump(mode="json")
        if isinstance(output, ParseOutput):
            write_records(self.directory / "records.csv", output.records)
            payload.pop("records")
        envelope = {
            "schema_version": 1,
            "city": self.target.city.slug,
            "org": self.target.org,
            "dependencies": self._dependencies(stage),
            "payload": payload,
        }
        write_text(
            self.directory / f"{stage}.json",
            json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n",
        )

    def load[T: Contract](self, stage: str, model: type[T]) -> T:
        envelope = json.loads((self.directory / f"{stage}.json").read_text(encoding="utf-8"))
        if (envelope["schema_version"], envelope["city"], envelope["org"]) != (
            1,
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
            manual = self.paths.manual(self.target)
            result["manual"] = hashlib.sha256(
                manual.read_bytes() if manual.exists() else b""
            ).hexdigest()
        return result

    def _validate(self, output: Contract) -> None:
        organizations = {org.slug for org in self.target.organizations}
        if isinstance(output, FetchOutput):
            if not output.sources and output.empty_reason is None:
                raise ValueError("unexplained empty fetch")
            for source in output.sources:
                if source.organization not in organizations:
                    raise ValueError("source organization mismatch")
                source_path = source.path.resolve()
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
            if {item.source_hash for item in output.mappings} != {
                source.source_hash for source in sources
            }:
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
                [item.merchant for item in output.results],
                {record.merchant for record in records if record.record_id in included},
            )
        elif isinstance(output, ClosureOutput):
            geocodes = self.load("geocode", GeocodeOutput).results
            require_exact_keys(
                [item.merchant for item in output.results],
                {item.merchant for item in geocodes if item.status == "success"},
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

    def manual(self) -> tuple[ManualCorrection, ...]:
        path = self.paths.manual(self.target)
        if not path.exists():
            return ()
        corrections = tuple(
            ManualCorrection.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        if any(item.city != self.target.city.slug for item in corrections):
            raise ValueError("manual correction city mismatch")
        return tuple(
            item
            for item in corrections
            if self.target.org is None or item.organization in (None, self.target.org)
        )

    def previous_geocodes(self) -> tuple[GeocodeResult, ...]:
        latest: dict[str, GeocodeResult] = {}
        for entry in read_cache(self.directory / "geocode-history.jsonl"):
            if entry.valid:
                latest[entry.key] = GeocodeResult.model_validate(entry.value)
        return tuple(latest.values())
