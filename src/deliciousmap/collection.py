"""게시판 수집. 스크래퍼가 낸 게시글을 저장소 밖 원본과 그 출처 기록으로 바꾼다."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from deliciousmap import boards
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


def collect(target: Target, paths: Paths, transport: Transport) -> FetchOutput:
    """선택한 기관의 게시판을 훑는다. 수집하지 못한 이유는 0건으로 숨기지 않는다."""
    sources: list[SourceRef] = []
    missing: list[MissingOriginal] = []
    unmeasured: list[dict[str, str]] = []
    visited: list[str] = []
    held: list[str] = []
    for organization in target.organizations:
        if organization.hold_reason is not None:
            held.append(f"{organization.slug}={organization.hold_reason}")
            continue
        for board in organization.boards:
            visited.append(f"{organization.slug}/{board.slug}")
            directory = paths.board_dir(target, organization.slug, board.slug)
            unmeasured.extend(_walk(board, directory, transport))
            collected, gone = _ledger(directory)
            sources.extend(_sources(directory, collected, organization.slug, board.slug))
            missing.extend(_missing(gone, organization.slug, board.slug))
    if unmeasured:
        # 게시판을 끝까지 훑은 뒤에 한 번에 알린다. 형식을 하나 만날 때마다 멈추지 않는다.
        raise AdapterFailure(FailureCause.UNSUPPORTED_FORMAT)
    if sources:
        return FetchOutput(sources=tuple(sources), missing=tuple(missing))
    if not visited and not held:
        # 아직 게시판을 선언하지 않은 도시를 수집 완료로 표시하지 않는다.
        raise AdapterFailure(FailureCause.NOT_IMPLEMENTED)
    return FetchOutput(
        sources=(), missing=tuple(missing), empty_reason=_empty_reason(visited, held)
    )


def _walk(board: Board, directory: Path, transport: Transport) -> list[dict[str, str]]:
    """게시판을 훑어 새 게시글의 원본을 내려받고 게시글 단위로 기록한다.

    실측하지 않은 형식은 그 자리에서 멈추지 않고 모아 두었다가 끝에 한 번에 알린다.
    22년치 게시판은 드문 형식이 뒤늦게 나오므로, 하나 만날 때마다 멈추면 그만큼 다시 훑어야 한다.
    """
    collected, gone = _ledger(directory)
    done = set(collected) | set(gone)
    scraper: boards.BoardScraper = board.scraper(board, transport)
    unmeasured: list[dict[str, str]] = []
    try:
        for posting in scraper.postings(lambda post_id: post_id in done):
            stored, lost, empty = [], [], []
            published = scraper.published_suffixes
            unknown = [item for item in posting.attachments if item.suffix not in published]
            unmeasured.extend(_note(item, "format not measured for this board") for item in unknown)
            if unknown:
                # 실측하지 않은 형식이 있는 게시글은 기록하지 않는다. 선언한 뒤 다시 받는다.
                continue
            rejected = []
            for attachment in posting.attachments:
                try:
                    _store(directory / attachment.name, attachment, transport)
                except boards.OriginalGone:
                    # 기관이 더는 내주지 않는 원본이다. 다시 요청해도 같으므로 장부에 남긴다.
                    lost.append(attachment)
                except boards.EmptyOriginal:
                    # 200이지만 받을 것이 없다. 유실과 같은 부류로 장부에 남긴다.
                    empty.append(attachment)
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
            _remember(directory, posting, stored, lost, empty)
    except boards.UnsupportedOriginal:
        raise AdapterFailure(FailureCause.UNSUPPORTED_FORMAT) from None
    except boards.BoardUnavailable:
        raise AdapterFailure(FailureCause.SERVICE_UNAVAILABLE) from None
    except boards.UnreadableBoard:
        raise AdapterFailure(FailureCause.ADAPTER_FAILED) from None
    _report_unmeasured(directory, unmeasured)
    return unmeasured


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


def _sources(
    directory: Path, collected: dict[str, "Collected"], organization: str, board: str
) -> list[SourceRef]:
    """수집 기록 전체를 출처로 옮긴다. 이번 실행에서 새로 받은 것만 세지 않는다.

    컨테이너는 저장한 원본에서 다시 판정한다. 게시판이 붙인 확장자를 그대로 믿지 않는다.
    """
    references = []
    for entry in collected.values():
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
                    container=boards.container_of(body),
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
        except (ValueError, KeyError, TypeError):
            continue
        if files:
            collected[post_id] = Collected(url, files)
        if lost:
            gone[post_id] = Gone(url, lost)
    return collected, gone


def _missing(gone: dict[str, Gone], organization: str, board: str) -> list[MissingOriginal]:
    return [
        MissingOriginal(
            organization=organization, board=board, url=entry.url, filename=name, reason=reason
        )
        for entry in gone.values()
        for name, reason in entry.files
    ]


def _remember(
    directory: Path,
    posting: boards.Posting,
    stored: list[boards.Attachment],
    lost: list[boards.Attachment],
    empty: list[boards.Attachment],
) -> None:
    if not posting.attachments:
        return
    entry = {
        "post_id": posting.post_id,
        "url": posting.attachments[0].page_url,
        "files": [item.name for item in stored],
        "gone": [item.name for item in lost],
        "empty": [item.name for item in empty],
    }
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / LEDGER).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _empty_reason(visited: list[str], held: list[str]) -> str:
    if not visited:
        return f"collection held: {', '.join(held)}"
    published = f"no attachment published on {', '.join(visited)}"
    return f"{published}; collection held: {', '.join(held)}" if held else published


def _store(destination: Path, attachment: boards.Attachment, transport: Transport) -> None:
    """원본은 저장소 밖에만 둔다. 이미 받은 원본은 다시 내려받지 않는다."""
    if destination.exists():
        return
    body = boards.request(transport, *boards.endpoint(attachment.url))
    # 원본으로 받아들일 수 있는지만 확인한다. 무슨 컨테이너였는지는 출처를 만들 때 다시 읽는다.
    boards.container_of(body)
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
