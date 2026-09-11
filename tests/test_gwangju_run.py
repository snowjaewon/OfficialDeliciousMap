"""광주 한 기관을 fetch부터 build까지 공개 CLI 하나로 잇는다. 모든 외부 응답은 합성이다."""

import json
from datetime import date
from pathlib import Path

import pytest

from deliciousmap.cli import main
from deliciousmap.registry import CITIES
from tests.fakes import FakeTransport, naver_body, naver_item
from tests.gwangju import (
    FakeBoardTransport,
    FakeModel,
    Post,
    city,
    header_answer,
    sheet_a,
    workbook,
)
from tests.test_parse_cli import DATA, configured, record_spending

__all__ = ["configured"]


def test_declared_gwangju_board_is_the_verified_city_hall_board() -> None:
    (gwangju,) = [item for item in CITIES if item.slug == "gwangju"]
    (organization,) = gwangju.organizations
    assert organization.slug == "gwangju-city"
    assert organization.hold_reason is None
    (board,) = organization.boards
    assert board.url == (
        "https://www.gwangju.go.kr/boardList.do?boardId=BD_0000000252&recordCnt=100"
    )


def test_run_builds_a_city_page_whose_ledger_keeps_unmapped_records(
    tmp_path: Path, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_ID", "합성-아이디")
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_SECRET", "합성-비밀")
    record_spending(tmp_path)
    sheet = sheet_a(
        ("2026-01-05", "합성 식당", "간담회", 4.0, 62000.0),
        ("2026-01-06", "합성 마트", "물품 구입", 1.0, 30000.0),
    )
    board = FakeBoardTransport(
        (
            Post(
                7,
                "2026년 1월 집행내역",
                "합성과",
                date(2026, 2, 2),
                (("1월.xls", workbook(sheet)),),
            ),
        )
    )
    model = FakeModel(
        headers=[header_answer()],
        verdict=lambda name: "restaurant" if "식당" in name else "non_restaurant",
    )
    naver = FakeTransport(naver_body(naver_item("합성 식당", "광주 합성로 1")))
    assert (
        main(
            [
                "run",
                "--city",
                "gwangju",
                "--raw-root",
                str(tmp_path / "외부 원본"),
                "--data-root",
                str(tmp_path / DATA),
                "--output-root",
                str(tmp_path / "출력"),
            ],
            cities=(city(),),
            board_transport=board,
            model_transport=model,
            naver_transport=naver,
        )
        == 0
    )
    # 원본에는 주소가 없어 네이버 후보만으로는 업소를 확정하지 않는다(#33).
    geocoded = json.loads(
        (tmp_path / DATA / "gwangju" / "geocode.json").read_text(encoding="utf-8")
    )
    assert [item["reason"] for item in geocoded["payload"]["results"]] == ["missing_address"]
    published = json.loads(
        (tmp_path / "출력" / "gwangju" / "records.json").read_text(encoding="utf-8")
    )
    assert [(item["merchant"], item["map_status"]) for item in published["records"]] == [
        ("합성 식당", "geocode_failed"),
        ("합성 마트", "non_restaurant"),
    ]
    markers = json.loads(
        (tmp_path / "출력" / "gwangju" / "markers.json").read_text(encoding="utf-8")
    )
    assert markers["markers"] == []
    page = (tmp_path / "출력" / "gwangju" / "index.html").read_text(encoding="utf-8")
    assert "광주광역시청" in page
