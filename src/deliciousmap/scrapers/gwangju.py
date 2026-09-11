"""광주광역시청 업무추진비 게시판 해석. 2026-09-11 실측한 구조만 따른다.

실측(`docs/validation/issue-51.md`): 목록은 `boardList.do`의 `movePage`로 넘기고 페이지 수는
`전체페이지 : N`에 있다. 게시글은 `boardView.do?boardId=&seq=`(축약형으로 200 확인),
첨부는 `fileDownload.do?...fileSn=`이다. 두 주소 모두 `seq`를 실어 목록에서 첨부가 달린
게시글을 가려낼 수 있다. 응답은 UTF-8이고
Referer·브라우저 위장 없이 200을 준다. 폐기된 `pageId` 파라미터는 붙이지 않는다.
"""

import re
import urllib.parse
from collections.abc import Iterator
from typing import TYPE_CHECKING

from deliciousmap import boards
from deliciousmap.transport import Transport

if TYPE_CHECKING:  # 레지스트리가 이 스크래퍼를 선언한다. 실행 시점에 되짚어 부르지 않는다.
    from deliciousmap.registry.models import Board

ENCODING = "utf-8"
VIEW_PATH = "boardView.do"
FILE_PATH = "fileDownload.do"
BOARD_PARAMETER = "boardId"
PAGE_PARAMETER = "movePage"
POST_PARAMETER = "seq"
FILE_PARAMETER = "fileSn"
# 이 게시판에서 실측한 첨부 형식. 그 밖의 형식이 올라오면 조용히 넘기지 않고 알린다.
PUBLISHED_SUFFIXES = frozenset({".xls", ".xlsx"})
# 목록이 밝히는 전체 페이지 수. 이 값이 없으면 게시판 구조가 바뀐 것이므로 짐작하지 않는다.
TOTAL_PAGES = re.compile(r"전체페이지\s*:\s*([\d,]+)")


class GwangjuCityBoard:
    def __init__(self, board: "Board", transport: Transport) -> None:
        self.list_url, self.params = boards.endpoint(board.url)
        if not boards.is_identifier(self.params.get(BOARD_PARAMETER, "").replace("_", "")):
            raise ValueError("board url must declare boardId")
        self.view_url = urllib.parse.urljoin(self.list_url, VIEW_PATH)
        self.transport = transport

    def postings(self, collected: boards.Collected) -> Iterator[boards.Posting]:
        page = 1
        while True:
            listing = self._read(self.list_url, {**self.params, PAGE_PARAMETER: str(page)})
            for post_id in _posts_with_attachments(listing):
                if not collected(post_id):
                    yield self._posting(post_id)
            if page >= _total_pages(listing):
                return
            page += 1

    def _posting(self, post_id: str) -> boards.Posting:
        params = {BOARD_PARAMETER: self.params[BOARD_PARAMETER], POST_PARAMETER: post_id}
        page_url = boards.address(self.view_url, params)
        attachments = []
        for href, filename in self._read(self.view_url, params).links:
            file_id = _parameter(href, FILE_PATH, FILE_PARAMETER)
            if file_id is None:
                continue
            attachments.append(
                boards.Attachment(
                    post_id=post_id,
                    file_id=file_id,
                    suffix=boards.suffix_of(filename, PUBLISHED_SUFFIXES),
                    url=urllib.parse.urljoin(self.list_url, href),
                    page_url=page_url,
                )
            )
        return boards.Posting(post_id, tuple(attachments))

    def _read(self, url: str, params: dict[str, str]) -> boards.Document:
        return boards.read(boards.request(self.transport, url, params), ENCODING)


def _posts_with_attachments(listing: boards.Document) -> tuple[str, ...]:
    """목록에 첨부 링크가 함께 실린 게시글만 고른다. 본문을 열어 보지 않는다."""
    posts = [_parameter(href, VIEW_PATH, POST_PARAMETER) for href, _ in listing.links]
    filed = {_parameter(href, FILE_PATH, POST_PARAMETER) for href, _ in listing.links}
    return tuple(post for post in dict.fromkeys(posts) if post is not None and post in filed)


def _total_pages(listing: boards.Document) -> int:
    found = TOTAL_PAGES.search(listing.text)
    if found is None:
        raise boards.UnreadableBoard("board listing does not declare its page count")
    return int(found.group(1).replace(",", ""))


def _parameter(href: str, path: str, name: str) -> str | None:
    parts = urllib.parse.urlsplit(href)
    if not parts.path.endswith(path):
        return None
    value = dict(urllib.parse.parse_qsl(parts.query)).get(name, "")
    return value if boards.is_identifier(value) else None
