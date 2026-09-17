# Issue #173 validation — Daegu expense boards

Validation date: 2026-09-17.  Every request used the project user agent
`OfficialDeliciousMap/0.1 (+https://github.com/snowjaewon/OfficialDeliciousMap)`,
was issued sequentially per host, and no browser user agent was used.  원본 were
received on this PC under `--raw-root C:\Users\설재원\deliciousmap-raw` (outside the
repository) and are not committed.  Every organization's 원본 come from that one root.

## Organizations

10 organizations are registered in `src/deliciousmap/registry/daegu.py` (#13 counts
대구 as 시청 + 9 구·군).  7 have one board each (slug `expenses`); 3 are held.

| organization | slug | board | scraper |
| --- | --- | --- | --- |
| 대구광역시 | `daegu-city` | `index.do?menu_id=00000084&postPerPage=50` | `IcmsBoard` |
| 대구광역시 중구 | `daegu-jung` | — | held: `bot_blocked` |
| 대구광역시 동구 | `daegu-dong` | `/portal/board/post/list.do?bcIdx=557&mid=0501040000` | `CouncilFilteredYhLibBoard` |
| 대구광역시 서구 | `daegu-seo` | `/portal/board/post/list.do?bcIdx=511&mid=0502030000` | `CouncilFilteredYhLibBoard` |
| 대구광역시 남구 | `daegu-nam` | `index.do?menu_id=00001247&postPerPage=50` | `IcmsBoard` |
| 대구광역시 북구 | `daegu-buk` | — | held: `bot_blocked` |
| 대구광역시 수성구 | `daegu-suseong` | `index.do?menu_id=00042650` (2026년 화면) | `OfficialTableBoard` |
| 대구광역시 달서구 | `daegu-dalseo` | — | held: `bot_blocked` |
| 대구광역시 달성군 | `daegu-dalseong` | `index.do?menu_id=00001704&postPerPage=20` | `IcmsBoard` |
| 대구광역시 군위군 | `daegu-gunwi` | `/ko/page.do?mnu_uid=160` | `GunwiBoard` |

Each board was found from the organization's own home page menu (`업무추진비`,
`업무추진비 공개`, `업무추진비공개`) and is the only expense board under that menu.
Every district publishes department-level postings on that one board (부서·동·직급이
한 게시판에 섞여 있다), so none is `below_threshold`.

## robots.txt

Read once per host.  A group names our user agent only through `User-agent: *`.

| host | bytes | `*` group | covers what we request? |
| --- | --- | --- | --- |
| `www.daegu.go.kr` | 74 | `Allow: /`, `Disallow: /sf-1/` | no |
| `www.jung.daegu.kr` | 441 | not a robots file — see 중구 below | — |
| `www.dong.daegu.kr` | 96 | `Disallow:/search/front/Search.jsp` | no |
| `www.dgs.go.kr` | 333 | `Disallow: /search/`, `Disallow: /*/board/post/` with `Allow: /*/board/post/*bcIdx=` 574·569·568·566·542·538·516·511, `Allow: /` | the expense board `bcIdx=511` is explicitly allowed (longer match); files `/common/file/download.do` fall under `Allow: /` |
| `www.nam.daegu.kr` | 132 | none — only `Googlebot` | no group applies |
| `www.buk.daegu.kr` | 99 | `Disallow:/icms/cmm/fms/FileDown.do`, `Disallow: /index.do?menu_link=/icms/bbs/`, `Allow:/` | **originals disallowed** |
| `www.suseong.kr` | 101 | none — only `Googlebot` | no group applies |
| `www.dalseo.daegu.kr` | 25 | `Disallow: /` | **everything disallowed** |
| `www.dalseong.daegu.kr` | 114 | `Disallow: /search_page/search_page.jsp`, `Disallow: /*?menu_link=/icms/bbs/selectBoardList.do`, `Allow: /` | no — the listing is requested as `index.do?menu_id=…&pageIndex=N` (no `menu_link`), the detail uses `selectBoardArticle.do` after `?menu_id=` |
| `www.gunwi.go.kr` | 34 | `Disallow: /upload/*` | no — files come from `/board_download.do` with a direct `200` (no redirect, checked with redirects disabled) |

At 달서구 only `robots.txt` was requested.  At 북구 the home page, the expense menu and one
detail page were read (all allowed); `FileDown.do` was never requested.

## Collection holds (`bot_blocked`)

- **중구.**  `https://www.jung.daegu.kr/robots.txt`, `/`, and `http://gu.jung.daegu.kr/`
  (the address other Daegu sites link to) all answer `200` with the same 441-byte page:
  a script that writes `sabFingerPrint` (window size) and `sabSignature` cookies and calls
  `window.location.reload()`.  Answering it means running or imitating that script to
  obtain cookies, which is a bot-block bypass, so 중구 is held — confirming #13's candidate.
- **북구.**  The board (`menu_id=00000122`, `BBSMSTR_000000001173`, 5,197 postings, 의회사무국
  postings mixed in) opens normally, but every attachment is
  `fn_egov_downFile(…)` → `/icms/cmm/fms/FileDown.do`, which the `*` group disallows.  The
  only other route is `filePreview` → `/filePreview.do`, a converted viewer, not the original.
  Following #172 (대전시청), a robots prohibition is not worked around.
- **달서구.**  `robots.txt` is `User-agent: *` / `Disallow: /`.

## Board contracts

### ICMS — 시청, 남구, 달성군

Listing `index.do?menu_id=<menu>&pageIndex=N&postPerPage=<n>` (GET; the site POSTs the same
form).  UTF-8.  `postPerPage` is the largest value the page's own select offers (시청·남구 50,
달성군 20).  The last page is the `?pageIndex=N` link (`마지막`): 시청 105, 달성군 231.

- A row opens its posting with `onclick="fn_icms_navi_common('view', '<nttId>')"`.
- The department column is found by its header — `부서명` (시청·달성군) or `담당부서` (남구).
- The board id is the form's hidden `bbsId` (`BBS_00040`, `BBSMSTR_000000000182`, `BBS_00066`).
  The detail is `index.do?menu_id=<menu>&menu_link=/icms/bbs/selectBoardArticle.do&bbsId=<bbsId>&nttId=<id>`
  — the URL the site's `getActionUrl` builds — and opens with GET.
- The detail lists files as `href="javascript:fn_egov_downFile('<atchFileId>','<fileSn>')"`;
  each is followed by a `filePreview(…)` link to the same file, which is not counted.
  The file is `/icms/cmm/fms/FileDown.do?atchFileId=…&fileSn=…`.  Ids differ per site: 시청
  `FILE_000000000720279`/`0`, 남구 64- and 32-hex tokens, 달성군 `FILE_000000000077779FVFTVW`/`0…2`.
- The detail is opened because the 시청 listing shows only one file per row (a row showed
  `fileSn=1` alone); 달성군's listing shows all three files of a posting.
- File text: 시청 `<span>name.xlsx</span>`, 달성군 `★name.xlsx [12339 byte]`, 남구
  `name.xlsx [16934 byte]` **followed by `<img alt="첨부파일">` inside the link**.  The first
  남구 run failed (`adapter-failed`, "unusable attachment extension") because that alt text
  stayed after the size; the name is now cut at a size-shaped `[… byte|KB|MB]` and everything
  after it.  A bracket that is not a size (`[붙임] … .xlsx`, no size as at 시청) is kept.
- 달성군 listing titles are truncated by the site (`…사용내역 공...`); the ledger keeps them as
  listed.

### yhLib portal — 동구, 서구

Same family as 부산 강서구, so `scrapers.busan.YhLibBoard` is reused: list
`list.do?bcIdx=&mid=&page=N`, detail `view.do?bcIdx=&mid=&idx=`, files
`yhLib.file.download('<64 hex>','<32 hex>')` → `/common/file/download.do?atchFileId=&fileSn=`,
last page from `goPage(N)` (동구 393, 서구 459).  The `/portal/contents.do?mid=…` menu address
redirects to these lists with a `token` parameter that the list does not need.

- 동구 carries the posting id in `data-req-get-p-idx` (as 강서구); 서구 puts it only in the link
  address `view.do?…&idx=252051`.  `_yhlib_index` now falls back to that address.
- 동구 has no writer column; 서구 has `list_write` (department).
- Both boards mix in the council secretariat (`…(의회사무국장)`, `2026년 8월 의회사무국장 …`), so
  `CouncilFilteredYhLibBoard` filters `의회` in title or department and counts it.

### 수성구 — yearly official tables

Not a board.  `index.do?menu_id=00000168` redirects to the current year
(`menu_id=00042650` = 2026; 2025 is `00042456`, …).  The page has a `search_target` select of
67 entries (구청장 … 고산3동장, one `------------------` separator) and, for the selected
official, a monthly table (건수·금액) with one attachment per month.  Choosing an official posts
form `icmsBoeVO` to `?menu_id=00042650&menu_link=/front/businessOperatingExpense/icmsOperatingExpenseFront.do`;
the same fields sent with GET return the same page (checked for 부구청장: 8 months, identical ids).

- One month's attachment group (`atchFileId`, e.g. `FILE_00000140205GNNF`) is one posting;
  its id without `_` is the posting id.  There is no posting date, so `posted` is empty and the
  collection takes every posting on the 2026 page.  The title is the file name
  (`2026년 1월 업무추진비공개(구청장)`), the department is the official.
- The page names the selected official with `selected`; a page that does not select the
  official asked for is refused.
- `의회사무국장` is requested and its months are counted as filtered (8).
- Months with no spending have no attachment (구청장 4·5월: 건수 0).
- Files are `/icms/cmm/fms/FileDown.do?atchFileId=…&fileSn=0`.

### 군위군 — own CMS

`/ko/page.do?mnu_uid=160&pageNo=N`; the page count is the text `전체 페이지 32`.  A row links
`?…&mnu_uid=160&&bod_uid=<id>&pageNo=1&cmd=2`; `cmd=2` answers with a script redirect to
`cmd=258` (after counting a view), so the detail is requested directly as
`page.do?mnu_uid=160&bod_uid=<id>&cmd=258`.  Files are `<a href="/board_download.do?file_uid=<n>">`,
each followed by a `[미리보기]` link that is not counted.  The writer column (`작성자`) holds the
department.  Two old council postings (`의회사무과장 업무추진비(2021년 상반기)`,
`의회사무과 업무추진비 (2020년 1월 ~3월)`) are filtered.

## Per-organization collection

Counts come from the committed `data/daegu/orgs/<slug>/fetch.json` and from the raw folders'
`listing.jsonl`/`collected.jsonl`.  Units: **목록** = postings in the listing index (council
postings excluded); **2026** / **상반기** = listing postings whose 게시일 is in 2026 /
2026-01-01…06-30; **받은 게시글** = 2026 postings in the collection ledger; **원본** = stored
files (`FetchOutput.sources`); **원본 없는 게시글** = 2026 postings that publish no attachment
(the collection does not write those to the ledger).  The collection selects by 게시일 year
(`period.collects`); the first-half filter is applied downstream by the spending period.

| 기관 | 목록 | 2026 | 상반기 | 받은 게시글 | 원본 | 확장자 | 매직 바이트(앞 4) | 원본 없는 게시글 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 대구광역시 | 5,234 | 393 | 263 | 392 | 398 | xlsx 374 · xls 23 · pdf 1 | `504b0304` 374 · `d0cf11e0` 23 · `25504446` 1 | 1 |
| 중구 | — | — | — | — | — | — | — | 수집 보류 `bot_blocked` |
| 동구 | 3,824 | 147 | 99 | 146 | 156 | pdf 93 · xlsx 54 · xls 9 | `25504446` 93 · `504b0304` 54 · `d0cf11e0` 9 | 1 |
| 서구 | 4,405 | 423 | 293 | 422 | 422 | xlsx 422 | `504b0304` 422 | 1 |
| 남구 | 4,254 | 267 | 189 | 265 | 276 | xlsx 253 · xls 23 | `504b0304` 253 · `d0cf11e0` 23 | 2 (+ 16 with only empty files) |
| 북구 | — | — | — | — | — | — | — | 수집 보류 `bot_blocked` |
| 수성구 | 461 (월 첨부 묶음) | 461 (게시일 없음, 2026년 화면) | 354 (제목의 1~6월) | 461 | 461 | xlsx 453 · xls 8 | `504b0304` 453 · `d0cf11e0` 8 | 0 |
| 달서구 | — | — | — | — | — | — | — | 수집 보류 `bot_blocked` |
| 달성군 | 4,541 | 273 | 178 | 269 | 293 | xls 150 · xlsx 139 · pdf 4 | `d0cf11e0` 150 · `504b0304` 139 · `25504446` 4 | 4 |
| 군위군 | 308 | 52 | 37 | 52 | 68 | pdf 60 · xlsx 8 | `25504446` 60 · `504b0304` 8 | 0 |

The extension of every stored file agrees with its container.  The three extensions seen
across the 2,074 originals (`xls`, `xlsx`, `pdf`) are what `scrapers.daegu.PUBLISHED_SUFFIXES`
declares, for the ICMS, 수성구 and 군위군 scrapers and for `CouncilFilteredYhLibBoard` (narrower
than 부산 강서구's `YhLibBoard`, which also accepts `hwp`·`hwpx`).

Ledger totals per organization (`fetch.json` payload):

| 기관 | 원본 | 컨테이너 | 받지 못한 원본 | 받지 않은 게시글 | 걸러 낸 게시글 | 장부 경고 |
| --- | --- | --- | --- | --- | --- | --- |
| 대구광역시 | 398 | ooxml 374 · ole2 23 · pdf 1 | 0 | 4,841 | 0 | 없음 |
| 중구 | 0 | — | 0 | 0 | 0 | `collection held: daegu-jung=bot_blocked` |
| 동구 | 156 | pdf 93 · ooxml 54 · ole2 9 | 0 | 3,677 | 97 | 없음 |
| 서구 | 422 | ooxml 422 | 0 | 3,982 | 184 | 없음 |
| 남구 | 276 | ooxml 253 · ole2 23 | 20 (empty) | 3,987 | 150 | 없음 |
| 북구 | 0 | — | 0 | 0 | 0 | `collection held: daegu-buk=bot_blocked` |
| 수성구 | 461 | ooxml 453 · ole2 8 | 0 | 0 | 8 | 없음 |
| 달서구 | 0 | — | 0 | 0 | 0 | `collection held: daegu-dalseo=bot_blocked` |
| 달성군 | 293 | ole2 150 · ooxml 139 · pdf 4 | 0 | 4,268 | 64 | 없음 |
| 군위군 | 68 | pdf 60 · ooxml 8 | 0 | 256 | 2 | 없음 |

**Filtered postings, audited.**  Every filtered row was listed again with the scrapers
(listing only) and its title/department read: 남구 150 all `의회사무과`; 달성군 64 all
`의회사무국` (61) or `의회사무과` (3); 서구 184 all `의회사무국` (98) or `대구광역시서구의회` (86);
동구 97 (no department column) all with `의회사무` in the title; 군위군 2 as quoted above;
수성구 8 are `의회사무국장` months.  No executive posting was filtered.  One first audit pass of
동구 stopped with "board listing does not declare its page count" while the city-wide run was
walking the same host; pages 1–393 were re-read and all declare `goPage(393)`, and the repeat
pass over 동구 and 서구 finished without it.

`목록 + 걸러 낸 게시글` equals each site's own total: 동구 3,824 + 97 = 3,921, 서구 4,405 +
184 = 4,589, 남구 4,254 + 150 = 4,404, 달성군 4,541 + 64 = 4,605, 군위군 308 + 2 = 310.

**Postings without an original, checked one by one.**
- 시청 `819848` (`2026년 1분기 …(자원순환과)`): body `해당없음(업무추진비 미사용)`.
- 동구 `194855` (`2026년 2분기 …(위생과)`): body says `…집행내역입니다.` but the file box says
  `파일이 없습니다.` — a publication gap, not a collection failure.
- 서구 `251903` (`2026년 8월 상중이동장 …`): body `사용 내역 0건`.
- 남구 `190077`, `190683` (대명10동 1월·3월): body `…집행내역은 없음으로 공개합니다.`
- 달성군 `50873`, `52983` (도시공원과 3월·6월) `…사용내역 없음`; `53120` (정책보좌관·총무과장
  6월) `해당없음`; `51210` (`2026년 1분기 주민복지국장 및 복지정책과장 …`): the body names the
  spending but the attachment list is empty — a publication gap.

**남구 empty originals.**  16 postings (게시일 2026-02-27…2026-03-10, `nttId` 190164…190354)
list 20 files with a size (e.g. `(2026년 2월)건축과업무추진비사용내역.xls [26112 byte]`) but
`FileDown.do` answers `200` with 0 bytes, with and without the detail as Referer.  They are in
`missing` as `empty`; no other posting of those 16 has a stored file.  No DRM, gone, or
editor side file was met anywhere.

## Commands

Git Bash, repository root:

```text
uv run python -m deliciousmap fetch --city daegu --org daegu-jung --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daegu --org daegu-buk --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daegu --org daegu-dalseo --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daegu --org daegu-gunwi --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daegu --org daegu-suseong --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daegu --org daegu-dong --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daegu --org daegu-seo --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daegu --org daegu-nam --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daegu --org daegu-dalseong --raw-root /c/Users/설재원/deliciousmap-raw
uv run python -m deliciousmap fetch --city daegu --org daegu-city --raw-root /c/Users/설재원/deliciousmap-raw
```

Wall time: 군위군 138 s, 수성구 311 s, 동구 606 s, 서구 1,487 s, 남구 499 s (after the fix;
the first run failed in 7 s), 달성군 405 s (resumed), 시청 581 s + 161 s (resumed).  The
background run was stopped by the host for low memory during 달성군; each organization was
resumed from its ledger in the foreground.

`fetch --city daegu` was then run once with `--data-root` in a scratch folder (the committed
artifacts stay per organization, as for Busan #140 and Daejeon #172).  It took 1,582 s,
reused every ledger, downloaded nothing new, and its `fetch.json` equals the sum of the
organization files: 2,074 sources (서구 422 · 수성구 461 · 시청 398 · 달성군 293 · 남구 276 ·
동구 156 · 군위군 68), 20 missing (남구 empty), 21,011 받지 않은 게시글
(4,841 + 3,677 + 3,982 + 3,987 + 0 + 4,268 + 256), 505 걸러 낸 게시글
(97 + 184 + 150 + 8 + 64 + 2), no warning.  The three `bot_blocked` holds are not repeated in the
city result because sources exist; they are in each held organization's `fetch.json`.

## Left for a follow-up

- `parse` and later stages, and the map, are out of scope (#173 제외 범위).
- 중구·북구·달서구 stay held until an allowed route exists.
- 수성구 만촌1동장 titles write the month as `(2026.1)`…`(2026.8)`; `period.declared` reads them
  as the whole of 2026, so the 8 files are not taken as first-half spending until the parse
  stage handles that form.
- 남구's 20 empty originals and the two publication gaps (동구 `194855`, 달성군 `51210`) can only
  be filled by the organizations.
- Hall coordinates and `address_prefixes` for Daegu are not declared yet (pipeline issue).
