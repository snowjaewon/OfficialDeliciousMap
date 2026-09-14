# Issue #131 validation — Ulsan expense boards

Validation date: 2026-09-14.  Requests used the project user agent
`OfficialDeliciousMap/0.1 (+https://github.com/snowjaewon/OfficialDeliciousMap)`.
The HTML responses and downloaded originals used for reconnaissance were kept
outside the repository; no raw or `dist/` file is committed here.

## Registered boundaries

`src/deliciousmap/registry/ulsan.py` registers six non-empty organizations in
this order: city, Jung-gu, Nam-gu, Dong-gu, Buk-gu, and Ulju-gun.  `--org`
selects one organization and `fetch --city ulsan` iterates the registered
boards in that order.  Boards whose current page contains transaction rows
without an original attachment are intentionally represented by postings with
an empty attachment tuple.

| organization | measured list endpoint(s) | observed listing size | attachment boundary |
| --- | --- | --- | --- |
| Ulsan city | `https://www.ulsan.go.kr/u/rep/bbs/list.ulsan?bbsId=BBS_0000000000000255&mId=001003002007000000` | market: 1 post; PDF icon; 2026-07-23 | detail `view.do` → `HHBbs.EncDownFile` → `/u/enc/media/bbsFileDown.do` |
| Ulsan city | `https://www.ulsan.go.kr/u/rep/transfer/director/list.ulsan?mId=001003002003000000` | 2,012 posts / 202 pages | inline transaction table; no attachment endpoint |
| Ulsan city | `https://www.ulsan.go.kr/u/rep/transfer/ecnmy/list.ulsan?mId=001003002001000000` | 4,664 posts / 467 pages | inline transaction table; no attachment endpoint |
| Jung-gu | `https://www.junggu.ulsan.kr/mayor/board/list.ulsan?boardId=BBS_0000006&listCel=1&listRow=10&menuCd=DOM_000000201005000000` | 8,046 rows / 805 pages | transaction rows; no attachment endpoint |
| Jung-gu | `https://www.junggu.ulsan.kr/index.ulsan?boardId=BBS_0000114&menuCd=DOM_000000104007001000&paging=ok&startPage=1`; `https://www.junggu.ulsan.kr/board/list.ulsan?boardId=BBS_0000115&menuCd=DOM_000000104007002000&paging=ok&startPage=1`; `https://www.junggu.ulsan.kr/board/list.ulsan?boardId=BBS_0000116&menuCd=DOM_000000104007003000&paging=ok&startPage=1`; `https://www.junggu.ulsan.kr/board/list.ulsan?boardId=BBS_0000117&menuCd=DOM_000000104007004000&paging=ok&startPage=1` | 2026 current boards; 1,262 posts / 127 pages on department board; legacy 426 / 43 | listing `board/download.ulsan` links; ZIP files (legacy board retained for history) |
| Nam-gu | `https://www.ulsannamgu.go.kr/cop/bbs/selectBoardList.do?bbsId=PrmtFee`; `https://www.ulsannamgu.go.kr/cop/bbs/selectBoardList.do?bbsId=PrmtFee1`; `https://www.ulsannamgu.go.kr/cop/bbs/selectBoardList.do?bbsId=PrmtFee2`; `https://www.ulsannamgu.go.kr/cop/bbs/selectBoardList.do?bbsId=dongPrmtFee`; `https://www.ulsannamgu.go.kr/cop/bbs/selectBoardList.do?bbsId=healthPrmtFee` | 77, 356, 1,630, 1,056, 77 posts respectively | listing `/cmm/fms/FileDown.do`; PDF links; article links are retained as provenance |
| Dong-gu | `https://www.donggu.ulsan.kr/cop/bbs/selectBoardList.do?bbsId=BBSMSTR_000000000354`; `https://www.donggu.ulsan.kr/cop/bbs/selectBoardList.do?bbsId=BBSMSTR_000000000361`; `https://www.donggu.ulsan.kr/cop/bbs/selectBoardList.do?bbsId=BBSMSTR_000000000362` | 46, 140, 1,136 posts respectively | listing `/cmm/fms/FileDown.do`; PDF links |
| Dong-gu | `https://www.donggu.ulsan.kr/mayor/expense/list.do` | 4,032 rows / 404 pages | transaction rows; no attachment endpoint |
| Buk-gu | `https://www.bukgu.ulsan.kr/lay1/bbs/S1T136C1896/A/348/list.do` | 2,206 posts / 221 pages at the default 10 rows; the measured form also publishes 20 and 30 rows | detail `view.do?article_seq=` → `/download.do?uuid=...`; PDF |
| Ulju-gun | `https://www.ulju.ulsan.kr/ulju/bbs/list.do?ptIdx=117&mId=0216040100`; `https://www.ulju.ulsan.kr/ulju/bbs/list.do?ptIdx=117&mId=0216040200`; `https://www.ulju.ulsan.kr/ulju/bbs/list.do?ptIdx=117&mId=0216040300` | 8 pages on the deputy board (10 rows per page) | detail `ulju/bbs/view.do` → `fn_egov_downFile` → `/cmm/fms/FileDown.do`; PDF |

The city transfer and Jung-gu/Dong-gu mayor boards are not silently treated
as failed attachments: their measured contract is a published transaction
table, so the scraper preserves the posting/date/title and records no original.

## Robots and collection decision

| host | `robots.txt` with project UA | decision |
| --- | --- | --- |
| `www.ulsan.go.kr` | HTTP 200; `User-agent: *`, allows `/` except unrelated manager paths | collect registered boards |
| `www.junggu.ulsan.kr` | HTTP 200; only disallows one unrelated `BBS_0000088` URL | collect registered boards |
| `www.ulsannamgu.go.kr` | HTTP 200; `User-agent: *`, `Allow: /` | collect registered boards |
| `www.donggu.ulsan.kr` | HTTP 200; restriction is for `Googlebot` on `*/cop/bbs/` | project UA is not blocked; collect |
| `www.bukgu.ulsan.kr` | HTTP 200 response was an HTML error page, not a robots policy | no robots block observed; endpoint was separately verified |
| `www.ulju.ulsan.kr` | HTTP 200; restriction is for `Googlebot` on `/ulju/bbs/` | project UA is not blocked; collect |

No authentication, DRM, robots bypass, or guessed URL was used.  A future live
fetch that receives a service block should record one of the existing hold
reasons (`bot_blocked`, `drm`, `board_lost`, `below_threshold`) rather than
turning the board into an empty successful result.

## Format and evidence ledger

The measured signatures are PDF `%PDF-` for the PDF links above and ZIP
`PK\x03\x04` for the Jung-gu download links.  OOXML packages are still
distinguished from generic ZIP archives by their `[Content_Types].xml` or
`word/`, `xl/`, and `ppt/` entries.  The registry exposes only `.pdf` on PDF
boards, only `.zip` on Jung-gu boards, and no suffix on transaction-table
boards, so an unexpected suffix remains `unmeasured` in the existing
collection ledger.

The counts in the table are the measured board totals and page counts from the
2026-09-14 listing responses; the newest rows were 2026 entries.  A complete
year-only attachment tally requires walking every declared page and downloading
each original, which was not run during this registry implementation.  Such a
run must use an external `--raw-root`, then record the resulting source SHA-256
and per-post ledger entries; no raw originals or hashes are fabricated here.

## Fixture and format checks

`tests/test_ulsan.py` covers page traversal, malformed page metadata, direct
eGov and Jung-gu attachments, city encoded download arguments, Buk-gu and
Ulju detail boundaries, no-attachment transaction boards, `--org` selection,
and the six-organization registry.  `.zip` is a measured published suffix;
`container_of` distinguishes a valid generic ZIP from OOXML while preserving
the existing short OOXML signature behavior.
