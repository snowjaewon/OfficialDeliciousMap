"""게시판 수집. 스크래퍼가 낸 첨부 참조를 저장소 밖 원본과 그 출처 기록으로 바꾼다."""

import os
import tempfile
from pathlib import Path

from deliciousmap import boards
from deliciousmap.contracts import FetchOutput, SourceRef
from deliciousmap.paths import Paths
from deliciousmap.pipeline import AdapterFailure, FailureCause
from deliciousmap.registry import Target
from deliciousmap.storage import file_digest
from deliciousmap.transport import Transport


def collect(target: Target, paths: Paths, transport: Transport) -> FetchOutput:
    """선택한 기관의 게시판을 훑는다. 수집하지 못한 이유는 0건으로 숨기지 않는다."""
    sources: list[SourceRef] = []
    visited: list[str] = []
    held: list[str] = []
    try:
        for organization in target.organizations:
            if organization.hold_reason is not None:
                held.append(f"{organization.slug}={organization.hold_reason}")
                continue
            for board in organization.boards:
                visited.append(f"{organization.slug}/{board.slug}")
                scraper: boards.BoardScraper = board.scraper(board, transport)
                for attachment in scraper.attachments():
                    sources.append(
                        _store(paths, target, organization.slug, board.slug, attachment, transport)
                    )
    except boards.UnsupportedOriginal:
        raise AdapterFailure(FailureCause.UNSUPPORTED_FORMAT) from None
    except boards.BoardUnavailable:
        raise AdapterFailure(FailureCause.SERVICE_UNAVAILABLE) from None
    except boards.UnreadableBoard:
        raise AdapterFailure(FailureCause.ADAPTER_FAILED) from None
    if sources:
        return FetchOutput(sources=tuple(sources))
    if not visited and not held:
        # 아직 게시판을 선언하지 않은 도시를 수집 완료로 표시하지 않는다.
        raise AdapterFailure(FailureCause.NOT_IMPLEMENTED)
    return FetchOutput(sources=(), empty_reason=_empty_reason(visited, held))


def _empty_reason(visited: list[str], held: list[str]) -> str:
    if not visited:
        return f"collection held: {', '.join(held)}"
    published = f"no attachment published on {', '.join(visited)}"
    return f"{published}; collection held: {', '.join(held)}" if held else published


def _store(
    paths: Paths,
    target: Target,
    organization: str,
    board: str,
    attachment: boards.Attachment,
    transport: Transport,
) -> SourceRef:
    """원본은 저장소 밖에만 둔다. 이미 받은 원본은 다시 내려받지 않는다."""
    destination = paths.original(target, organization, board, attachment.name)
    if not destination.exists():
        body = boards.request(transport, *boards.endpoint(attachment.url))
        boards.require_original(body, attachment.suffix)
        _write(destination, body)
    return SourceRef(
        path=destination,
        source_hash=file_digest(destination),
        organization=organization,
        board=board,
        url=attachment.page_url,
    )


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
