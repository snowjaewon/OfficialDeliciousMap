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
