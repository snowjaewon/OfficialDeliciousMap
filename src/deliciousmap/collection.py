"""게시판 수집. 스크래퍼가 낸 게시글을 저장소 밖 원본과 그 출처 기록으로 바꾼다."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from deliciousmap import boards, period
from deliciousmap.contracts import FetchOutput, MissingOriginal, SourceRef
from deliciousmap.paths import Paths
from deliciousmap.pipeline import AdapterFailure, FailureCause
from deliciousmap.registry import Board, Target
from deliciousmap.storage import write_text
from deliciousmap.transport import Transport

# 수집을 마친 게시글의 추가형 기록. 원본과 함께 저장소 밖에 두며, 중단한 수집을 이어서
# 할 때 이미 끝낸 게시글의 본문을 다시 열지 않게 한다.
LEDGER = "collected.jsonl"
# 실측하지 않은 형식을 만난 첨부의 목록. 게시판을 끝까지 훑은 뒤 한 번에 보고하기 위한 것이며
# 기록에 남기지 않으므로 형식을 선언하고 다시 실행하면 그 게시글부터 다시 받는다.
UNMEASURED = "unmeasured.jsonl"
# 목록에서 읽은 게시일·제목의 색인. 원본과 함께 저장소 밖에 두며, 이미 받아 둔 원본에도
# 목록만 다시 읽어 이 값을 채운다. 지우면 다음 실행이 목록에서 다시 만든다.
LISTING = "listing.jsonl"
# 목록 순회가 어느 쪽까지 끝났는지의 기록(#154). 원본과 함께 저장소 밖에 둔다. 순회가 끊기면
# 다음 실행이 그 쪽부터 잇고, 끝까지 훑으면 지운다. 지우면 다음 실행이 1쪽부터 훑는다.
LISTING_PROGRESS = "listing-progress.json"
# 다시 요청해도 달라지지 않는 사유(목록을 읽지 못함·실측하지 않은 형식)까지 경고로만 남기고
# 다음 게시판으로 가는 도시. #132가 울산에, #152가 서울에 켰다. 그런 사유는 그 게시판이 아니라
# 우리 스크래퍼가 틀렸다는 뜻이라 도시 공통으로 넓히지 않는다 — 울산 시청 부서장 목록처럼
# 기관이 적은 값 하나(`202-12-28`)로 훑기가 끝나는 게시판이 있어(#145) 그 도시는 받아들이기로
# 했고, 받아들이지 않은 도시는 그 자리에서 알린다.
#
# #172가 대전을 더했다. 중구 과장급 목록 마지막 291쪽은 기관 서버가 2016년 글 행 중간에 오류
# 화면 HTML을 통째로 끼워 넣어 행이 닫히지 않는다. 대상 기간 밖 옛 글 하나로 중구 전체를 실패로
# 두지 않기로 했다(2026-09-17 사용자 결정).
#
# 끊긴 게시판(service-unavailable)은 이 목록과 무관하게 도시를 가리지 않고 이어 간다(#140).
FAILURE_TOLERANT = frozenset({"daejeon", "seoul", "ulsan"})
# 실측하지 않은 형식을 경고로만 남기고 통과시키는 도시. 울산 하나뿐이다 — 그 완화는
# 조용히 빠지는 첨부를 만들므로(울산 장부 실측: 북구 18·동구 28·남구 10건) 서울에는
# 켜지 않는다. 서울은 스캔본을 만나면 멈췄고, 그래서 `jpeg`·`png`를 실측 컨테이너로
# 선언해 풀었다.
#
# 이 도시 목록을 없애려면 울산 장부의 그 56건이 무슨 형식인지 판정해야 하는데 그 원본은
# 울산을 수집한 PC에 있다. 확인하지 않은 채로 다른 도시의 파이프라인 결과를 바꾸지 않는다.
# 게시판 장애를 이어 가는 규칙과는 다른 규칙이라 #140에서 함께 없애지 않았다.
UNMEASURED_TOLERANT = frozenset({"ulsan"})


def collect(target: Target, paths: Paths, transport: Transport) -> FetchOutput:
    """선택한 기관의 게시판을 훑는다. 수집하지 못한 이유는 0건으로 숨기지 않는다."""
    sources: list[SourceRef] = []
    missing: list[MissingOriginal] = []
    unmeasured: list[dict[str, str]] = []
    failures: list[str] = []
    # 이어 간 장애. 한 건도 거두지 못한 채 끝나면 그중 첫 사유로 수집을 실패로 알린다.
    outages: list[FailureCause] = []
    visited: list[str] = []
    held: list[str] = []
    uncollected = 0
    filtered = 0
    for organization in target.organizations:
        if organization.hold_reason is not None:
            held.append(f"{organization.slug}={organization.hold_reason}")
            continue
        for board in organization.boards:
            visited.append(f"{organization.slug}/{board.slug}")
            directory = paths.board_dir(target, organization.slug, board.slug)
            try:
                walked = _walk(board, directory, transport)
            except AdapterFailure as exc:
                # 다시 요청해도 달라지지 않는 사유다. 받아들이기로 한 도시만 이어 간다.
                if target.city.slug not in FAILURE_TOLERANT:
                    raise
                failures.append(f"{organization.slug}/{board.slug}={exc.cause.value}")
                walked = _Walked([], 0, 0)
            if walked.failure is not None:
                # #140의 결정: 끊긴 게시판을 이어 가는 규칙에서 도시 이름을 뺀다. 부산은 기관
                # 열일곱이 호스트 열여섯에 흩어져 있어 공개 서버 하나가 끊기는 일이 상례인데,
                # 도시 이름은 게시판이 끊겼는지와 무관하다. 끊긴 게시판 하나가 나머지 기관의
                # 원본까지 0건으로 만들지 않도록 사유만 장부 경고에 남기고 다음 게시판으로 간다.
                outages.append(walked.failure)
                failures.append(f"{organization.slug}/{board.slug}={walked.failure.value}")
            unmeasured.extend(walked.unmeasured)
            uncollected += walked.uncollected
            filtered += walked.filtered
            collected, gone = _ledger(directory)
            listed = _listed(directory)
            sources.extend(
                _sources(
                    directory,
                    collected,
                    listed,
                    organization.slug,
                    board.slug,
                    _html(board.scraper.published_suffixes),
                )
            )
            missing.extend(_missing(gone, listed, organization.slug, board.slug))
    if not sources and outages:
        # 게시판을 모두 훑었는데 한 건도 거두지 못했고 그 원인이 장애다. 이것까지 경고로
        # 남기면 장애가 "첨부가 없는 기관"과 같은 모양이 된다. 실패는 실패로 알린다.
        raise AdapterFailure(outages[0])
    if unmeasured and target.city.slug not in UNMEASURED_TOLERANT:
        # 게시판을 끝까지 훑은 뒤에 한 번에 알린다. 형식을 하나 만날 때마다 멈추지 않는다.
        raise AdapterFailure(FailureCause.UNSUPPORTED_FORMAT)
    if unmeasured:
        failures.append(f"unmeasured-attachments={len(unmeasured)}")
    warning = _failure_reason(failures)
    if sources:
        return FetchOutput(
            sources=tuple(sources),
            missing=tuple(missing),
            empty_reason=warning,
            uncollected_postings=uncollected,
            filtered_postings=filtered,
        )
    if not visited and not held:
        # 아직 게시판을 선언하지 않은 도시를 수집 완료로 표시하지 않는다.
        raise AdapterFailure(FailureCause.NOT_IMPLEMENTED)
    return FetchOutput(
        sources=(),
        missing=tuple(missing),
        empty_reason=_join_reasons(_empty_reason(visited, held), warning),
        uncollected_postings=uncollected,
        filtered_postings=filtered,
    )


def _html(published: frozenset[str]) -> bool:
    """화면 자체가 원본인 게시판인지. 스크래퍼가 `.html`을 실측 확장자로 선언하면 참이다.

    선언은 게시판마다 다르므로 컨테이너 판정도 게시판 단위로 갈린다. 첨부를 내려받는
    게시판에서 200으로 오는 오류 화면을 원본으로 삼지 않기 위해서다.
    """
    return boards.HTML_SUFFIX in published


@dataclass(frozen=True)
class _Walked:
    """게시판 하나를 훑은 결과. 끝까지 못 갔더라도 그때까지 읽은 것을 그대로 담는다."""

    unmeasured: list[dict[str, str]]
    # 게시일이 대상 연도 밖이라 원본을 받지 않은 게시글 수.
    uncollected: int
    # 업무추진비 집행기관이 아니라 스크래퍼가 걸러 낸 줄 수. 스크래퍼가 세지 않으면 0이다.
    filtered: int
    # 훑기를 끊은 장애. 없으면 게시판을 끝까지 봤다는 뜻이다. 끊긴 뒤에도 위의 수는 남는다 —
    # 버리면 "기간 밖 게시글이 없는 게시판"과 "끊겨서 세지 못한 게시판"이 같은 모양이 된다.
    failure: FailureCause | None = None


def _walk(board: Board, directory: Path, transport: Transport) -> _Walked:
    """게시판을 훑어 대상 기간 게시글의 원본을 내려받고 게시글 단위로 기록한다.

    실측하지 않은 형식은 그 자리에서 멈추지 않고 모아 두었다가 끝에 한 번에 알린다.
    22년치 게시판은 드문 형식이 뒤늦게 나오므로, 하나 만날 때마다 멈추면 그만큼 다시 훑어야 한다.

    목록은 끝까지 훑되 게시일이 대상 연도 밖인 게시글은 본문도 열지 않는다(`period.collects`).
    이미 받아 둔 원본은 그 규칙과 무관하게 장부에 남으며, 받지 않은 게시글은 수로 돌려준다.
    """
    collected, gone = _ledger(directory)
    done = set(collected) | set(gone)
    listed = _listed(directory)
    scraper: boards.BoardScraper = board.scraper(board, transport)
    unmeasured: list[dict[str, str]] = []
    uncollected = 0
    failure: FailureCause | None = None

    def skip(post_id: str, posted: date | None) -> bool:
        """본문을 열지 않고 넘길 게시글. 아래 루프가 같은 판정을 다시 쓰므로 여기 한 곳에 둔다."""
        return post_id in done or not period.collects(posted)

    def settle(next_page: int) -> None:
        """넘긴 쪽을 디스크에 남긴다. 프로세스가 통째로 죽으면 아래 `finally`도 돌지 않으므로
        이어 갈 실행이 셀 목록 색인을 먼저 쓰고, 그다음에 어느 쪽부터 이을지를 쓴다.

        사람이 봐야 하는 첨부를 만난 뒤로는 쪽을 넘겼다고 쓰지 않는다. 그 목록은 끝에 한 번에
        알리고 기록하지 않으므로, 넘겼다고 쓰면 이어 간 실행이 그 첨부를 다시 보지 않는다.
        """
        _remember_listing(directory, listed)
        if not unmeasured:
            _remember_progress(directory, board, next_page, _filtered(scraper))

    resumed = False
    if isinstance(scraper, boards.ResumesListing):
        first_page, filtered = _progress(directory, board)
        resumed = first_page > 1
        scraper.resume(first_page, filtered, settle)
    try:
        for posting in scraper.postings(skip):
            if posting.posted is not None or posting.title:
                # 이미 끝낸 게시글도 목록에서 읽은 값은 이번 훑기의 것으로 갱신한다.
                listed[posting.post_id] = Listed(
                    posting.posted, posting.title, posting.department, posting.spent_on
                )
            if posting.post_id in done:
                continue
            if skip(posting.post_id, posting.posted):
                # 이번 수집이 받지 않는 게시글. 장부에 남기지 않으므로 기간을 넓히면 다시 받는다.
                uncollected += 1
                continue
            stored, lost, empty, locked, stray, oversize = [], [], [], [], [], []
            published = scraper.published_suffixes
            unknown = [item for item in posting.attachments if item.suffix not in published]
            unmeasured.extend(_note(item, "format not measured for this board") for item in unknown)
            if unknown:
                # 실측하지 않은 형식이 있는 게시글은 기록하지 않는다. 선언한 뒤 다시 받는다.
                continue
            rejected = []
            for attachment in posting.attachments:
                try:
                    _store(directory / attachment.name, attachment, transport, scraper)
                except boards.OriginalGone:
                    # 기관이 더는 내주지 않는 원본이다. 다시 요청해도 같으므로 장부에 남긴다.
                    lost.append(attachment)
                except boards.EmptyOriginal:
                    # 200이지만 받을 것이 없다. 유실과 같은 부류로 장부에 남긴다.
                    empty.append(attachment)
                except boards.ProtectedOriginal:
                    # 기관이 DRM으로 잠갔다. 형식을 선언해도 읽히지 않으므로 사람이 볼
                    # 목록이 아니라 장부에 남긴다. 잠기지 않은 첨부는 그대로 받는다.
                    locked.append(attachment)
                except boards.NotAnOriginal:
                    # 편집 도구가 만든 부속 파일이다. 형식을 선언해도 표가 생기지 않으므로
                    # 사람이 볼 목록이 아니라 장부에 남기고 다음 첨부로 간다.
                    stray.append(attachment)
                except boards.OversizeOriginal:
                    # 한 번에 읽어 둘 수 있는 크기를 넘는다. 잘라 쓰면 원본이 아니므로
                    # 사람이 볼 목록이 아니라 장부에 남기고 다음 첨부로 간다.
                    oversize.append(attachment)
                except boards.UnsupportedOriginal as reason:
                    # 내용이 실측한 컨테이너와 다르다. 사람이 봐야 하므로 모아서 알린다.
                    rejected.append(_note(attachment, str(reason)))
                else:
                    stored.append(attachment)
            if rejected:
                # 사람이 봐야 하는 첨부가 있는 게시글은 기록하지 않는다. 판단한 뒤 다시 받는다.
                unmeasured.extend(rejected)
                continue
            # 게시글을 끝낸 뒤에만 기록한다. 중간에 멈추면 그 게시글은 다시 수집한다.
            _remember(directory, posting, stored, lost, empty, locked, stray, oversize)
        # 끝까지 훑었다. 다음 실행은 새로 올라온 게시글을 보도록 1쪽부터 훑는다.
        (directory / LISTING_PROGRESS).unlink(missing_ok=True)
    except boards.UnsupportedOriginal:
        raise AdapterFailure(FailureCause.UNSUPPORTED_FORMAT) from None
    except boards.UnreadableBoard:
        raise AdapterFailure(FailureCause.ADAPTER_FAILED) from None
    except boards.BoardUnavailable:
        # 다시 요청하면 달라질 수 있는 장애다. 여기서 끊더라도 그때까지 세어 둔 수는 훑기
        # 결과에 담아 돌려준다 — 버리면 "기간 밖 게시글이 없는 게시판"과 같은 모양이 된다.
        failure = FailureCause.SERVICE_UNAVAILABLE
    finally:
        # 게시판이 도중에 실패해도 그때까지 목록에서 읽은 값은 맞다. 이미 받은 원본이 게시일·
        # 제목·집행일을 잃지 않게 남긴다(시청 부서장 목록이 2020년 구간의 행에서 멈춘 실측).
        _remember_listing(directory, listed)
    _report_unmeasured(directory, unmeasured)
    if resumed:
        # 이어 간 실행은 앞선 실행이 넘긴 쪽을 다시 읽지 않는다. 그 쪽의 게시글은 목록 색인에
        # 남아 있으므로 색인에서 같은 판정(끝내지 않았고 기간 밖)으로 세면 1쪽부터 훑은 실행과
        # 같은 게시글 단위가 된다. 처음부터 훑은 실행은 전과 같이 이번에 본 게시글만 센다.
        # `skip`은 끝낸 게시글도 참이라 쓰지 않는다 — 위 루프도 끝낸 게시글을 먼저 거른 뒤 센다.
        uncollected = sum(
            post_id not in done and not period.collects(entry.posted)
            for post_id, entry in listed.items()
        )
    return _Walked(unmeasured, uncollected, _filtered(scraper), failure)


def _progress(directory: Path, board: Board) -> tuple[int, int]:
    """이어 갈 쪽과 그때까지 걸러 낸 수. 기록이 없거나 다른 목록의 것이면 1쪽부터 훑는다.

    목록 색인이 없어도 1쪽부터다. 이어 간 실행은 넘긴 쪽의 게시글을 색인에서 센다.
    """
    path = directory / LISTING_PROGRESS
    if not path.exists() or not (directory / LISTING).exists():
        return 1, 0
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        page, filtered = entry["next_page"], entry["filtered"]
        valid = entry["url"] == board.url and _whole(page) and page > 1 and _whole(filtered)
    except (ValueError, KeyError, TypeError):
        return 1, 0
    return (page, filtered) if valid else (1, 0)


def _whole(value: object) -> bool:
    """0 이상의 정수인지. JSON의 `true`는 파이썬에서 1과 같으므로 따로 뺀다."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _remember_progress(directory: Path, board: Board, next_page: int, filtered: int) -> None:
    """목록 주소를 함께 남긴다. 레지스트리가 게시판 주소를 바꾸면 남은 기록을 쓰지 않는다."""
    entry = {"filtered": filtered, "next_page": next_page, "url": board.url}
    write_text(directory / LISTING_PROGRESS, json.dumps(entry, sort_keys=True) + "\n")


def _filtered(scraper: boards.BoardScraper) -> int:
    """스크래퍼가 걸러 낸 게시글 수. 섞인 게시판이 아니면 0이다."""
    return scraper.filtered if isinstance(scraper, boards.FiltersRows) else 0


def _note(attachment: boards.Attachment, reason: str) -> dict[str, str]:
    """사람이 봐야 하는 첨부 하나. 게시글과 무엇이 걸렸는지만 남긴다."""
    return {
        "post_id": attachment.post_id,
        "url": attachment.page_url,
        "suffix": attachment.suffix,
        "reason": reason,
    }


def _report_unmeasured(directory: Path, unmeasured: list[dict[str, str]]) -> None:
    """무엇을 실측해야 하는지 한 곳에 남긴다. 원본과 같이 저장소 밖에 둔다."""
    path = directory / UNMEASURED
    if not unmeasured:
        path.unlink(missing_ok=True)
        return
    directory.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in unmeasured]
    write_text(path, "".join(f"{line}\n" for line in lines))


@dataclass(frozen=True)
class Listed:
    """목록에서 읽은 게시글 하나. 지출 기간은 제목에만 있어 출처에 함께 싣는다."""

    posted: date | None
    title: str
    department: str
    # 상세 키가 밝힌 집행일(`boards.Posting.spent_on`). 그런 게시판이 아니면 없다.
    spent_on: date | None = None

    @staticmethod
    def of(listed: dict[str, "Listed"], post_id: str) -> tuple[date | None, str | None, str | None]:
        """출처에 실을 목록 값. 계약은 빈 글자를 받지 않으므로 없는 것으로 남긴다."""
        entry = listed.get(post_id)
        if entry is None:
            return None, None, None
        return entry.posted, entry.title or None, entry.department or None

    @staticmethod
    def spent_on_of(listed: dict[str, "Listed"], post_id: str) -> date | None:
        entry = listed.get(post_id)
        return entry.spent_on if entry else None


def _listed(directory: Path) -> dict[str, Listed]:
    """목록 색인. 같은 게시글이 여러 줄이면 마지막 줄이 이긴다. 읽지 못한 줄은 버린다."""
    path = directory / LISTING
    listed: dict[str, Listed] = {}
    if not path.exists():
        return listed
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            posted = entry["posted"]
            spent_on = entry.get("spent_on")
            listed[str(entry["post_id"])] = Listed(
                date.fromisoformat(posted) if posted else None,
                str(entry["title"]),
                str(entry.get("department") or ""),
                date.fromisoformat(spent_on) if spent_on else None,
            )
        except (ValueError, KeyError, TypeError):
            continue
    return listed


def _remember_listing(directory: Path, listed: dict[str, Listed]) -> None:
    """색인은 목록을 그대로 옮긴 것이라 통째로 다시 쓴다. 수집 기록과 달리 이력이 아니다."""
    if not listed:
        return
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "post_id": post_id,
                "posted": entry.posted.isoformat() if entry.posted else None,
                "title": entry.title,
                "department": entry.department,
                # 상세 키가 없는 게시판의 색인은 전과 같은 줄로 남긴다.
                **({"spent_on": entry.spent_on.isoformat()} if entry.spent_on else {}),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        # 게시글 번호는 연번이지만 숫자라고 단정하지 않는다. 자릿수를 먼저 보고 정렬한다.
        for post_id, entry in sorted(listed.items(), key=lambda item: (len(item[0]), item[0]))
    ]
    write_text(directory / LISTING, "".join(f"{line}\n" for line in lines))


def _sources(
    directory: Path,
    collected: dict[str, "Collected"],
    listed: dict[str, Listed],
    organization: str,
    board: str,
    html: bool = False,
) -> list[SourceRef]:
    """수집 기록 전체를 출처로 옮긴다. 이번 실행에서 새로 받은 것만 세지 않는다.

    컨테이너는 저장한 원본에서 다시 판정한다. 게시판이 붙인 확장자를 그대로 믿지 않는다.
    """
    references = []
    for post_id, entry in collected.items():
        posted, title, department = Listed.of(listed, post_id)
        for name in entry.files:
            path = directory / name
            if not path.exists():
                raise AdapterFailure(FailureCause.IO_ERROR)
            body = path.read_bytes()
            references.append(
                SourceRef(
                    path=path,
                    source_hash=hashlib.sha256(body).hexdigest(),
                    organization=organization,
                    board=board,
                    url=entry.url,
                    container=boards.container_of(body, html=html),
                    department=department,
                    posted=posted,
                    title=title,
                    spent_on=Listed.spent_on_of(listed, post_id),
                )
            )
    return references


@dataclass(frozen=True)
class Collected:
    """수집을 마친 게시글 하나의 기록. 출처 주소와 그때 저장한 원본 이름을 남긴다."""

    url: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class Gone:
    """게시판이 링크했지만 받을 것이 없던 원본. 게시글 주소와 밝힌 이름·사유만 남긴다."""

    url: str
    # (파일 이름, 사유) 쌍. 사유는 `MissingOriginal.reason`과 같은 값이다.
    files: tuple[tuple[str, str], ...]


def _ledger(directory: Path) -> tuple[dict[str, Collected], dict[str, Gone]]:
    """마지막 줄이 끊긴 기록은 버린다. 그 게시글은 아직 끝내지 못한 것으로 본다."""
    path = directory / LEDGER
    collected: dict[str, Collected] = {}
    gone: dict[str, Gone] = {}
    if not path.exists():
        return collected, gone
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            post_id = str(entry["post_id"])
            url = str(entry["url"])
            files = tuple(str(name) for name in entry["files"])
            lost = tuple((str(name), "gone") for name in entry.get("gone", ()))
            lost += tuple((str(name), "empty") for name in entry.get("empty", ()))
            lost += tuple((str(name), "drm") for name in entry.get("drm", ()))
            lost += tuple(
                (str(name), "not_an_original") for name in entry.get("not_an_original", ())
            )
            lost += tuple((str(name), "too_large") for name in entry.get("too_large", ()))
        except (ValueError, KeyError, TypeError):
            continue
        if files:
            collected[post_id] = Collected(url, files)
        if lost:
            gone[post_id] = Gone(url, lost)
    return collected, gone


def _missing(
    gone: dict[str, Gone], listed: dict[str, Listed], organization: str, board: str
) -> list[MissingOriginal]:
    lost: list[MissingOriginal] = []
    for post_id, entry in gone.items():
        posted, title, _ = Listed.of(listed, post_id)
        lost.extend(
            MissingOriginal(
                organization=organization,
                board=board,
                url=entry.url,
                filename=name,
                reason=reason,
                posted=posted,
                title=title,
            )
            for name, reason in entry.files
        )
    return lost


def _remember(
    directory: Path,
    posting: boards.Posting,
    stored: list[boards.Attachment],
    lost: list[boards.Attachment],
    empty: list[boards.Attachment],
    locked: list[boards.Attachment],
    stray: list[boards.Attachment],
    oversize: list[boards.Attachment],
) -> None:
    if not posting.attachments:
        return
    entry = {
        "post_id": posting.post_id,
        "url": posting.attachments[0].page_url,
        "files": [item.name for item in stored],
        "gone": [item.name for item in lost],
        "empty": [item.name for item in empty],
        "drm": [item.name for item in locked],
        "not_an_original": [item.name for item in stray],
        "too_large": [item.name for item in oversize],
    }
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / LEDGER).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _empty_reason(visited: list[str], held: list[str]) -> str:
    if not visited:
        return f"collection held: {', '.join(held)}"
    published = f"no attachment published on {', '.join(visited)}"
    return f"{published}; collection held: {', '.join(held)}" if held else published


def _failure_reason(failures: list[str]) -> str | None:
    if not failures:
        return None
    return "collection failures: " + ", ".join(failures)


def _join_reasons(primary: str, warning: str | None) -> str:
    return f"{primary}; {warning}" if warning else primary


def _store(
    destination: Path,
    attachment: boards.Attachment,
    transport: Transport,
    scraper: boards.BoardScraper,
) -> None:
    """원본은 저장소 밖에만 둔다. 이미 받은 원본은 다시 내려받지 않는다."""
    if destination.exists():
        return
    body = boards.request(transport, *boards.endpoint(attachment.url), attachment.referer)
    # 빈 응답·잠긴 응답·부속 파일은 게시판을 가리지 않고 같은 뜻이라 먼저 가린다. 이것을
    # 게시판의 판정보다 뒤에 두면 서울 화면 게시판의 빈 응답이 장부의 `empty`가 아니라
    # 사람이 볼 목록으로 간다.
    boards.reject_unusable(body)
    if isinstance(scraper, boards.VerifiesOriginal):
        # 그다음은 게시판이 내용으로 가린다. 매직 바이트가 없는 원본을 실측한 표식으로 가르는
        # 일(서울 화면 게시판)과, 원본 대신 자기 화면을 200으로 주는 일(인천 옹진군 실측)이
        # 둘 다 여기서 갈린다. 컨테이너 판정보다 먼저 묻는 것은 뒤엣것 때문이다 — 그 화면은
        # 실측하지 않은 형식이 아니라 받을 원본이 없다는 뜻이고, 사람이 볼 목록이 아니라
        # 장부에 남아야 한다.
        scraper.verify(body)
    # 원본으로 받아들일 수 있는지만 확인한다. 무슨 컨테이너였는지는 출처를 만들 때 다시 읽는다.
    boards.container_of(body, html=_html(scraper.published_suffixes))
    _write(destination, body)


def _write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(body)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
