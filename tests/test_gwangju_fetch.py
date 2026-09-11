"""광주광역시청 게시판 수집을 공개 CLI로 실행한다. HTTP 경계에만 응답을 주입한다."""

import importlib
import json
import sys
import urllib.error
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from deliciousmap import boards
from deliciousmap import transport as transport_module
from deliciousmap.cli import main
from deliciousmap.paths import Paths
from deliciousmap.registry import CITIES, Board, Organization, select_target
from deliciousmap.scrapers.gwangju import GwangjuCityBoard

FIXTURES = Path(__file__).parent / "fixtures" / "gwangju"
LIST_URL = "https://www.gwangju.go.kr/boardList.do"
VIEW_URL = "https://www.gwangju.go.kr/boardView.do"
FILE_URL = "https://www.gwangju.go.kr/fileDownload.do"
BOARD_ID = "BD_0000000252"
# 실측한 컨테이너 서명. 내용은 판정에 쓰이지 않으므로 뒤는 채우지 않는다.
OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 24
OOXML = b"PK\x03\x04" + b"\x00" * 28
PDF = b"%PDF-1.4" + b"\x00" * 24


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def address(url: str, params: Mapping[str, str]) -> str:
    return url + "?" + "&".join(f"{key}={params[key]}" for key in sorted(params))


class BoardTransport:
    """게시판 응답만 대신한다. 스크래퍼와 수집 규칙은 그대로 실행된다."""

    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.requests: list[str] = []

    def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes:
        key = address(url, params)
        self.requests.append(key)
        if key not in self.responses:
            raise AssertionError(f"unexpected board request: {key}")
        return self.responses[key]


def list_page(page: int) -> str:
    return address(LIST_URL, {"boardId": BOARD_ID, "recordCnt": "100", "movePage": str(page)})


def view_page(seq: int) -> str:
    return address(VIEW_URL, {"boardId": BOARD_ID, "seq": str(seq)})


def download(seq: int, file_sn: int) -> str:
    return address(
        FILE_URL,
        {
            "fileSe": "BB",
            "fileKey": f"{BOARD_ID}|{seq}",
            "fileSn": str(file_sn),
            "boardId": BOARD_ID,
            "seq": str(seq),
        },
    )


def board_responses() -> dict[str, bytes]:
    return {
        list_page(1): fixture("board-list-1.html"),
        list_page(2): fixture("board-list-2.html"),
        view_page(11024): fixture("board-view-11024.html"),
        view_page(11022): fixture("board-view-11022.html"),
        download(11024, 1): OLE2,
        download(11024, 2): OOXML,
        download(11022, 1): OLE2,
    }


def paths_at(tmp_path: Path) -> Paths:
    return Paths(
        Path.cwd(),
        tmp_path / "외부 원본",
        tmp_path / "정제 산출물",
        tmp_path / "빌드 출력",
    )


def run_fetch(paths: Paths, transport: BoardTransport, *, city: str = "gwangju") -> int:
    return main(
        [
            "fetch",
            "--city",
            city,
            "--raw-root",
            str(paths.raw_root),
            "--data-root",
            str(paths.data_root),
            "--output-root",
            str(paths.output_root),
        ],
        board_transport=transport,
    )


def fetch_artifact(paths: Paths, city: str = "gwangju") -> dict[str, Any]:
    target = select_target(CITIES, city, None)
    envelope = json.loads((paths.city_dir(target) / "fetch.json").read_text(encoding="utf-8"))
    payload: dict[str, Any] = envelope["payload"]
    return payload


def test_board_modules_load_without_the_registry_importing_them_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스크래퍼는 레지스트리가 선언한다. 어느 쪽을 먼저 불러도 순환하지 않아야 한다."""
    for name in [item for item in sys.modules if item.startswith("deliciousmap")]:
        monkeypatch.delitem(sys.modules, name)
    assert importlib.import_module("deliciousmap.scrapers.gwangju").GwangjuCityBoard is not None


def test_registry_declares_the_measured_city_hall_board() -> None:
    target = select_target(CITIES, "gwangju", "gwangju-city")
    organization = target.organizations[0]
    assert organization.name == "전남광주통합특별시(구)광주광역시"
    board = organization.boards[0]
    assert board.url.startswith("https://www.gwangju.go.kr/boardList.do?")
    assert f"boardId={BOARD_ID}" in board.url


def test_fetch_accepts_every_format_measured_on_this_board(tmp_path: Path) -> None:
    """이 게시판은 .xls·.xlsx 말고 .hwp·.hwpx·.pdf도 올린다(2026-09-11 실측)."""
    paths = paths_at(tmp_path)
    responses = board_responses()
    hwp = "업무추진비 공개 서식(2020. 10월~12월).hwp"
    responses[view_page(11022)] = view_with_suffix(11022, hwp)
    responses[download(11022, 1)] = OLE2
    responses[view_page(11024)] = view_with_suffix(11024, "주요참석자 명단.hwpx")
    responses[download(11024, 1)] = OOXML
    assert run_fetch(paths, BoardTransport(responses)) == 0
    names = [Path(item["path"]).name for item in fetch_artifact(paths)["sources"]]
    assert names == ["11024-1.hwpx", "11022-1.hwp"]

    # 실측한 다섯 번째 형식도 같은 규칙으로 받는다.
    other = paths_at(tmp_path / "pdf")
    responses = board_responses()
    responses[view_page(11024)] = view_with_suffix(11024, "2026.3.시책업무추진비 사용 내역.pdf")
    responses[download(11024, 1)] = PDF
    responses[view_page(11022)] = view_with_suffix(11022, "2026 1분기 업무추진비.xls")
    responses[download(11022, 1)] = OLE2
    assert run_fetch(other, BoardTransport(responses)) == 0
    assert Path(fetch_artifact(other)["sources"][0]["path"]).name == "11024-1.pdf"


def test_fetch_ignores_the_bulk_download_link(tmp_path: Path) -> None:
    """첨부가 둘 이상인 글의 묶음 내려받기 링크에는 `fileSn`이 없다. 첨부로 세지 않는다."""
    paths = paths_at(tmp_path)
    transport = BoardTransport(board_responses())
    assert run_fetch(paths, transport) == 0
    assert len(fetch_artifact(paths)["sources"]) == 3
    assert [key for key in transport.requests if "action=zip" in key] == []


def test_fetch_stores_every_attachment_outside_the_repository(tmp_path: Path) -> None:
    paths = paths_at(tmp_path)
    transport = BoardTransport(board_responses())
    assert run_fetch(paths, transport) == 0
    sources = fetch_artifact(paths)["sources"]
    assert [Path(item["path"]).name for item in sources] == [
        "11024-1.xls",
        "11024-2.xlsx",
        "11022-1.xls",
    ]
    for item in sources:
        stored = Path(item["path"])
        assert stored.is_relative_to(paths.raw_root.resolve())
        assert not stored.is_relative_to(Path.cwd())
        assert stored.read_bytes()[:4] in {OLE2[:4], OOXML[:4]}


def test_fetch_records_the_posting_as_the_source_of_every_original(tmp_path: Path) -> None:
    paths = paths_at(tmp_path)
    assert run_fetch(paths, BoardTransport(board_responses())) == 0
    sources = fetch_artifact(paths)["sources"]
    assert {item["organization"] for item in sources} == {"gwangju-city"}
    assert {item["board"] for item in sources} == {"expenses"}
    assert sources[0]["url"] == view_page(11024)
    assert sources[2]["url"] == view_page(11022)
    # 같은 원본을 두 번 세지 않도록 내용 해시로 구별한다.
    assert sources[0]["source_hash"] == sources[2]["source_hash"]
    assert sources[0]["source_hash"] != sources[1]["source_hash"]


def test_fetch_walks_every_listed_page_and_skips_postings_without_attachments(
    tmp_path: Path,
) -> None:
    paths = paths_at(tmp_path)
    transport = BoardTransport(board_responses())
    assert run_fetch(paths, transport) == 0
    assert transport.requests.count(list_page(1)) == 1
    assert transport.requests.count(list_page(2)) == 1
    # 첨부가 없는 게시글(11023)의 본문은 요청하지 않는다.
    assert view_page(11023) not in transport.requests


def test_fetch_resumes_without_reopening_collected_postings(tmp_path: Path) -> None:
    paths = paths_at(tmp_path)
    assert run_fetch(paths, BoardTransport(board_responses())) == 0
    again = BoardTransport(board_responses())
    assert run_fetch(paths, again) == 0
    # 목록은 다시 훑되 끝낸 게시글의 본문도 첨부도 다시 요청하지 않는다.
    assert [key for key in again.requests if not key.startswith(LIST_URL)] == []
    # 이번 실행에서 새로 받은 것이 없어도 출처는 수집 기록 전체를 싣는다.
    assert len(fetch_artifact(paths)["sources"]) == 3


def test_fetch_recollects_a_posting_left_unfinished(tmp_path: Path) -> None:
    """첨부를 다 받기 전에 멈춘 게시글은 기록되지 않아 다음 실행이 다시 받는다."""
    paths = paths_at(tmp_path)
    responses = board_responses()
    responses[download(11024, 2)] = "<html>일시 오류</html>".encode()
    assert run_fetch(paths, BoardTransport(responses)) == 1
    again = BoardTransport(board_responses())
    assert run_fetch(paths, again) == 0
    assert view_page(11024) in again.requests
    assert len(fetch_artifact(paths)["sources"]) == 3


def test_fetch_refuses_a_response_that_is_not_an_original_container(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = paths_at(tmp_path)
    responses = board_responses()
    responses[download(11024, 1)] = "<!doctype html><html><body>오류</body></html>".encode()
    assert run_fetch(paths, BoardTransport(responses)) == 1
    assert "cause=unsupported-format" in capsys.readouterr().err
    assert not (paths.raw_root / "gwangju").exists()


def test_fetch_refuses_an_attachment_whose_signature_contradicts_its_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = paths_at(tmp_path)
    responses = board_responses()
    # 이름은 .xls인데 내용은 OOXML이다. 확장자를 믿고 저장하지 않는다.
    responses[download(11024, 1)] = OOXML
    assert run_fetch(paths, BoardTransport(responses)) == 1
    assert "cause=unsupported-format" in capsys.readouterr().err


def test_fetch_reports_a_service_failure_instead_of_an_empty_collection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Unavailable:
        def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes:
            raise OSError("connection reset")

    paths = paths_at(tmp_path)
    assert run_fetch(paths, Unavailable()) == 1  # type: ignore[arg-type]
    assert "cause=service-unavailable" in capsys.readouterr().err


def test_fetch_leaves_held_organizations_uncollected_with_their_reason(tmp_path: Path) -> None:
    city = select_target(CITIES, "gwangju", None).city
    held = tuple(replace(org, hold_reason="bot_blocked") for org in city.organizations)
    paths = paths_at(tmp_path)
    transport = BoardTransport(board_responses())
    assert (
        main(
            [
                "fetch",
                "--city",
                "gwangju",
                "--raw-root",
                str(paths.raw_root),
                "--data-root",
                str(paths.data_root),
                "--output-root",
                str(paths.output_root),
            ],
            cities=(replace(city, organizations=held),),
            board_transport=transport,
        )
        == 0
    )
    artifact = fetch_artifact(paths)
    assert artifact["sources"] == []
    assert "bot_blocked" in artifact["empty_reason"]
    assert transport.requests == []


def test_organization_hold_reason_is_declared_only_for_known_causes() -> None:
    with pytest.raises(ValueError):
        Organization("x", "임의 기관", hold_reason="not_yet_visited")  # type: ignore[arg-type]


def listing_without_page_count() -> bytes:
    body = fixture("board-list-1.html").decode("utf-8")
    return body.replace("전체게시글 : 3 / 전체페이지 : 2", "").encode("utf-8")


def view_with_suffix(seq: int, filename: str) -> bytes:
    link = (
        f"/fileDownload.do?fileSe=BB&amp;fileKey={BOARD_ID}%7C{seq}"
        f"&amp;fileSn=1&amp;boardId={BOARD_ID}&amp;seq={seq}"
    )
    return (
        '<html><body><div class="add_file"><ul><li>'
        f'<a href="{link}">{filename}</a>'
        "</li></ul></div></body></html>"
    ).encode()


def test_fetch_refuses_an_attachment_format_not_measured_for_this_board(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = paths_at(tmp_path)
    responses = board_responses()
    # 이 게시판에서 실측한 형식은 .xls·.xlsx·.hwp·.hwpx·.pdf다. .zip은 실측하지 않았다.
    responses[view_page(11024)] = view_with_suffix(11024, "2026년 2분기 업무추진비 묶음.zip")
    # 내용은 온전한 ZIP 컨테이너다. 거절의 이유는 실측하지 않은 형식이라는 것뿐이다.
    responses[download(11024, 1)] = OOXML
    assert run_fetch(paths, BoardTransport(responses)) == 1
    assert "cause=unsupported-format" in capsys.readouterr().err


def test_fetch_reports_a_listing_that_lost_its_page_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = paths_at(tmp_path)
    responses = board_responses()
    responses[list_page(1)] = listing_without_page_count()
    assert run_fetch(paths, BoardTransport(responses)) == 1
    # 구조가 바뀐 게시판은 형식 문제가 아니라 읽지 못한 것으로 알린다.
    assert "cause=adapter-failed" in capsys.readouterr().err


def test_fetch_reports_a_response_too_large_to_read_whole(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = paths_at(tmp_path)
    responses = board_responses()
    responses[download(11024, 1)] = OLE2 + b"\x00" * boards.MAX_RESPONSE_BYTES
    assert run_fetch(paths, BoardTransport(responses)) == 1
    # 잘라 쓰지 않고, 크기 초과를 형식 미지원으로 바꾸지도 않는다.
    assert "cause=adapter-failed" in capsys.readouterr().err


def test_board_declaration_must_carry_its_board_identifier() -> None:
    with pytest.raises(ValueError):
        GwangjuCityBoard(
            Board("expenses", "https://www.gwangju.go.kr/boardList.do?recordCnt=100", object),
            BoardTransport({}),
        )


def test_board_requests_wait_between_calls_to_one_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(transport_module.time, "sleep", waits.append)
    monkeypatch.setattr(
        transport_module.urllib.request, "urlopen", lambda *args, **kwargs: _Response()
    )
    boards.request(boards.default_transport(), LIST_URL, {"boardId": BOARD_ID})
    assert waits == [boards.REQUEST_INTERVAL]


class _Response:
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return b"ok"


class Gone:
    """게시판은 링크했지만 기관이 내주지 않는 원본을 흉내 낸다."""

    def __init__(self, responses: dict[str, bytes], gone: set[str]) -> None:
        self.inner = BoardTransport(responses)
        self.gone = gone

    @property
    def requests(self) -> list[str]:
        return self.inner.requests

    def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes:
        key = address(url, params)
        if key in self.gone:
            self.inner.requests.append(key)
            raise transport_module.ResourceGone("gone")
        return self.inner.fetch(url, params, headers)


def test_fetch_records_an_original_the_organization_no_longer_serves(tmp_path: Path) -> None:
    """404는 서비스 장애가 아니다. 수집을 멈추지 않고 받지 못한 사실을 남긴다."""
    paths = paths_at(tmp_path)
    transport = Gone(board_responses(), {download(11024, 2)})
    assert run_fetch(paths, transport) == 0
    artifact = fetch_artifact(paths)
    assert [Path(item["path"]).name for item in artifact["sources"]] == [
        "11024-1.xls",
        "11022-1.xls",
    ]
    assert len(artifact["missing"]) == 1
    lost = artifact["missing"][0]
    assert lost["reason"] == "gone"
    assert lost["url"] == view_page(11024)
    assert lost["filename"] == "11024-2.xlsx"
    # 뒤에 오는 게시글(11022)의 수집이 막히지 않는다.
    assert download(11022, 1) in transport.requests


def test_fetch_does_not_ask_again_for_an_original_known_to_be_gone(tmp_path: Path) -> None:
    paths = paths_at(tmp_path)
    assert run_fetch(paths, Gone(board_responses(), {download(11024, 2)})) == 0
    again = Gone(board_responses(), {download(11024, 2)})
    assert run_fetch(paths, again) == 0
    assert [key for key in again.requests if not key.startswith(LIST_URL)] == []
    assert len(fetch_artifact(paths)["missing"]) == 1


def test_fetch_still_fails_when_the_board_itself_is_unreachable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """자원 없음과 달리 서비스 장애는 그대로 실패로 알린다."""

    class Broken:
        def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes:
            raise OSError("connection reset")

    paths = paths_at(tmp_path)
    assert run_fetch(paths, Broken()) == 1  # type: ignore[arg-type]
    assert "cause=service-unavailable" in capsys.readouterr().err


class Flaky:
    """urlopen 자리에서 정해진 만큼 실패한 뒤 응답을 준다."""

    def __init__(self, failures: list[Exception]) -> None:
        self.failures = failures
        self.calls = 0

    def __call__(self, request: object, timeout: float | None = None) -> "_Response":
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return _Response()


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(LIST_URL, code, "", {}, None)  # type: ignore[arg-type]


def send(monkeypatch: pytest.MonkeyPatch, failures: list[Exception]) -> tuple[bytes, Flaky]:
    waits: list[float] = []
    monkeypatch.setattr(transport_module.time, "sleep", waits.append)
    flaky = Flaky(failures)
    monkeypatch.setattr(transport_module.urllib.request, "urlopen", flaky)
    return boards.request(boards.default_transport(), LIST_URL, {"boardId": BOARD_ID}), flaky


def test_board_requests_retry_a_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """수만 번 요청하면 일시적 실패를 만난다. 한 번 끊겼다고 수집을 버리지 않는다."""
    body, flaky = send(monkeypatch, [OSError("connection reset"), http_error(503)])
    assert body == b"ok"
    assert flaky.calls == 3


def test_board_requests_give_up_after_the_declared_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures: list[Exception] = [OSError("connection reset")] * boards.REQUEST_ATTEMPTS
    with pytest.raises(boards.BoardUnavailable):
        send(monkeypatch, failures)


def test_board_requests_do_not_retry_a_missing_original(monkeypatch: pytest.MonkeyPatch) -> None:
    """없는 자원은 다시 물어도 같다. 유실을 일시적 실패로 취급하지 않는다."""
    with pytest.raises(boards.OriginalGone):
        send(monkeypatch, [http_error(404)])


def test_board_requests_do_not_retry_a_rejected_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport_module.time, "sleep", lambda _: None)
    flaky = Flaky([http_error(403)])
    monkeypatch.setattr(transport_module.urllib.request, "urlopen", flaky)
    with pytest.raises(boards.BoardUnavailable):
        boards.request(boards.default_transport(), LIST_URL, {"boardId": BOARD_ID})
    assert flaky.calls == 1
