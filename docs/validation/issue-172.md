# Issue #172 validation — Daejeon expense boards

Validation date: 2026-09-17.  Every request used the project user agent
`OfficialDeliciousMap/0.1 (+https://github.com/snowjaewon/OfficialDeliciousMap)`,
was issued sequentially per host, and no browser user agent was used.  원본 were
received on this PC under `--raw-root C:\Users\설재원\deliciousmap-raw` (outside the
repository) and are not committed.  Every organization's 원본 come from that one root.

The mockup notes (`governdeliciousmap` `docs/대전_업무추진비_공개현황.md`, 2026-08-09,
and its four Daejeon scrapers) were read as knowledge only.  Two of their claims no
longer hold and are corrected below: four districts are *not* below the disclosure
threshold, and 서구 does not serve `FileDown.do`.

## Organizations

6 organizations are registered in `src/deliciousmap/registry/daejeon.py` (#13 counts
대전 as 시청 + 5 자치구).  5 have boards; 1 is held.

| organization | slug | boards | scraper |
| --- | --- | --- | --- |
| 대전광역시 | `daejeon-city` | — | held: `bot_blocked` |
| 대전광역시 동구 | `daejeon-dong` | 2 | `ArticleBoard` |
| 대전광역시 중구 | `daejeon-jung` | 4 | `BbsBoard` |
| 대전광역시 서구 | `daejeon-seo` | 2 | `ZipBbsBoard` |
| 대전광역시 유성구 | `daejeon-yuseong` | 1 | `BbsBoard` |
| 대전광역시 대덕구 | `daejeon-daedeok` | 5 | `DptBoard` |

## robots.txt

Read once per host.  A group names our user agent only through `User-agent: *`.

| host | bytes | `*` group | covers what we request? |
| --- | --- | --- | --- |
| `www.daejeon.go.kr` | 1,139 | `Disallow: /`, `Disallow: /RSA`, `Disallow: /drh/part/board`; `Allow: /english /japanese /chinese /drh` | listing/detail under `/drh/open/…` allowed (longest match `Allow: /drh`); **originals under `/FileUpload/…` disallowed** |
| `www.donggu.go.kr` | 424 | `Allow: /` (named AI crawlers get `Disallow: /`; our agent is not one of them) | no |
| `www.djjunggu.go.kr` | 272 | none — groups are only Yeti/Googlebot/Daum/Daumoa | no (no group applies) |
| `www.seogu.go.kr` | 288 | none — same four crawlers | no |
| `www.yuseong.go.kr` | 287 | none — same four crawlers | no |
| `www.daedeok.go.kr` | 124 | `Allow: /`, `Disallow: /dpt/dpt03/DPT030101_cmmBoardList.do`, `Disallow: /biz/` | no — the expense boards are `/dpt/dpt02/…`, files `/board/binary/…` |

One request to `https://www.daejeon.go.kr/` (the #172 starting point) was made
before the robots file was read; `/` itself is under `Disallow: /`.  No other
disallowed path was requested — in particular `/js/…` (where `fileDownLoad` would be
defined) and `/FileUpload/…` were never fetched.

## Collection hold — 대전광역시 (`bot_blocked`)

The expense menu `/drh/open/drhDataOpen/drhDataOpenBoardList.do?menuSeq=4804&searchCondition2=C08&searchCondition3=D0806`
lists three 공표 items, each a board of postings (`drhDataOpenBoardView.do?boardSeq=…`):

| boardSeq | 공개목록 | measured |
| --- | --- | --- |
| 1186 | 시장, 부시장 | 152 postings, 8 pages; newest `2026년 8월중 업무추진비 사용내역 공개` (2026-09-10) |
| 747 | 3급 이상 실·국장, 3급 사업소장 | not paged further |
| 694 | 4급 사업소장, 과장급이상 | not paged further |

Every attachment on a detail page (`drhDataOpenBoardArticleView.do`, e.g. `articleSeq=14498`
with three PDFs) is `javascript:fileDownLoad('FileUpload/DRH/202607/….pdf', '<name>')`.
The page defines no other download endpoint.  The mockup fetched originals by
appending that first argument to the host, i.e. `/FileUpload/DRH/…`, which only the
`Disallow: /` line matches.  Following #140 (부산 남구·강서구), a robots prohibition is
not worked around, so the city is held (user decision, 2026-09-17).  This holds the
largest Daejeon publisher: the mockup's first-half count was 3,547 of 4,243 records
from the city.

## Disclosure threshold — no district is held

#13 listed 4 districts as `below_threshold` candidates (중구·서구·유성구·대덕구 publish
구청장 only).  Re-measured from each site's own 업무추진비 menu:

| district | boards under the expense menu | department-level? |
| --- | --- | --- |
| 동구 | 단체장 업무추진비 · 5급 이상 업무추진비 | yes |
| 중구 | 단체장(구청장) · 소속기관장(보건소, 효문화관리원, 동) · 과장급 이상 · 부서별 | yes |
| 서구 | 단체장(구청장) · 부서별 | yes |
| 유성구 | 단체장(구청장) only | **no** |
| 대덕구 | 단체장(구청장) · 부구청장 · 국장 · 부서장(실·과장·동장) · 부서별 | yes |

유성구 alone publishes no department unit.  Its 구청장 originals are still collected
rather than held (user decision, 2026-09-17); the gap is recorded here, not hidden.

## Board contracts

### eGov `/bbs` — 중구, 서구, 유성구

`/bbs/BBSMSTR_<n>/list.do?pageIndex=N` → detail `view.do?nttId=<id>` (GET works; the
site itself POSTs a form).  UTF-8.  The page count is the text `페이지 1 / 15`.

- The listing opens a posting through `fn_search_detail('<nttId>')` — on `<a onclick>`
  at 중구·유성구, on `<button onclick>` at 서구 (`_ButtonTable` reads both as links).
- Every attachment cell carries an inline `<script>` defining the download functions;
  the shared listing parser already mutes script text.
- The detail lists files as `href="javascript:fn_egov_downFile('<atchFileId>','<fileSn>')"`
  with text `<name> [197.4 KB] 다운로드`.  중구 detail pages also carry a site-wide
  `FileDown.do` link (사전정보공개목록) that is not an attachment, so only the call is read.
- The name is cut at the **last** `[…]` — a leading `[붙임]` would otherwise lose the
  extension (found in review).
- 유성구 postings before 2021-07 were migrated with ids like `ODYS_MYR_1_164`.  Rejecting
  the underscore dropped 183 of 245 rows from the listing index; the id is now kept
  (underscores become `x` in stored names only).
- Posting with nothing spent: `…(2026년 5월)_없음` (중구), `…(내역없음)` (유성구) have no
  attachment and stay as postings without an original.

**서구 downloads the archive.**  `GET /cmm/fms/FileDown.do?atchFileId=…&fileSn=N` answers
`404` with an error page for every file tried (`FILE_000000045088Tb3` 0 and 1,
`FILE_000000045166Jd2` 0), with no cookie, with a cookie jar after opening the detail,
and with the detail as Referer.  The listing's own archive button
`/cmm/fms/zipDownload.do?atchFileIdStr=<atchFileId>&zipFileName=zipDownload.zip`
answers `200` with a ZIP holding the originals — for multi-file postings (pdf+xlsx)
and for single-file postings alike.  `ZipBbsBoard` takes one archive per `atchFileId`.

| organization | board slug | BBSMSTR | scraper |
| --- | --- | --- | --- |
| 중구 | `expenses-mayor` | `000000000103` | `BbsBoard` |
| 중구 | `expenses-agency` | `000000000611` | `BbsBoard` |
| 중구 | `expenses-director` | `000000000104` | `BbsBoard` |
| 중구 | `expenses-department` | `000000000105` | `BbsBoard` |
| 서구 | `expenses-mayor` | `000000000571` | `ZipBbsBoard` |
| 서구 | `expenses-department` | `000000000263` | `ZipBbsBoard` |
| 유성구 | `expenses-mayor` | `000000000111` | `BbsBoard` |

### 동구 — article CMS

`/dg/kor/article/<code>?pageIndex=N` (`secretBusiness`, `senior`).  The listing is not a
table: `div.notice_list > ul > li`, each field a `<p class="no|subject|date|writer|…">`.
The posting id is only in `article.view('<seq>')`; the detail is `/dg/kor/article/<code>/<seq>`.
Attachments are `/dg/attach/<hash>/<hash>`, each followed by a `/dg/attach/preview/…`
link to the same file that is not counted.  The last page is the `page_end` link
`?pageIndex=129`.

### 대덕구 — dpt CMS

`/dpt/dpt02/DPT0201040<k>_cmmBoardList.do?pageIndex=N` for k = 1…5, detail
`DPT0201040<k>_cmmBoardView.do?boardId=<DPT_…>&ntatcSeq=<10 digits>` (works without
`pageIndex`).  Paging is `onclick="fn_link_page(N)"` on `href="#url"`.  Files are
`/board/binary/<DPT_…>/<n>.<ext>`, printed twice (desktop and mobile blocks) and counted once.

The title link holds a hidden mobile line `<p class="mobile_con">게시일 | 작성자 | 제목</p>`
and the 작성자 column is a **person's name**, not a department.  `_DptTable` mutes that
line so titles carry no name, and `DptBoard` records no department.

`expenses-department` (DPT02010405, 620 postings) was last posted 2023-09-13; the
부서장(실·과장·동장) board carries the department postings since.  It is still declared so the
board is visibly walked with 0 originals rather than silently absent.

## Council postings are filtered

구의회 사무국 spending is mixed into two district boards.  The council is not the
구청's 집행기관, so these are 걸러 낸 게시글 (counted, not collected), matched by `의회`
in the title or writer:

- 동구 `senior`: writer `의회사무국`, `동구 의회사무국`, `대전 동구의회`, or a person's name
  with `(의회사무국)` only in the title — 72 postings, none posted in 2026.
- 서구 `부서별`: `…업무추진비 집행내역(의회사무국)` — 6 postings, one posted 2026-01-06
  (`B000000216116Ye0nU8`).  That posting was collected before the filter existed; its
  ledger line was removed (backup `collected.jsonl.bak-172` beside it) and 서구 re-run.

## An organization page the server breaks — 중구 과장급 291쪽

`BBSMSTR_000000000104/list.do?pageIndex=291` holds 4 postings from 2014–2016.  The server
renders three rows and then, inside the fourth row's title cell (`시책추진업무추진비
건축과(2016-01)`), emits a complete second HTML document (its error/layout page).  The
response has 14 `<tr` and 12 `</tr>`, so the listing parser refuses it
(`board listing row never closed`) and, Daejeon not being failure-tolerant, the whole of
중구 failed with `adapter-failed` after 2,900 of 2,904 director rows.

Daejeon was added to `collection.FAILURE_TOLERANT` next to Seoul and Ulsan (user
decision, 2026-09-17): the board is recorded as a ledger warning and the next board is
still walked.  The 4 lost rows are outside the target year.

## Per-organization collection

Counts come from the committed `data/daejeon/orgs/<slug>/fetch.json` and the raw
folders.  Units: **목록** = postings in the listing index (council postings excluded);
**2026** / **상반기** = listing postings whose 게시일 is in 2026 / 2026-01-01…06-30;
**받은 게시글** = 2026 postings in the ledger; **원본** = stored files
(`FetchOutput.sources`); **원본 없는 게시글** = 2026 postings with no attachment.
The collection selects by 게시일 year (`period.collects`), so 2026 postings are taken
whole; the first-half filter is applied downstream by the spending period.

| 기관 / 게시판 | 목록 | 2026 | 상반기 | 받은 게시글 | 원본 | 확장자 | 매직 바이트(앞 4) | 원본 없는 게시글 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 대전광역시 | — | — | — | — | — | — | — | 수집 보류 `bot_blocked` |
| 동구 `expenses-mayor` | 70 | 7 | 5 | 7 | 7 | xlsx 7 | `504b0304` 7 | 0 |
| 동구 `expenses-director` | 1,218 | 132 | 88 | 131 | 156 | xlsx 155 · xls 1 | `504b0304` 155 · `d0cf11e0` 1 | 1 |
| 중구 `expenses-mayor` | 142 | 9 | 6 | 8 | 8 | xlsx 8 | `504b0304` 8 | 1 |
| 중구 `expenses-agency` | 2,371 | 167 | 110 | 154 | 154 | xlsx 154 | `504b0304` 154 | 13 |
| 중구 `expenses-director` | 2,900 (게시판 총 2,904) | 281 | 192 | 223 | 224 | xlsx 212 · pdf 12 | `504b0304` 212 · `25504446` 12 | 58 |
| 중구 `expenses-department` | 4,763 | 395 | 272 | 237 | 238 | xlsx 235 · pdf 3 | `504b0304` 235 · `25504446` 3 | 158 |
| 서구 `expenses-mayor` | 92 | 9 | 6 | 9 | 9 | zip 9 (안: pdf 9 · xlsx 9) | `504b0304` 9 | 0 |
| 서구 `expenses-department` | 1,593 | 307 | 199 | 307 | 307 | zip 307 (안: xlsx 310 · xls 9) | `504b0304` 307 | 0 |
| 유성구 `expenses-mayor` | 245 | 9 | 6 | 8 | 8 | pdf 8 | `25504446` 8 | 1 |
| 대덕구 `expenses-mayor` | 126 | 9 | 6 | 9 | 9 | pdf 9 | `25504446` 9 | 0 |
| 대덕구 `expenses-deputy` | 68 | 9 | 6 | 9 | 9 | pdf 9 | `25504446` 9 | 0 |
| 대덕구 `expenses-bureau` | 269 | 52 | 38 | 52 | 52 | xlsx 43 · pdf 9 | `504b0304` 43 · `25504446` 9 | 0 |
| 대덕구 `expenses-director` | 1,506 | 276 | 188 | 233 | 236 | xlsx 200 · xls 20 · pdf 16 | `504b0304` 200 · `d0cf11e0` 20 · `25504446` 16 | 43 |
| 대덕구 `expenses-department` | 620 | 0 | 0 | 0 | 0 | — | — | 0 (마지막 글 2023-09-13) |

Ledger totals per organization (`fetch.json` payload):

| 기관 | 원본 | 컨테이너 | 받지 못한 원본 | 받지 않은 게시글 | 걸러 낸 게시글 | 장부 경고 |
| --- | --- | --- | --- | --- | --- | --- |
| 대전광역시 | 0 | — | 0 | 0 | 0 | `collection held: daejeon-city=bot_blocked` |
| 동구 | 163 | ooxml 162 · ole2 1 | 0 | 1,149 | 72 | 없음 |
| 중구 | 624 | ooxml 609 · pdf 15 | 0 | 6,705 | 0 | `collection failures: daejeon-jung/expenses-director=adapter-failed` (291쪽) |
| 서구 | 316 | zip 316 | 0 | 1,369 | 6 | 없음 |
| 유성구 | 8 | pdf 8 | 0 | 236 | 0 | 없음 |
| 대덕구 | 306 | ooxml 243 · ole2 20 · pdf 43 | 0 | 2,243 | 0 | 없음 |

**원본 없는 게시글, checked one by one.**  대덕구 43: every detail page was re-fetched;
none has a `/board/binary/` link and every body says there was nothing to spend
(`집행내역 없음`, `…집행내역이 없어 첨부생략합니다`).  동구 1 (`141003`, `(산내동) 2025년 4분기`):
the detail says `첨부파일이 없습니다`.  유성구 1: `2026년 5월 … 집행내역(내역없음)`.
중구 230: 223 titles already say so (`…_없음`, `_내역없음`, `-해당 없음.`); the other 7
(`B000000225360Qr1cM0`, `B000000226236Se0sT4`, `B000000224569Zs2cC9`,
`B000000225361Gz5jC0`, `B000000226996Gn1xI7`, `B000000228149Bq7nI9`,
`B000000228150Sq6lC5`) were re-fetched — none has an `fn_egov_downFile` call and each
body says `…은 없습니다` or `내역 없음`.
No DRM, empty, gone, or editor side file was met (`missing` is empty everywhere).

## Commands

Git Bash, repository root:

```text
uv run python -m deliciousmap fetch --city daejeon --org daejeon-city --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daejeon --org daejeon-dong --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daejeon --org daejeon-jung --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daejeon --org daejeon-seo --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daejeon --org daejeon-yuseong --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daejeon --org daejeon-daedeok --raw-root /c/Users/설재원/deliciousmap-raw
```

Two background runs were killed by the host for low system memory (the fetch process
itself stayed near 72 MB); each organization was resumed from its ledger.  중구 was run as
a detached process because re-walking ~540 listing pages on every resume did not fit a
10-minute foreground window.

`fetch --city daejeon` was then run once with `--data-root` in a scratch folder (the
committed artifacts stay per organization, as for Busan #140).  It reused every ledger,
downloaded nothing new, and its `fetch.json` equals the sum of the organization files:
1,417 sources (중구 624 · 서구 316 · 대덕구 306 · 동구 163 · 유성구 8), 0 missing,
11,702 받지 않은 게시글 (1,149 + 6,705 + 1,369 + 236 + 2,243), 78 걸러 낸 게시글 (72 + 6),
warning `collection failures: daejeon-jung/expenses-director=adapter-failed`.  The
city's `bot_blocked` hold is not repeated in that warning because sources exist; it is
in `data/daejeon/orgs/daejeon-city/fetch.json`.

## Left for a follow-up

- `parse` and later stages, and the map, are out of scope (#172 제외 범위).
- 대전광역시 stays held until an allowed route to its originals exists.
- 유성구 publishes no department-level board.
