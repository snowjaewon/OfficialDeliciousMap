# Issue #140 validation — Busan expense boards

Validation date: 2026-09-14.  Every request used the project user agent
`OfficialDeliciousMap/0.1 (+https://github.com/snowjaewon/OfficialDeliciousMap)`,
was issued sequentially, and kept the project request interval.  No browser user
agent was used and no block was worked around.  HTML responses and 원본 were kept
outside the repository under `--raw-root`; no 원본, `dist/`, or personal data is
committed here.

The starting point was the 2026-09-09 reconnaissance on the
`research/seoul-busan-boards` branch.  Everything below was re-measured; the
places where the reconnaissance no longer holds are called out explicitly.

## Organizations

17 organizations are registered in `src/deliciousmap/registry/busan.py`.  13 have
boards; 4 are held with a reason from `Organization.hold_reason`.

| organization | slug | boards | scraper |
| --- | --- | --- | --- |
| 부산광역시 | `busan-city` | 2 | `CityBoard` |
| 부산광역시 중구 | `busan-jung` | 1 | `MixedRfc3Board` |
| 부산광역시 서구 | `busan-seo` | 1 | `Rfc3Board` |
| 부산광역시 동구 | `busan-dong` | 1 | `Rfc3Board` |
| 부산광역시 영도구 | `busan-yeongdo` | — | held: `bot_blocked` |
| 부산광역시 부산진구 | `busan-busanjin` | 1 | `Rfc3Board` |
| 부산광역시 동래구 | `busan-dongnae` | 1 | `Rfc3Board` |
| 부산광역시 남구 | `busan-nam` | — | held: `bot_blocked` |
| 부산광역시 북구 | `busan-buk` | 1 | `Rfc3Board` |
| 부산광역시 해운대구 | `busan-haeundae` | 1 | `MixedRfc3Board` |
| 부산광역시 사하구 | `busan-saha` | — | held: `board_lost` |
| 부산광역시 금정구 | `busan-geumjeong` | 1 | `Rfc3Board` |
| 부산광역시 강서구 | `busan-gangseo` | — | held: `bot_blocked` |
| 부산광역시 연제구 | `busan-yeonje` | 1 | `EgovPortalBoard` |
| 부산광역시 수영구 | `busan-suyeong` | 1 | `MixedRfc3Board` |
| 부산광역시 사상구 | `busan-sasang` | 1 | `Rfc3Board` |
| 부산광역시 기장군 | `busan-gijang` | 1 | `GijangBoard` |

## robots.txt

Read once per host with the project user agent.  RFC 9309 gives the
`User-agent: *` group to any crawler that is not named.

| host | `*` group | covers the board path? |
| --- | --- | --- |
| `www.busan.go.kr` | **unreadable** — `/robots.txt` answers `401` with an EUC-KR security page naming our source IP | RFC 9309 §2.3.1.3: a 4xx makes robots unavailable, so access is permitted |
| `www.yeongdo.go.kr` | **unreadable** — `200` but the body is the same security page, not a robots file | unavailable, so permitted |
| `www.bsnamgu.go.kr` | `User-agent: *` / `Disallow: /` (only `Yeti` is allowed) | **yes — prohibited** |
| `www.bsgangseo.go.kr` | `User-agent:*` / `Disallow:/` (only `Googlebot` is narrowed) | **yes — prohibited** |
| `www.saha.go.kr` | `Disallow: /*bbs*` | **yes** — `/portal/bbs/list.do` matches |
| `www.bsjunggu.go.kr` | `Disallow: /*/board/SynapViewer.junggu` | no — only the viewer, which is never requested |
| `www.suyeong.go.kr` | `Disallow: /*/board/SynapViewer.suyeong` | no — same |
| `www.geumjeong.go.kr` | `Allow: /`, `Disallow: /search/search.jsp` | no |
| `www.busanjin.go.kr`, `www.dongnae.go.kr` | `Allow: /` (the `/board/` Disallow is in the `Googlebot` group) | no |
| `www.haeundae.go.kr` | `Disallow: /cms/ /copyright/ … /health/board/list.do /reserve/board/list.do` | no — the expense board is `/board/list.do` |
| `www.yeonje.go.kr` | `Allow: /portal/`, `Disallow: /intro` (every `/…/bbs` Disallow is in the `Googlebot` group) | no |
| `www.bsseogu.go.kr`, `www.bsdonggu.go.kr`, `www.sasang.go.kr`, `www.gijang.go.kr` | no `*` group at all | no — default allow |
| `www.bsbukgu.go.kr` | `/robots.txt` → `404` | no |

## Collection holds

The four values of `Organization.hold_reason` are the only thing recorded; none
of these was worked around.

**남구 (`bot_blocked`)** — `https://www.bsnamgu.go.kr/robots.txt` (54 bytes):

```
User-agent: *
Disallow: /
User-agent: Yeti
Allow: /
```

Our user agent matches only the `*` group, and `Disallow: /` covers
`/board/list.namgu`.  Only the robots file was fetched on this host; the board
listing was never requested.

**강서구 (`bot_blocked`)** — `https://www.bsgangseo.go.kr/robots.txt` (69 bytes):

```
User-agent:*
Disallow:/

User-agent: Googlebot
Disallow: */board/
```

Same reading: `Googlebot` is given a *narrower* restriction, everybody else is
denied outright.  Only the robots file was fetched.

This also settles the reconnaissance's Fasoo DRM note for 강서구 — the question
does not arise, because the board may not be crawled at all.

**영도구 (`bot_blocked`)** — the listing is served, but the detail pages are not.
The host runs the same security appliance as 부산시청: `/robots.txt` answers with
an IP block page instead of a robots file.  Measured on the 2026 first-half
postings we would actually collect:

| probe | result |
| --- | --- |
| listing `00333.web?gcode=1037` | `200`, 130,435 bytes, 496 pages |
| 10 first-half detail pages, 2 s apart | **3 × 200, 7 × 400** |
| 10 newest detail pages, 1 s apart, one retry each | 4 first-try 200, 1 retry 200, **5 hard failures** |
| the 5 hard failures again after a 45 s pause at 8 s intervals | **1 × 200, 4 × 400** |

The failures are sticky per posting and do not recover with a slower rate or a
retry, so this is not the transient outage that `REQUEST_INTERVAL` and
`REQUEST_ATTEMPTS` already handle.  A separate observation: a download that
400s on its own succeeds once a cookie jar is carried, so the host is gating on
something we would have to imitate.  Bypassing bot blocking is out of scope
(#140 제외 범위), so 영도구 is held.

What it costs: 496 + 14 listing pages, 217 + 6 first-half postings, ~72% of them
carrying an `.xls`/`.xlsx` original.  Its download endpoint is keyed on the
URL-encoded original filename (`/board/download.do?gcode=&name=…`) with no file
id, so a future attempt must capture the filename verbatim from each detail page.

**사하구 (`board_lost`)** — the reconnaissance's entry point
`portal/bbs/list.do?ptIdx=29` is inside `Disallow: /*bbs*`, so it was not
re-requested.  The menu page that robots does permit,
`https://www.saha.go.kr/portal/contents.do?mId=0302070000`, answers `200` with
breadcrumb 정보공개 > 행정정보공개 > 업무추진비 공개 and `<h2>업무추진비 공개</h2>`,
but `<div id="conts">` holds exactly one element:

```html
<div id="conts">
<div class="taC">
	<img src="/common/images/etc/ready.jpg" alt="페이지가 준비중입니다. …"/>
</div>
</div>
```

No table, no list, no link to expense data.  Every 업무추진비 link on the page
points back at this same placeholder.  There is no reachable board for 사하구
under robots, so it stays held until a person finds a new address in a browser.

## Board contracts

### rfc3 family — 9 organizations, one scraper

`/board/list.<사이트키>?boardId=…&startPage=N` → detail
`view.<사이트키>?boardId=…&dataSid=…` → file
`download.<사이트키>?boardId=…&dataSid=…&fileSid=…`.  UTF-8.  Attachments are on
the detail page only, so `Rfc3Board` opens a detail only for postings this
collection will actually take.

The site key is read from the listing path, never declared twice: it differs
from the domain on 해운대구 (`do`) and 남구 (`namgu`).

| organization | listing URL | site key | pages | rows/page | dedicated? |
| --- | --- | --- | --- | --- | --- |
| 중구 | `https://www.bsjunggu.go.kr/board/list.junggu?boardId=BBS_0000018` | `junggu` | 1,101 | 10 | **mixed** — 404/610 measured rows are expense posts |
| 서구 | `https://www.bsseogu.go.kr/board/list.bsseogu?boardId=BBS_0000151` | `bsseogu` | 106 | 10 | yes |
| 동구 | `https://www.bsdonggu.go.kr/board/list.donggu?boardId=BBS_0000254` | `donggu` | 79 | 10 | yes |
| 부산진구 | `https://www.busanjin.go.kr/board/list.busanjin?boardId=BBS_0000023&menuCd=DOM_000000109001003000&contentsSid=276` | `busanjin` | 485 | 10 | yes |
| 동래구 | `https://www.dongnae.go.kr/board/list.dongnae?boardId=BBS_0000200` | `dongnae` | 178 | **15** | yes |
| 북구 | `https://www.bsbukgu.go.kr/board/list.bsbukgu?boardId=BBS_0000030` | `bsbukgu` | 327 | 10 | yes |
| 해운대구 | `https://www.haeundae.go.kr/board/list.do?boardId=BBS_0000004` | `do` | 451 | 10 | **mixed** — 340/350 measured rows |
| 금정구 | `https://www.geumjeong.go.kr/board/list.geumj?boardId=BBS_0000331` | `geumj` | 637 | 10 | yes |
| 수영구 | `https://www.suyeong.go.kr/board/list.suyeong?boardId=BBS_0000116` | `suyeong` | 933 | 10 | **mixed** — 333/740 measured rows |
| 사상구 | `https://www.sasang.go.kr/board/list.sasang?boardId=BBS_0000175` | `sasang` | 379 | 10 | yes |

부산진구 answers `403 - BAD REQUEST -` (a WAF, `Connection: Close`) when
`menuCd` is missing, so the query condition is part of the registered URL.

### Where the family is not uniform

The reconnaissance recorded one shape for the family.  Nine boards actually
disagree in five ways, and each one is a defect if assumed away:

1. **Posting-date text** has four forms: `2026-09-14` (중구·수영구·사상구),
   `2026.08.18` (동구·동래구·해운대구), `26.09.14` (부산진구·북구·금정구), and
   `2026. 09. 02` with spaces (서구).  `listing.DATE_RE` now tolerates whitespace
   around the separator and `SHORT_DATE_RE` reads the two-digit year.
2. **Column order is not stable** — nine boards, seven distinct header sets, and
   the 제목 column always precedes the 게시일 column.  Reading the date out of the
   whole row text therefore reads a date out of the title.  `listing.posted_of`
   prefers a cell that is *only* a date and falls back to the row.
3. **Two download anchors can point at the same file** (동래구, 해운대구, whose
   second anchor reads `다운받기`/`내려받기`).  Counting anchors doubles the
   attachment count and downloads each original twice.  `Rfc3Board` counts
   `fileSid`.
4. **The declared filename is not uniformly `<name>.<ext>(<size> kb)`** — 동래구
   omits the size entirely, and three hosts insert a space before `(`.  The
   period inside the name also looks like an extension
   (`업무추진비집행내역(개금2동-2026.8.).xlsx` → a leading scan yields `.8`, which
   would file a perfectly good XLSX as an unmeasured format).  The name is read
   whole and only its final extension is used.
5. **Download hrefs carry a host-specific path prefix** on three sites
   (`/council/board/…`, `/tour/board/…`, `/library/board/…`).  The prefix is
   cosmetic — `/board/download.<key>` returns byte-identical files — and the
   scraper normalizes to the listing's own directory.

동래구 additionally inlines `console.log('<제목>')` inside the 제목 cell, so the
shared listing parser now drops `<script>`/`<style>` text; without that the title
appears twice in the cell text.

### Mixed boards — 중구, 수영구, 해운대구

중구 and 수영구 are 정보공개 통합 게시판, not expense boards; 해운대구 is a
전 부서 통합 게시판 with a smaller intruder.  Measured page 1: 중구 9/10 and
수영구 6/10 rows are expense posts; 해운대구 is 340/350 over its 2026 range, the
intruder being a recurring `보건소 수의계약내역, 신용카드 사용내역 알림` (9 postings,
13 originals — removed from the ledger once the filter was declared).  Non-expense examples that would otherwise be
downloaded: `공개공지 관리실태 점검결과(2025년)`, `2026년 8월 이륜자동차 등록현황`,
`2026년 상반기 외국인 현황`, `석면해체․제거작업 공개`.

The filter lives on the scraper class and the registry picks the class, the same way
울산's `NamguBoard` carries its measured page size.  That keeps the per-organization
choice in the registry (AGENTS.md: 기관별 차이는 레지스트리 값) while the pattern that
implements it stays next to the board it was measured on.

The filter is `추진비`, not `업무추진비`: 중구 has two postings spelled
`…과장급이상무추진비사용내역(2026.8.)` with the `업` dropped, and a whole-word
filter loses them.  None of the measured non-expense titles contains `추진비`.
Note that `2026년 상반기 외국인 현황` would match a period-first filter — the
subject test has to come before the period test.

### 부산시청 — `ghopen12`

`https://www.busan.go.kr/ghopen12/list?schBizNo=<n>&curPage=N` → detail
`/ghopen12/view?schCommand=Expense&schIndx=…` → file
`/comm/getFile?srvcId=OPENGOV&upperNo=<schIndx>&fileTy=ATTACH&fileNo=<n>`.

| `schBizNo` | board | posts | pages | registered |
| --- | --- | --- | --- | --- |
| 46 | 시장, 부시장 업무추진비 사용내역 | 108 | 11 | yes |
| 45 | 실국본부장, 4급이상 공무원이 장인 부서 및 기관의 업무추진비 | 10,600 | 1,060 | yes |
| 199 | 지방공기업 임원 등 업무추진비 사용내역 | 1 | 1 | **no** |

**Why 199 is excluded.**  Its 공표방법 is `링크`, not `자료첨부`.  It holds exactly
one posting (`schIndx=107`, 공표일 **2014-09-23**, nothing since) whose body is a
table of 바로가기 links to five legally separate 지방공기업 — 부산도시공사
(`bmc.busan.kr`), 부산시설공단 (`www.bisco.or.kr`), 부산환경공단
(`www.beco.or.kr`), 부산교통공사 (`www.humetro.busan.kr`), 부산관광공사
(`bto.or.kr`) — each publishing its own executives' 업무추진비 on its own site.
There is no 부산광역시청 spending and no downloadable original on that board.

Two things this board does that a naive reader gets wrong:

- `fileNo` does **not** start at 1.  Posting 21481 publishes `fileNo=2` and
  `fileNo=3` with no `fileNo=1`, so the number is read from the detail page.
- The listing href is malformed (`…&curPage=1&&amp;schBizNo=46`, a doubled `&`)
  and the 공표부서 cell contains a raw unescaped `>` (`행정자치국 > 총무과`).
  Both are tolerated by the lenient HTML parser.

### 연제구 — egov portal

`https://www.yeonje.go.kr/portal/bbs/list.do?ptIdx=32&mId=0401090000&page=N`.
395 pages, 3,942 postings.  `mId` is mandatory — without it the listing answers
`400` (`alert('잘못된 요청 입니다.')`) and the detail answers `500`.  POST is
refused with `403` by a CSRF check; the GET form is what the site itself uses and
is what the scraper sends.  No CSRF token was harvested.

Neither the posting id nor the page count is in an href — both are only in
script calls, `goTo.view('list','131707','32','0401090000')` and `goPage(395)`.
Attachments come from `fn_egov_downFile('<atchFileId>','<fileSn>')` →
`/cmm/fms/FileDown.do`.  `fileSn` here is a 32-hex token, not the small integer
the eGov default uses, so it is carried from the page and never synthesized.

### 기장군 — the listing *is* the data

`https://www.gijang.go.kr/board/list.gijang?boardId=BBS_0000147&menuCd=DOM_000000101002014000&paging=ok`.
One `<tr>` is one spending line; the columns are 부서 · 사용자 · 사용일자(일시) ·
사용장소(가맹점) · 사용목적(내역) · 사용금액(원) · 대상인원(명) · 사용방법 · 연도 ·
월.  There are zero `<a>` elements inside `<tbody>` on any page: no detail page,
no attachment.  Extraction from this table is out of scope for #140, so the
correct 원본 count for 기장군 is 0 — but the rows are still walked so that the
board is recorded as visited rather than silently empty.

Two corrections to the reconnaissance, both material:

- **`categoryCode1` is a department filter, not a year filter.**  It is a 41-option
  `<select … title="부서">`; `categoryCode1=000` is 행정지원과(군수).  The
  reconnaissance URL carried it, which showed 530 rows / 53 pages.  Without it the
  board declares `총게시물 3283건 ｜ 페이지 : 1/329`.  The registered URL drops it.
- **The 연도/월 columns are editorial, not derived from 사용일자.**  64 of 3,215 rows
  disagree — e.g. `2026. 8. 14.` filed under 2026/6월, `2026.5.8.` filed under
  2025/5월.  Filtering server-side on `categoryCode2`/`categoryCode3` would drop
  5 first-half rows and admit 3 that do not belong, so the period is decided from
  the parsed 사용일자 instead.

사용일자 is free text with 97 distinct shapes over 3,283 rows — `2026. 8. 20.`
(780), `2026.06.28.` (663), `2026. 08. 20.` (404), `2026-09-14` (164),
`20260628` (131), empty (49), plus `26.6.11.`, `6.27.(금)`, `202503222`.  The
scraper reads the compact 8-digit form and the separator forms and leaves the
rest undeclared rather than guessing.

## Title period notation

`period.DECLARATION` previously read only the notations measured on the 광주시청
board.  One notation had to be added for Busan, and it is not cosmetic.

**Added: `제N분기`.**  부산시청 board 45 publishes `2026년 제1분기`, `2026년 제2분기`
(4 measured postings, e.g. `schIndx=21636`, `21635`, `21541`, `21506`).  Without
it, `제` blocked every quarter alternative and the title fell through to the
year-only reading — so `2026년 제3분기` was being read as *the whole of 2026* and
would have entered the first-half target set.  `tests/test_period.py` pins both
`제1분기` → 1–3월 and `제3분기` → 7–9월.

Notations that were already read correctly and were re-confirmed on Busan titles:

| notation | measured on | reading |
| --- | --- | --- |
| `2026년 2분기` | every board | 4–6월 |
| `2026년 8월` | 부산진구, 서구, 해운대구 | 8월 |
| `2026년도 2분기` | 부산시청 45 (`schIndx=21927`) | 4–6월 |
| `2026년 1, 2월` | 영도구 (`idx=331576`) | 1–2월 |
| `2026년 3~7월` | 영도구 (`idx=333662`) | 3–7월 |
| `2026년 4~5월`, `2026년 4월 ~ 6월` | 북구 | 4–5월, 4–6월 |
| `업무추진비 사용내역(2026년 6월)` | 사상구 | 6월 |
| `(2026.6월)`, `(2026. 3월)` | 사상구, 중구 | 6월, 3월 |

Titles that stay undeclared on purpose:

- `회계장비담당관 2분기 시책업무추진비 사용내역` (부산시청 45, `schIndx=21740`) has
  no year at all.  The year is only inferable from 공표일, which is a different
  fact from the spending period, so it is left undeclared.
- `2026년 재무과 8월 업무추진비 집행내역` (영도구, `idx=333723`) puts the department
  between the year and the month.  It reads as year-only, which keeps it in the
  year but does not claim a month it did not state.

`period.exclusion` counts these as `undeclared_in_year`; that counter is the
watch point for the next issue, not something to be silenced here.

## DRM

Fasoo DRM attachments are `.xlsx` by name and
`\x9b DRMONE  This Document is encrypted and protected by Fasoo DRM` by content.
They are not an unmeasured format — declaring the extension does not make them
readable — so `boards.ProtectedOriginal` separates them and the collection
ledger records them as `drm`, alongside `gone` and `empty`.  Unlocked
attachments on the same posting are still taken, and one DRM sample never holds
a whole organization.

Measured on 부산시청 before the run, 8 attachments from 8 different postings across
both boards and three quarters: **3 DRM, 5 real OOXML** (each of the 5 opens as a
zip with `xl/workbook.xml`).  That is the sample, not a rate; the per-organization
counts below come from the actual collection.

Two traps: `Content-Type` is `application/octet-stream` for both kinds, and the
filename markers some departments add (`_해제`, `★`) do not track the actual
content.  Only the magic bytes decide.

## A format the reconnaissance never saw: HWPML

부산 동구 publishes 한글 XML under `.hwp` and `.hwpx` names — a UTF-8 BOM followed
by `<?xml …?><HWPML Style="embed" …>`.  It is neither OLE2 nor a zip, so
`container_of` refused it and the first 동구 run failed with
`cause=unsupported-format` and 28 entries in `unmeasured.jsonl`.

This is a real original, not a board error, so `hwpml` is now a container and the
BOM is stripped before matching (which also fixes BOM-prefixed SpreadsheetML).
Reading HWPML tables is out of scope for #140; the run records what was received.

## Collection behaviour changed for every city

#132 turned on "continue to the next board after a failure" for Ulsan only, by
comparing `target.city.slug`.  #140 removes the city name from that decision.
Busan spreads 17 organizations over 16 hosts, so one public server dropping is
ordinary, and a city name says nothing about whether a board is reachable.

What continues is only `service-unavailable` — a failure that a later request can
answer differently.  `adapter-failed` (the listing no longer parses) and
`unsupported-format` mean *our scraper* is wrong, not the board; continuing past
those would make every later run collect the same short amount from the same
place, so they are still raised where they happen.  That also keeps the 광주
guarantees intact: a listing that lost its page count still fails loudly rather
than quietly collecting page 1 of N.

Walking every board and still collecting nothing, when the cause was a failure,
is reported as a failure and not as an empty collection — otherwise an outage
looks exactly like an organization that publishes no attachments.

## Per-organization collection

Counts come from the committed `data/busan/orgs/<slug>/fetch.json`.  `원본` is the
number of originals actually stored; `받지 못한 원본` is `FetchOutput.missing`;
`받지 않은 게시글` is postings whose 게시일 falls outside the target year, which
`period.collects` skips without opening (`FetchOutput.uncollected_postings`).

| 기관 | 원본 | 컨테이너별 | 받지 못한 원본 | 받지 않은 게시글 | 장부 경고 |
| --- | --- | --- | --- | --- | --- |
| 부산광역시 (`busan-city`) | 409 | hwpx 3 · ooxml 406 | drm 105 | 10,198 | 없음 |
| 부산광역시 중구 (`busan-jung`) | 405 | ole2 170 · ooxml 226 · pdf 9 | 0 | 10,406 | 없음 |
| 부산광역시 서구 (`busan-seo`) | 128 | ole2 27 · ooxml 101 | 0 | 937 | 없음 |
| 부산광역시 동구 (`busan-dong`) | 118 | hwpml 28 · hwpx 1 · ole2 2 · ooxml 1 · pdf 86 | 0 | 682 | 없음 |
| 부산광역시 영도구 (`busan-yeongdo`) | — | — | — | — | 수집 보류 `bot_blocked` |
| 부산광역시 부산진구 (`busan-busanjin`) | 480 | ooxml 446 · pdf 34 | drm 15 · not_an_original 1 | 4,338 | 없음 |
| 부산광역시 동래구 (`busan-dongnae`) | 119 | hwpx 40 · ole2 41 · ooxml 11 · pdf 27 | 0 | 2,538 | 없음 |
| 부산광역시 남구 (`busan-nam`) | — | — | — | — | 수집 보류 `bot_blocked` |
| 부산광역시 북구 (`busan-buk`) | 298 | hwpx 140 · ole2 128 · ooxml 9 · pdf 21 | drm 31 | 2,942 | 없음 |
| 부산광역시 해운대구 (`busan-haeundae`) | 289 | ole2 62 · ooxml 218 · pdf 9 | drm 51 | 4,163 | 없음 |
| 부산광역시 사하구 (`busan-saha`) | — | — | — | — | 수집 보류 `board_lost` |
| 부산광역시 금정구 (`busan-geumjeong`) | 402 | hwpx 241 · ole2 111 · pdf 50 | drm 15 | 5,949 | 없음 |
| 부산광역시 강서구 (`busan-gangseo`) | — | — | — | — | 수집 보류 `bot_blocked` |
| 부산광역시 연제구 (`busan-yeonje`) | 280 | hwpx 39 · ooxml 241 | 0 | 3,645 | 없음 |
| 부산광역시 수영구 (`busan-suyeong`) | 326 | ole2 30 · ooxml 296 | 0 | 8,593 | 없음 |
| 부산광역시 사상구 (`busan-sasang`) | 265 | hwpx 15 · ole2 215 · ooxml 9 · pdf 26 | drm 17 | 407 | busan-sasang/expenses=service-unavailable |
| 부산광역시 기장군 (`busan-gijang`) | 0 | — | 0 | 2,690 | `no attachment published …` (실패가 아니라 첨부 없는 게시판) |
| **합계 (수집 13개 기관)** | **3,519** | | **235** | **57,488** | |

The last column is `FetchOutput.empty_reason`, which is a ledger warning and not
always a failure: 기장군's entry records that the board publishes no attachment at
all (its table *is* the data), while 사상구's is a genuine interrupted walk.

**These are 2026 counts, not 상반기 counts.**  `period.collects` cuts by year, because
a quarter is published after the quarter ends, so a 상반기 원본 can be posted in July.
Narrowing to the first half happens downstream on the title-declared period, and this
issue's `fetch` stage deliberately does not do it.  Read against the whole-2026 set,
the first-half split is 2,373 of 3,519 originals (see *Title period notation*); it is
reported project-wide rather than per organization because `FetchOutput` carries no
per-organization posting count — only `sources`, `missing`, and
`uncollected_postings`.  Per-organization 상반기 counts belong to the `parse` stage,
which is outside #140's 구현 범위.

### 사상구 is the one board that did not finish its walk

`busan-sasang` keeps ending with
`collection failures: busan-sasang/expenses=service-unavailable`.  The host closes
the connection mid-walk (`RemoteDisconnected`), at a different page each run, and the
four project retries with their 2/4/8 s backoff do not outlast it.  It is not a rate
limit: 90 sequential listing pages at the project interval, and again at 1 s, all
returned 200.

The 2026 originals are nevertheless complete, and that is checkable rather than
assumed.  The board's listing index (`listing.jsonl`, now kept even when the walk is
cut short) holds 283 postings dated 2026; 282 of them are in the collection ledger.
The one that is not — `dataSid=565106`,
`보건행정과 업무추진비 사용내역(2026.7월)` — publishes no file at all: its detail page
contains zero `download.sasang` links and its body reads `해당없음`.

So what the failure costs is the tail of the walk, which only feeds the
`받지 않은 게시글` count: 407 is a floor for that board, not its total.  The artifact
says so in `empty_reason` instead of presenting the run as complete.

## DRM, measured per organization

Six of the thirteen collected organizations publish some DRM-locked attachments.  The
rate is the locked count over everything the board linked for 2026:

| organization | DRM | of | rate |
| --- | --- | --- | --- |
| 부산광역시 | 105 | 514 | 20.4% |
| 해운대구 | 51 | 340 | 15.0% |
| 북구 | 31 | 329 | 9.4% |
| 사상구 | 17 | 282 † | 6.0% † |
| 금정구 | 15 | 417 | 3.6% |
| 부산진구 | 15 | 495 | 3.0% |
| **합계** | **234** | **3,753** | **6.2%** |

† 사상구's denominator counts only what its interrupted walk reached.  Its 2026
postings are complete (see above), so the rate is sound for 2026, but it is a floor
for the board as a whole.

No organization was entirely DRM, so none is held for `drm`; every unlocked
attachment on the same posting was taken.  강서구, which the issue names alongside
부산시청 as a DRM risk, has no measurement at all: its `robots.txt` forbids the board
outright, so the question never arises — the hold is `bot_blocked`, not `drm`.

Two DRM products are in use, and the reconnaissance only knew about one:

- **Fasoo** (부산시청) — ` DRMONE  This Document is encrypted and protected by
  Fasoo DRM`, under `.xlsx` names.
- **Softcamp** (부산 북구) — `SCDSA004`, under `.hwp`/`.hwpx` names.  This one first
  appeared as 31 "unmeasured formats" that failed the whole organization while 297
  perfectly good originals sat beside them.

Neither is an unmeasured format: declaring the extension does not make them readable.
They are counted in the ledger as `drm`, next to `gone` and `empty`.

`Content-Type` is `application/octet-stream` for locked and unlocked alike, and the
markers some departments put in filenames (`_해제`, `★`) do not track the content.
Only the magic bytes decide.

## Formats the reconnaissance never saw

Two container kinds and one non-original had to be added, each after a real run
failed on it.

**HWPML** (부산 동구, 28 of its 118 originals).  한글 XML published under `.hwp` and
`.hwpx` names: a UTF-8 BOM, then `<?xml …?><HWPML Style="embed" …>`.  Neither OLE2 nor
a zip, so the first 동구 run ended `cause=unsupported-format`.  It is a real original,
so `hwpml` is now a container and the BOM is stripped before matching (which also
fixes BOM-prefixed SpreadsheetML).

**HWPX** (479 originals across 금정구, 북구, 동래구, 연제구, 사상구, 시청, 동구).
These were being counted as plain `zip`, because a HWPX package has neither
`[Content_Types].xml` nor `word/`/`xl/`/`ppt/` entries.  The package declares itself:
its first entry is an uncompressed `mimetype` holding `application/hwp+zip`.  Since
per-container counts are a completion criterion for this issue, calling a 한글 문서 an
archive would mislead whoever unpacks them next.  A genuine multi-file archive is
still `zip`.

**A file that is not an original** (부산진구 `dataSid=3966536`).  A 668-byte UTF-16LE
`HCellShareFileInfo` — the lock/share record 한셀 writes beside a document, not a
spending table.  Left as an unmeasured format, this single stray file failed the other
479 originals of that organization.  It is recorded as `not_an_original`, kept separate
from `gone`/`empty` because the organization can fix it by uploading the right file.

Reading HWPML and HWPX tables is out of scope for #140; the run records what was
received.

**This changes what a container name means across cities.**  `hwpml`, `hwpx`, and
`not_an_original` widen `contracts.Container` and `MissingOriginal.reason`, which every
city shares.  Widening a set leaves the committed 광주·울산 artifacts valid — no
existing value changed — but those artifacts were written before the split, so their
`.hwpx` sources are still labelled `ooxml`/`zip`.  Regenerating them needs their
원본, which live on the other developer's PC, so it is left to whoever re-runs those
cities.  The mismatch is in the label only; the stored bytes are untouched.

## Title period notation

`period.DECLARATION` previously read only the notations measured on the 광주시청 board.
One notation had to be added for Busan, and it is not cosmetic.

**Added: `제N분기`.**  부산시청 board 45 publishes `2026년 제1분기`, `2026년 제2분기`
(4 measured postings, e.g. `schIndx=21636`, `21635`, `21541`, `21506`).  Without it,
`제` blocked every quarter alternative and the title fell through to the year-only
reading — so `2026년 제3분기` was being read as *the whole of 2026* and would have
entered the first-half target set.  `tests/test_period.py` pins both `제1분기` → 1–3월
and `제3분기` → 7–9월.

Notations that were already read correctly and were re-confirmed on Busan titles:

| notation | measured on | reading |
| --- | --- | --- |
| `2026년 2분기` | every board | 4–6월 |
| `2026년 8월` | 부산진구, 서구, 해운대구 | 8월 |
| `2026년도 2분기` | 부산시청 45 (`schIndx=21927`) | 4–6월 |
| `2026년 1, 2월` | 영도구 (`idx=331576`) | 1–2월 |
| `2026년 3~7월` | 영도구 (`idx=333662`) | 3–7월 |
| `2026년 4~5월`, `2026년 4월 ~ 6월` | 북구 | 4–5월, 4–6월 |
| `업무추진비 사용내역(2026년 6월)` | 사상구 | 6월 |
| `(2026.6월)`, `(2026. 3월)` | 사상구, 중구 | 6월, 3월 |

Across all 3,519 collected originals the period reads as **2,373 in the reporting
period**, 1,143 declared outside it (2026 Q3 and later, plus 2025 back-postings
published during 2026), and **3 undeclared**.  All three undeclared titles are
source-side mistakes, and none is guessed at:

| organization | title | what is wrong |
| --- | --- | --- |
| 북구 | `2026월 3월 덕천1동 업무추진비 집행내역` | `년` typed as `월` |
| 부산시청 | `회계장비담당관 2분기 시책업무추진비 사용내역` | no year at all |
| 사상구 | `노인장애인복지과 업무추진비 사용내역(202년 2월)` | `2026` typed as `202` |

That count is this low only because the three shared boards are filtered by subject
first.  Before 해운대구 was declared mixed, 13 of the 14 undeclared titles were its
recurring `보건소 수의계약내역, 신용카드 사용내역 알림` — 수의계약 records, not
업무추진비.  `period.exclusion`'s `undeclared_in_year` is the watch point for the next
issue; it is now 3, and each one is a typo rather than an unmeasured notation.

## Left for a follow-up

**There is no `data/busan/fetch.json`.**  광주 and 울산 each have a whole-city artifact
next to their per-organization ones; 부산 has only the 13 per-organization files.

That is a shape difference, not a missing measurement: the per-organization artifacts
are what the 완료 기준 asks for ("기관마다 `data/busan/orgs/<slug>/fetch.json`이 남거나
수집 보류 사유가 레지스트리에 있다"), and every number in this document comes from them.
The whole-city file would carry the same 3,519 sources under one envelope.

Producing it means `fetch --city busan` with no `--org`, and that walks every board's
listing again in **one** process.  Measured: 6,211 listing pages left to walk at
1.5–2.7 s per page (북구 1.52, 기장군 1.82, 연제구 1.79, 해운대구 2.65), so ≈3.5 hours.
The per-organization collection was much faster only because the 16 hosts were walked
four at a time; a whole-city run cannot be split that way and still produce one
artifact.  The run was started, reached 시청's 1,060-page board, and was stopped
deliberately rather than left to finish.

Nothing about the collected 원본 changes when it is produced — the ledgers already hold
everything, so the eventual run re-reads listings and downloads nothing.

## Commands

Both shells, from the repository root:

```text
uv run python -m deliciousmap fetch --city busan
uv run python -m deliciousmap fetch --city busan --org busan-seo
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
git diff --check
```
