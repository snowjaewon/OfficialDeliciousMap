"""광주광역시청 게시판의 합성 응답. 실제 게시판 HTML 구조만 흉내 내고 실제 게시글은 쓰지 않는다."""

import io
import json
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape

import xlwt

from deliciousmap.registry import Board, City, MapBounds, Organization
from deliciousmap.scrapers.gwangju import GwangjuCityBoard

Value = str | float | datetime

HEADER_A = ("", "사용자", "사용일시", "사용장소", "집행목적", "대상인원수\n(명)", "사용금액\n(원)",
            "결제방법", "비목")  # fmt: skip
HEADER_B = ("", "사용자", "사용일시", "집행목적", "사용금액\n(원)", "대상\n(명)", "사용장소",
            "결제방법", "비목")  # fmt: skip


def sheet_a(
    *rows: tuple[Value, str, str, float, float], total: bool = True
) -> list[tuple[Value, ...]]:
    """사용일시·사용장소·집행목적·인원·금액 순서의 광주시청형 시트. 행 1은 비고 행 2가 제목이다."""
    body = [("", "합성과장", when, place, purpose, people, amount, "카드", "시책")
            for when, place, purpose, people, amount in rows]  # fmt: skip
    title = ("", "□ 합성과 업무추진비 사용내역(26.1~3월)")
    if not total:
        return [(), title, HEADER_A, *body]
    footer = ("", "", "계", "", "", f"{len(rows)}건", sum(row[4] for row in rows), "", "")
    return [(), title, HEADER_A, *body, footer]


def sheet_b(*rows: tuple[Value, str, float, str]) -> list[tuple[Value, ...]]:
    """집행목적·금액·인원·사용장소 순서의 시트. 날짜는 엑셀 날짜 셀로 둔다."""
    body = [("", "합성팀", when, purpose, amount, 4.0, place, "신용카드", "기관")
            for when, purpose, amount, place in rows]  # fmt: skip
    footer = [("", "계", "", f"{len(rows)}건", sum(row[2] for row in rows), "", "", "", "")]
    return [(), ("", "□ 합성팀 업무추진비 사용내역(5월)"), HEADER_B, *body, *footer]


def workbook(*sheets: Sequence[Sequence[Value]]) -> bytes:
    """합성 엑셀 97-2003 통합문서. 실제 원본처럼 빈 시트가 뒤에 붙을 수 있다."""
    book = xlwt.Workbook()
    dated = xlwt.easyxf(num_format_str="yyyy-mm-dd hh:mm")
    for index, rows in enumerate(sheets, start=1):
        sheet = book.add_sheet(f"시트{index}")
        for r, cells in enumerate(rows):
            for c, value in enumerate(cells):
                if isinstance(value, datetime):
                    sheet.write(r, c, value, dated)
                elif value != "":
                    sheet.write(r, c, value)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def header_answer(
    *, spent_on: int = 2, merchant: int = 3, purpose: int = 4, amount: int = 6, header: int = 3
) -> dict[str, object]:
    """광주시청형 시트에 맞는 헤더 매핑 답변. 사용자·인원 열에는 역할을 주지 않는다."""
    return {
        "layout": "table",
        "header_rows": [header],
        "data_start_row": header + 1,
        "columns": [
            {"column": spent_on, "role": "spent_on"},
            {"column": merchant, "role": "merchant"},
            {"column": purpose, "role": "purpose"},
            {"column": amount, "role": "amount_krw"},
        ],
        "amount_unit": "won",
        "year_hint": None,
    }


ANSWER_B = header_answer(spent_on=2, merchant=6, purpose=3, amount=4)


def gemini_reply(
    answer: object,
    *,
    prompt_tokens: int = 1500,
    output_tokens: int = 200,
    finish_reason: str = "STOP",
) -> bytes:
    return json.dumps(
        {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": json.dumps(answer)}]},
                    "finishReason": finish_reason,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": prompt_tokens,
                "candidatesTokenCount": output_tokens,
                "totalTokenCount": prompt_tokens + output_tokens,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


@dataclass
class FakeModel:
    """모델 응답만 대신한다. 요청 구성·예산·검증·캐시는 실제 코드가 한다.

    헤더 매핑 요청에는 `headers`의 답을 차례로, 판별 요청에는 `verdict`로 상호마다 답한다.
    """

    headers: list[object | Exception] = field(default_factory=list)
    verdict: Callable[[str], str] = lambda name: "restaurant"
    classify_failure: Exception | None = None
    # 판별 답에서 상호 표기를 바꿔 돌려줄 때 쓴다(원래 표기 → 답의 표기).
    rename: dict[str, str] = field(default_factory=dict)
    prompts: list[tuple[str, str]] = field(default_factory=list)

    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> bytes:
        request = json.loads(body.decode("utf-8"))
        prompt = request["contents"][0]["parts"][0]["text"]
        schema = request["generationConfig"]["responseSchema"]["properties"]
        if "verdicts" in schema:
            self.prompts.append(("classify", prompt))
            if self.classify_failure is not None:
                raise self.classify_failure
            names = [line.split(". ", 1)[1] for line in prompt.splitlines()]
            return gemini_reply(
                {
                    "verdicts": [
                        {
                            "index": index,
                            "merchant": self.rename.get(name, name),
                            "status": self.verdict(name),
                            "reason": "합성",
                        }
                        for index, name in enumerate(names, start=1)
                    ]
                }
            )
        self.prompts.append(("headermap", prompt))
        answer = self.headers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        # 응답 원문을 그대로 주면 잘린 응답 같은 제공자 응답을 흉내 낼 수 있다.
        return answer if isinstance(answer, bytes) else gemini_reply(answer)

    def calls(self, kind: str) -> list[str]:
        return [prompt for name, prompt in self.prompts if name == kind]


BOARD_URL = "https://www.gwangju.go.kr/boardList.do?boardId=BD_0000000252"
ORIGIN = "https://www.gwangju.go.kr"


@dataclass(frozen=True)
class Post:
    seq: int
    title: str
    department: str
    posted_on: date
    files: tuple[tuple[str, bytes], ...] = ()


def city(*, hold: bool = False) -> City:
    """합성 게시판 하나를 가진 광주 레지스트리. 실제 레지스트리의 게시판 클래스를 그대로 쓴다."""
    return City(
        "gwangju",
        "광주",
        MapBounds(35.0362, 126.6495, 35.2588, 127.0228),
        (
            Organization(
                "gwangju-city",
                "광주광역시청",
                (Board("expenses", BOARD_URL, GwangjuCityBoard),),
                hold_reason="bot_blocked" if hold else None,
            ),
        ),
    )


def list_page(posts: tuple[Post, ...], total: int, pages: int = 1) -> bytes:
    rows = "".join(
        f"""
        <div class="body_row">
          <div class="num"><span class="blind">번호</span>{post.seq}</div>
          <div class="subject">
            <a href="/boardView.do?pageId=&amp;boardId=BD_0000000252&amp;seq={post.seq}"
               data-view="L" data-seq="{post.seq}" title="{escape(post.title)}"
               >{escape(post.title)}</a>
          </div>
          <div class="writer">
            <!-- {escape(post.department)} 원래 부서 -->
            <span class="blind">작성자</span>
            {escape(post.department)}</div>
          <div class="date"><span class="blind">작성일</span>
            {post.posted_on.isoformat()}</div>
          <div class="file"><a href="/fileDownload.do?fileSe=BB&amp;fileSn=1&amp;seq={post.seq}"
             title="파일"><i class="far fa-save"></i></a></div>
        </div>"""
        for post in posts
    )
    return f"""<html><body>
      <p class="total_num">전체게시글 : {total:,} / 전체페이지 : {pages:,}</p>
      <div class="board_list_body">{rows}</div></body></html>""".encode()


def view_page(post: Post) -> bytes:
    items = "".join(
        f"""<li><a href="/fileDownload.do?fileSe=BB&amp;fileKey=BD_0000000252%7C{post.seq}"""
        f"""&amp;fileSn={index}&amp;boardId=BD_0000000252&amp;seq={post.seq}">{escape(name)}</a>
            <a href="/filePreView.do?fileSe=BB&amp;fileKey=BD_0000000252%7C{post.seq}"""
        f"""&amp;fileSn={index}" class="filePreview">미리보기</a></li>"""
        for index, (name, _) in enumerate(post.files, start=1)
    )
    return f"""<html><body><div class="board_view">
      <div class="board_view_head"><h6>{escape(post.title)}</h6></div>
      <div class="board_view_info"><span>작성자 : {escape(post.department)}</span>
        <span>작성일 : {post.posted_on.isoformat()} 14:53</span></div>
      <div class="add_file"><span>파일</span><ul>{items}</ul></div>
      <div class="board_view_body">붙임과 같이 게시합니다.</div>
    </div></body></html>""".encode()


@dataclass
class FakeBoardTransport:
    """게시판 응답만 대신한다. 요청 구성·목록 넘김·원본 링크 해석은 실제 게시판 클래스가 한다."""

    posts: tuple[Post, ...]
    page_size: int = 100
    failures: set[str] = field(default_factory=set)
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes:
        self.requests.append((url, dict(params)))
        path = urllib.parse.urlsplit(url).path
        if path in self.failures:
            raise OSError("synthetic network failure with SECRET details")
        assert url.startswith(ORIGIN)
        if path == "/boardList.do":
            assert params["boardId"] == "BD_0000000252"
            # 실제 게시판처럼 요청한 쪽 크기와 무관하게 쪽마다 고정된 수를 준다고 가정한다.
            page = int(params["movePage"])
            chunk = self.posts[(page - 1) * self.page_size : page * self.page_size]
            pages = max(1, -(-len(self.posts) // self.page_size))
            return list_page(chunk, len(self.posts), pages)
        post = next(item for item in self.posts if str(item.seq) == params["seq"])
        if path == "/boardView.do":
            return view_page(post)
        if path == "/fileDownload.do":
            assert params["fileKey"] == f"BD_0000000252|{post.seq}"
            return post.files[int(params["fileSn"]) - 1][1]
        raise AssertionError(f"unexpected request {url}")

    def downloads(self) -> list[str]:
        return [
            f"{params['seq']}-{params['fileSn']}"
            for url, params in self.requests
            if url.endswith("/fileDownload.do")
        ]
