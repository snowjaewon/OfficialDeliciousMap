"""광주 광산구청 사전정보공표 해석. 2026-09-13 실측한 구조만 따른다.

실측(`docs/validation/issue-97.md`): 이 구는 게시판 HTML을 주지 않는다. 진입 화면
`contentsView.do?pageId=`이 세션 쿠키와 1회용 토큰을 내주고, 목록·본문은 그 토큰을 실은
`POST getInfoOpenList.do`·`POST getInfoOpenData.do`가 JSON으로 답한다. 토큰 없이 부르면 403이다.
목록은 `dataMap.list`에 `detailSn`·`detailNm`·`deptNm`·`regDt`를, 본문은 `dataMap.fileList`에
`fileSn`·`fileExtsn`·`fileUrl`을 담는다. 전체 쪽 수는 `dataMap.pageCnt`에 있다.
첨부 주소의 `fileSe`는 시청의 `BB`가 아니라 `IO`다. 응답은 UTF-8이고 브라우저 위장 없이 200을 준다.
"""

import json
import re
import urllib.parse
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from deliciousmap import boards
from deliciousmap.transport import SessionTransport, query

if TYPE_CHECKING:  # 레지스트리가 이 스크래퍼를 선언한다. 실행 시점에 되짚어 부르지 않는다.
    from deliciousmap.registry.models import Board

ENCODING = "utf-8"
LIST_PATH = "getInfoOpenList.do"
VIEW_PATH = "getInfoOpenData.do"
CATEGORY_PARAMETER = "infoOpenSn"
PAGE_PARAMETER = "movePage"
SIZE_PARAMETER = "recordCnt"
POST_PARAMETER = "detailSn"
# 진입 화면이 밝히는 1회용 토큰과 그 토큰을 실어 보낼 헤더 이름. 값은 화면마다 새로 받는다.
TOKEN = re.compile(r'name="_?csrf"\s+content="([0-9a-fA-F-]{16,64})"')
TOKEN_HEADER = "X-CSRF-TOKEN"
FORM_TYPE = "application/x-www-form-urlencoded; charset=UTF-8"
# 목록·본문 요청에 함께 실어야 답이 채워지는 값들. 빼면 빈 목록이 온다(실측).
LIST_PARAMETERS = {"infoOpen": "D", "infoOpenType": "S", "infoOpenCtgryTy": "S"}
VIEW_PARAMETERS = {"infoOpen": "D"}
CATEGORY_UPPER = "infoOpenCtgryUpper"
# 한 번에 받아 올 게시글 수. 실측에서 100까지 그대로 답했다. 더 키우지 않는다.
PAGE_SIZE = 100
# 이 게시판에서 실측한 첨부 형식. 2026년치 190건을 모두 내려받아 매직 바이트까지 확인했다.
PUBLISHED_SUFFIXES = frozenset({".xls", ".xlsx", ".xlsm", ".hwp", ".hwpx", ".pdf"})
POSTED = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


class GwangsanInfoOpenBoard:
    """광산구 사전정보공표 항목 하나. 게시판 주소가 밝힌 진입 화면과 분류만 쓴다."""

    published_suffixes = PUBLISHED_SUFFIXES

    def __init__(self, board: "Board", transport: SessionTransport) -> None:
        self.entry_url, self.params = boards.endpoint(board.url)
        category = self.params.get(CATEGORY_PARAMETER, "")
        if not boards.is_identifier(category) or not boards.is_identifier(
            self.params.get(CATEGORY_UPPER, "")
        ):
            raise ValueError("board url must declare infoOpenSn and infoOpenCtgryUpper")
        self.category = category
        self.list_url = urllib.parse.urljoin(self.entry_url, LIST_PATH)
        self.view_url = urllib.parse.urljoin(self.entry_url, VIEW_PATH)
        self.transport = transport
        self._token = ""

    def postings(self, skipped: boards.Skipped) -> Iterator[boards.Posting]:
        page = 1
        while True:
            answer = self._call(self.list_url, self._listing_form(page))
            data = _mapping(answer, "dataMap")
            for row in _rows(data):
                # 넘기기로 한 게시글은 본문을 열지 않고 목록에서 읽은 값만 낸다.
                yield (row.posting(()) if skipped(row.post_id, row.posted) else self._posting(row))
            if page >= _total_pages(data):
                return
            page += 1

    def _posting(self, row: "_Row") -> boards.Posting:
        form = {**VIEW_PARAMETERS, "sn": self.category, POST_PARAMETER: row.post_id}
        page_url = boards.address(self.view_url, form)
        data = _mapping(self._call(self.view_url, form), "dataMap")
        attachments = tuple(
            boards.Attachment(
                post_id=row.post_id,
                file_id=file_id,
                suffix=suffix,
                url=urllib.parse.urljoin(self.entry_url, href),
                page_url=page_url,
            )
            for file_id, suffix, href in _files(data)
        )
        return row.posting(attachments)

    def _listing_form(self, page: int) -> dict[str, str]:
        return {
            **LIST_PARAMETERS,
            CATEGORY_UPPER: self.params[CATEGORY_UPPER],
            CATEGORY_PARAMETER: self.category,
            SIZE_PARAMETER: str(PAGE_SIZE),
            PAGE_PARAMETER: str(page),
        }

    def _call(self, url: str, form: Mapping[str, str]) -> dict[str, object]:
        """토큰을 실어 한 번 부른다. 토큰이 없거나 만료됐으면 진입 화면에서 다시 받는다."""
        for attempt in (1, 2):
            if not self._token:
                self._token = self._enter()
            headers = {**boards.HEADERS, TOKEN_HEADER: self._token, "Content-Type": FORM_TYPE}
            try:
                body = self.transport.post(url, query(form).encode(ENCODING), headers)
            except boards.OriginalGone:
                raise
            except Exception:
                if attempt == 2:
                    raise boards.BoardUnavailable("board request failed") from None
                # 세션이 끊겼을 수 있다. 토큰을 버리고 진입 화면부터 한 번만 다시 한다.
                self._token = ""
                continue
            return _document(body)
        raise AssertionError("unreachable")

    def _enter(self) -> str:
        """진입 화면에서 세션과 1회용 토큰을 받는다. 쿠키는 요청 경계가 이어서 든다."""
        body = boards.request(self.transport, self.entry_url, self.params)
        found = TOKEN.search(body.decode(ENCODING, errors="replace"))
        if found is None:
            raise boards.UnreadableBoard("board entry page no longer declares a request token")
        return found.group(1)


@dataclass(frozen=True)
class _Row:
    """목록 한 줄. 게시글 번호·게시일·제목·부서만 남긴다."""

    post_id: str
    posted: date
    title: str
    department: str

    def posting(self, attachments: tuple[boards.Attachment, ...]) -> boards.Posting:
        return boards.Posting(self.post_id, attachments, self.posted, self.title, self.department)


def _document(body: bytes) -> dict[str, object]:
    try:
        answer = json.loads(body.decode(ENCODING))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise boards.UnreadableBoard(
            "board answered with something other than the measured JSON"
        ) from None
    if not isinstance(answer, dict):
        raise boards.UnreadableBoard("board answer is not the measured object")
    return answer


def _mapping(answer: Mapping[str, object], name: str) -> Mapping[str, object]:
    data = answer.get(name)
    if not isinstance(data, Mapping):
        raise boards.UnreadableBoard("board answer does not carry the measured payload")
    return data


def _rows(data: Mapping[str, object]) -> tuple[_Row, ...]:
    listed = data.get("list")
    if not isinstance(listed, list):
        raise boards.UnreadableBoard("board answer does not carry a listing")
    rows = []
    for item in listed:
        if not isinstance(item, Mapping):
            raise boards.UnreadableBoard("board listing row is not the measured object")
        post_id = _identifier(item.get(POST_PARAMETER))
        rows.append(
            _Row(
                post_id,
                _posted_on(item.get("regDt")),
                _text(item.get("detailNm")),
                _text(item.get("deptNm")),
            )  # fmt: skip
        )
    seen: dict[str, _Row] = {}
    for row in rows:
        seen.setdefault(row.post_id, row)
    return tuple(seen.values())


def _files(data: Mapping[str, object]) -> tuple[tuple[str, str, str], ...]:
    listed = data.get("fileList")
    if not isinstance(listed, list):
        raise boards.UnreadableBoard("board answer does not carry an attachment list")
    files = []
    for item in listed:
        if not isinstance(item, Mapping):
            raise boards.UnreadableBoard("board attachment is not the measured object")
        href = _text(item.get("fileUrl"))
        if not href:
            raise boards.UnreadableBoard("board attachment does not declare its address")
        suffix = _text(item.get("fileExtsn")).lower()
        files.append((_identifier(item.get("fileSn")), f".{suffix}" if suffix else "", href))
    return tuple(files)


def _total_pages(data: Mapping[str, object]) -> int:
    """목록이 밝히는 전체 쪽 수. 이 값이 없으면 게시판이 바뀐 것이므로 짐작하지 않는다."""
    pages = data.get("pageCnt")
    if not isinstance(pages, (int, float)) or isinstance(pages, bool) or pages < 1:
        raise boards.UnreadableBoard("board answer does not declare its page count")
    return int(pages)


def _identifier(value: object) -> str:
    """주소와 경로에 그대로 쓸 식별자. 게시판이 숫자로 주므로 문자열로 맞춘다."""
    text = str(value) if isinstance(value, int) and not isinstance(value, bool) else _text(value)
    if not boards.is_identifier(text):
        raise boards.UnreadableBoard("board supplied an unusable identifier")
    return text


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _posted_on(value: object) -> date:
    """줄이 밝힌 게시일. 모양만 날짜인 값은 날짜로 받아들이지 않는다."""
    day = POSTED.search(value) if isinstance(value, str) else None
    if day is None:
        raise boards.UnreadableBoard("board listing row does not declare its posting date")
    try:
        return date(*(int(part) for part in day.groups()))
    except ValueError:
        raise boards.UnreadableBoard(
            "board listing row declares an impossible posting date"
        ) from None
