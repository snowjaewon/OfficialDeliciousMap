"""게시판 수집. 스크래퍼가 낸 게시글을 저장소 밖 원본과 그 출처 기록으로 바꾼다."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from deliciousmap import boards
from deliciousmap.contracts import FetchOutput, SourceRef
from deliciousmap.paths import Paths
from deliciousmap.pipeline import AdapterFailure, FailureCause
from deliciousmap.registry import Board, Target
from deliciousmap.storage import file_digest
from deliciousmap.transport import Transport

# 수집을 마친 게시글의 추가형 기록. 원본과 함께 저장소 밖에 두며, 중단한 수집을 이어서
# 할 때 이미 끝낸 게시글의 본문을 다시 열지 않게 한다.
LEDGER = "collected.jsonl"


def collect(target: Target, paths: Paths, transport: Transport) -> FetchOutput:
    """선택한 기관의 게시판을 훑는다. 수집하지 못한 이유는 0건으로 숨기지 않는다."""
    sources: list[SourceRef] = []
    visited: list[str] = []
    held: list[str] = []
    for organization in target.organizations:
        if organization.hold_reason is not None:
            held.append(f"{organization.slug}={organization.hold_reason}")
            continue
        for board in organization.boards:
            visited.append(f"{organization.slug}/{board.slug}")
            directory = paths.board_dir(target, organization.slug, board.slug)
            _walk(board, directory, transport)
            sources.extend(_sources(directory, organization.slug, board.slug))
    if sources:
        return FetchOutput(sources=tuple(sources))
    if not visited and not held:
        # 아직 게시판을 선언하지 않은 도시를 수집 완료로 표시하지 않는다.
        raise AdapterFailure(FailureCause.NOT_IMPLEMENTED)
    return FetchOutput(sources=(), empty_reason=_empty_reason(visited, held))


def _walk(board: Board, directory: Path, transport: Transport) -> None:
    """게시판을 훑어 새 게시글의 원본을 내려받고 게시글 단위로 기록한다."""
    done = _ledger(directory)
    scraper: boards.BoardScraper = board.scraper(board, transport)
    try:
        for posting in scraper.postings(lambda post_id: post_id in done):
            for attachment in posting.attachments:
                _store(directory / attachment.name, attachment, transport)
            # 첨부를 모두 저장한 뒤에만 기록한다. 중간에 멈추면 그 게시글은 다시 수집한다.
            _remember(directory, posting)
    except boards.UnsupportedOriginal:
        raise AdapterFailure(FailureCause.UNSUPPORTED_FORMAT) from None
    except boards.BoardUnavailable:
        raise AdapterFailure(FailureCause.SERVICE_UNAVAILABLE) from None
    except boards.UnreadableBoard:
        raise AdapterFailure(FailureCause.ADAPTER_FAILED) from None


def _sources(directory: Path, organization: str, board: str) -> list[SourceRef]:
    """수집 기록 전체를 출처로 옮긴다. 이번 실행에서 새로 받은 것만 세지 않는다."""
    references = []
    for entry in _ledger(directory).values():
        for name in entry.files:
            path = directory / name
            if not path.exists():
                raise AdapterFailure(FailureCause.IO_ERROR)
            references.append(
                SourceRef(
                    path=path,
                    source_hash=file_digest(path),
                    organization=organization,
                    board=board,
                    url=entry.url,
                )
            )
    return references


@dataclass(frozen=True)
class Collected:
    """수집을 마친 게시글 하나의 기록. 출처 주소와 그때 저장한 원본 이름을 남긴다."""

    url: str
    files: tuple[str, ...]


def _ledger(directory: Path) -> dict[str, Collected]:
    """마지막 줄이 끊긴 기록은 버린다. 그 게시글은 아직 끝내지 못한 것으로 본다."""
    path = directory / LEDGER
    if not path.exists():
        return {}
    entries: dict[str, Collected] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
            entries[str(entry["post_id"])] = Collected(
                str(entry["url"]), tuple(str(name) for name in entry["files"])
            )
        except (ValueError, KeyError, TypeError):
            continue
    return entries


def _remember(directory: Path, posting: boards.Posting) -> None:
    if not posting.attachments:
        return
    entry = {
        "post_id": posting.post_id,
        "url": posting.attachments[0].page_url,
        "files": [item.name for item in posting.attachments],
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
    boards.require_original(body, attachment.suffix)
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
