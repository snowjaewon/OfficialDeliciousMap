from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from deliciousmap.contracts import Record
from deliciousmap.storage import read_records, write_records


def test_shared_cache_round_trip_preserves_history_and_selects_latest_valid(tmp_path: Path) -> None:
    from deliciousmap.contracts import CacheEntry
    from deliciousmap.storage import append_cache, read_cache, select_cache

    path = tmp_path / "data" / "_shared" / "classify.jsonl"
    older = CacheEntry(
        key="식당", revision=1, valid=True, evidence="synthetic", value={"status": "restaurant"}
    )
    failed = CacheEntry(key="식당", revision=2, valid=False, evidence="validation-failed", value={})
    other = CacheEntry(
        key="aaa", revision=1, valid=True, evidence="synthetic", value={"status": "pending"}
    )
    for entry in (older, failed, other):
        append_cache(path, entry)
    append_cache(path, older)
    assert read_cache(path) == (other, older, failed)
    assert select_cache(path, "식당") == older
    assert select_cache(path, "absent") is None
    assert path.read_text(encoding="utf-8").splitlines()[0].startswith('{"evidence":')


def test_record_csv_round_trip_preserves_values_order_and_utf8(tmp_path: Path) -> None:
    records = (
        Record(
            record_id="expense-2",
            spent_on=date(2026, 1, 2),
            organization="test-org",
            department="총무과",
            merchant="가게, 본점",
            purpose="업무\n협의",
            amount_krw=Decimal("1200.50"),
            source_hash="a" * 64,
            source_location="sheet1:R2",
        ),
        Record(
            record_id="expense-1",
            spent_on=date(2026, 1, 3),
            organization="test-org",
            department="",
            merchant="식당",
            purpose="",
            amount_krw=Decimal("-10"),
            source_hash="b" * 64,
            source_location="sheet1:R3",
        ),
    )
    path = tmp_path / "한글 경로" / "records.csv"
    write_records(path, records)
    assert read_records(path) == records
    content = path.read_bytes()
    assert not content.startswith(b"\xef\xbb\xbf")
    assert (
        content.decode("utf-8").splitlines()[0]
        == "record_id,spent_on,organization,department,merchant,purpose,"
        "amount_krw,source_hash,source_location"
    )
    assert "1200.50" in content.decode("utf-8")


@pytest.mark.parametrize("invalid_date", ["2026-02-30", "20260102", "1767312000"])
def test_csv_rejects_noncanonical_or_invalid_dates(tmp_path: Path, invalid_date: str) -> None:
    fixture = Path(__file__).parent / "fixtures" / "seoul" / "records.csv"
    path = tmp_path / "records.csv"
    path.write_text(
        fixture.read_text(encoding="utf-8").replace("2026-01-02", invalid_date), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        read_records(path)


def test_headerless_mapping_cannot_reference_shared_header_cache() -> None:
    from pydantic import ValidationError

    from deliciousmap.contracts import CacheRef, HeaderMap

    with pytest.raises(ValidationError):
        HeaderMap(
            source_hash="a" * 64,
            table="sheet1",
            layout="table",
            header_rows=(),
            data_start_row=1,
            columns={"merchant": 0},
            amount_multiplier=Decimal("1"),
            cache=CacheRef(key="b" * 64, revision=1),
        )


def test_cache_history_opens_a_new_part_instead_of_passing_the_size_limit(tmp_path: Path) -> None:
    from deliciousmap.contracts import CacheEntry
    from deliciousmap.storage import append_cache_entries, cache_parts, read_cache, select_cache

    path = tmp_path / "gwangju" / "geocode-history-v2.jsonl"
    bulky = tuple(
        CacheEntry(
            key=letter * 64,
            revision=1,
            valid=True,
            evidence="synthetic",
            # 한 항목이 7MB를 넘어 두 개까지만 한 조각에 들어간다.
            value={"body": "가" * 2_400_000},
        )
        for letter in "abc"
    )
    append_cache_entries(path, bulky[:2])
    first = path.read_bytes()
    assert cache_parts(path) == (path,)
    append_cache_entries(path, bulky[2:])
    rolled = path.parent / "geocode-history-v2.002.jsonl"
    # 앞 조각은 그대로 두고 새 조각을 연다. 두 파일 모두 상한 안이다.
    assert path.read_bytes() == first
    assert cache_parts(path) == (path, rolled)
    assert all(part.stat().st_size <= 20_000_000 for part in cache_parts(path))
    assert read_cache(path) == bulky
    assert select_cache(path, "c" * 64) == bulky[2]
    # 이미 쌓인 항목의 재추가는 어느 조각도 다시 쓰지 않는다.
    append_cache_entries(path, bulky)
    assert path.read_bytes() == first
    assert read_cache(path) == bulky


def test_cache_rejects_an_entry_that_cannot_fit_a_part(tmp_path: Path) -> None:
    from deliciousmap.contracts import CacheEntry
    from deliciousmap.storage import append_cache_entries

    path = tmp_path / "geocode-history-v2.jsonl"
    with pytest.raises(ValueError, match="20MB"):
        append_cache_entries(
            path,
            (
                CacheEntry(
                    key="a" * 64,
                    revision=1,
                    valid=True,
                    evidence="synthetic",
                    value={"body": "가" * 7_000_000},
                ),
            ),
        )
    assert not path.exists()


def test_cache_parts_must_be_numbered_without_gaps_and_keep_pairs_unique(tmp_path: Path) -> None:
    from deliciousmap.storage import cache_parts, read_cache, write_text

    path = tmp_path / "geocode-history-v2.jsonl"
    line = (
        '{"schema_version":1,"key":"'
        + "a" * 64
        + '","revision":1,"valid":true,"evidence":"synthetic","value":{}}\n'
    )
    write_text(path, line)
    write_text(path.parent / "geocode-history-v2.003.jsonl", line)
    with pytest.raises(ValueError, match="parts"):
        cache_parts(path)
    (path.parent / "geocode-history-v2.003.jsonl").rename(
        path.parent / "geocode-history-v2.002.jsonl"
    )
    with pytest.raises(ValueError, match="repeat"):
        read_cache(path)
