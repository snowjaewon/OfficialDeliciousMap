# Issue #132 validation — Ulsan pipeline run

Validation date: 2026-09-14.  The collection root was an external directory
passed with `--raw-root`; no 원본 was copied into this
repository.  This report separates implemented pipeline behavior from live
collection and data-quality gates that could not be completed.

The sections up to "Commands and results" record the 2026-09-14 runs.  The
[2026-09-15 completion check](#2026-09-15-completion-check) re-reads the
current artifacts after #145, #146, #147, #151, and #160 and supersedes their
figures.

## Implementation under test

- Ulsan transfer-board rows with legacy dates such as `20. 11. 5` are parsed
  as 2020 dates.  A two-digit match cannot take a substring of a four-digit
  year.
- A Ulsan board that fails with an adapter/service error is recorded in the
  fetch warning and the next registered board is attempted.  Other cities
  retain the previous fail-fast behavior.
- Nam-gu's measured `recordCountPerPage=30` option is used to reduce the
  number of listing requests during a resumable collection; the option is
  isolated to the Nam-gu adapter.
- `build --city ulsan --org <slug>` and `run --city ulsan --org <slug>` do not
  require the city map shell's public Naver key.  A city-wide build still
  requires that key.

## Per-organization evidence

| organization | 원본 / fetch evidence | parse and decision evidence | build / remaining status |
| --- | --- | --- | --- |
| `ulsan-city` | `fetch.json`: 1 source, 0 missing, 6,409 uncollected postings; the market PDF is the only received 원본, while transfer-board rows have no published 원본 | `headermap`/`parse`: 0 sources and 0 records for the in-period input; `classify`/`geocode`/`closure`: 0 results | organization build completed with 0 records and 0 markers; transfer-board rows remain represented by the uncollected count. **Superseded by the [#146 update](#issue-146-update--dong-gu-titles-and-a-month-only-title-2026-09-14)**: the market PDF is now a target source |
| `ulsan-junggu` | `fetch.json`: 126 sources, 0 missing, 9,443 uncollected postings; source hashes are unique (126). Boards: deputy 3, director 3, department 120. Containers: PDF 94, OLE2 18, ZIP 14. Fetch warning: `expenses-director=service-unavailable`. Fetch manifest SHA-256: `945f20fa964eef6aa87492f6a099c642fc31b277f548e67d463e4b29d4b2bfc1` | header mappings 0; unresolved 86 (`model_not_configured` 63, `no_table` 12, `unsupported_format` 11). Parse sources 86; excluded `declared_out_of_range=40`, `posted_out_of_range=0`, `undeclared_in_year=0`; repeated expenses 8. Classify/geocode/closure results 0; parse reports no records in the 2026-01-01..2026-06-30 period | organization build completed and wrote `dist/ulsan/orgs/ulsan-junggu/{records,markers}.json`; no city shell was touched |
| `ulsan-namgu` | `fetch.json`: 392 sources, 0 missing, 2,798 uncollected postings; source hashes are unique. Boards: deputy 8, director 49, department 227, dong 99, health 9. All source containers are PDF. Warning: `unmeasured-attachments=10` | `headermap`: 17 mappings, 254 unresolved sources, 1 unresolved mapping. `parse`: 271 sources, 17 parsed sources, 66 records, 254 unresolved sources. `classify`: 66 decisions — 1 restaurant, 1 non-restaurant, 64 pending (`model_not_configured`) | The organization `geocode` ran without a configured provider, so `경복궁` is recorded as `lookup_error` (`not_supplied`) and the stage saved its artifact and then exited 1 (`lookup-failed`); the Naver/licence lookups and the human confirmation were applied only to the city run (below). `closure` completed with 0 results and `build` wrote `dist/ulsan/orgs/ulsan-namgu/{records,markers}.json` with 66 records and 0 markers. The organization artifacts were not regenerated, so they still show 0 markers while the city output confirms `경복궁` |
| `ulsan-donggu` | `fetch.json`: 146 sources, 0 missing, 1,152 uncollected postings; all source containers are PDF. Warning: `unmeasured-attachments=28` | `headermap`/`parse`: 0 sources and 0 records for the in-period input; `classify`/`geocode`/`closure`: 0 results | organization build completed with 0 records and 0 markers. The mayor board was collected through measured `searchWrd=2026MM` queries; no coordinate is claimed. **Superseded by the [#146 update](#issue-146-update--dong-gu-titles-and-a-month-only-title-2026-09-14)**: all 146 sources had been dropped as `undeclared_in_year` because the scraper stored the row number as the title |
| `ulsan-bukgu` | `fetch.json`: 200 sources, 0 missing, 1,995 uncollected postings; all 200 source containers are PDF. Warning: `unmeasured-attachments=18` | `headermap`: 13 mappings, 126 unresolved sources. `parse`: 135 sources, 9 parsed sources, 58 records, 126 unresolved sources. `classify`: 58 decisions — 1 restaurant, 57 pending (`model_not_configured` 46; a cached shared-classification decision `상호명 정보 없음` 11) | The organization `geocode` ran without a configured provider, so `파리바게트` is recorded as `lookup_error` (`not_supplied`) and the stage saved its artifact and then exited 1 (`lookup-failed`); the Naver/licence lookups were applied only to the city run (below). `closure` completed with 0 results and `build` wrote `dist/ulsan/orgs/ulsan-bukgu/{records,markers}.json` with 58 records and 0 markers. No coordinate is claimed |
| `ulsan-ulju` | `fetch.json`: 8 sources, 0 missing, 66 uncollected postings; all 8 source hashes are unique and all are PDF. Fetch warning: `expenses-director=adapter-failed, expenses-department=adapter-failed`. Fetch manifest SHA-256: `7715c05e07a9217f879ee84d3a413d2623048d26136e7c17479cc1bf915f31e4` | header mappings 0; unresolved 6 (`model_not_configured` 6). Parse sources 6; excluded `declared_out_of_range=2`, `posted_out_of_range=0`, `undeclared_in_year=0`; repeated expenses 8. Classify/geocode/closure results 0; parse reports no records in the 2026-01-01..2026-06-30 period | organization `run` and the individual stages completed; build wrote `dist/ulsan/orgs/ulsan-ulju/{records,markers}.json` |

The completed manifests' paths were re-read outside the repository.  Their
leading signatures matched the recorded container for every source: Ulsan city
PDF 1; Jung-gu PDF 94, OLE2 18, ZIP 14; Nam-gu PDF 392; Dong-gu PDF 146;
Buk-gu PDF 200; Ulju-gun PDF 8.  No unsupported or missing 원본 was silently
converted to a successful source.  The unmeasured attachment warnings remain
explicit in the corresponding fetch artifacts.

## City-level partial merge and build

All six completed organization fetch artifacts were merged into the city fetch
artifact without changing any source or inventing records.  The merged warning
text in `data/ulsan/fetch.json` preserves the per-board service, adapter, and
unmeasured-attachment conditions.

The figures in this section and the next are from before the
[#146 update](#issue-146-update--dong-gu-titles-and-a-month-only-title-2026-09-14).
The resulting city artifact contains 873 source hashes and 21,863 uncollected
postings.  `headermap` has 30 mappings, 472 unresolved sources, and 1
unresolved mapping.  `parse` examined 498 sources and produced 124 records;
`classify` wrote 124 decisions: 2 restaurant, 1 non-restaurant, and 121
pending (`model_not_configured` 110; the cached shared-classification decision
`상호명 정보 없음` 11).  Only the two restaurant decisions enter geocode, so the
121 pending decisions are the main reason the city has at most two marker
candidates.  An earlier revision of this report said "1 pending"; the counts
above were re-read from `data/ulsan/classify.json` and the organization
`classify.json` files on 2026-09-14.

## City geocode human review

The first approved city geocode retry received five Naver candidates for each
of the two restaurant records.  All ten were in Seoul or Incheon — the lookup
does not add city context to the query — and both records stayed
`missing_address` because the source records carry no address.  A human
review was then run for each record; search rank was not used to choose a
candidate.

| record | expense | decision | evidence |
| --- | --- | --- | --- |
| `116b614e978728d0-table1-R3` (`ulsan-namgu`) | 2026-05-21, 일자리청년과, `경복궁`, 351,000원 | **confirmed** by the user (record scope) in `data/manual/ulsan/geocode.jsonl` | 인허가 조회서비스 일반음식점, query `경복궁`: all 356 rows (4 pages) were read for this review. Ulsan rows: 5. Only `3700000-101-2024-00403` `경복궁`, 남구 산업로 595, 2~3층 (삼산동), licensed 2024-10-30, is 영업/정상; the other four (including the earlier licence at the same address) closed between 2003 and 2022-08-30. The 휴게음식점 (42) and 제과점 (3) results were not truncated; their only Ulsan row is the differently named `경복궁고로케`. The business is in the same 자치구 as the spending organization. No receipt or other direct payment-place evidence exists; the confirmation says so |
| `2b3b369e15e84e3e-table3-R6` (`ulsan-bukgu`) | 2026-06-22, 안전총괄과, `파리바게트`, 22,900원 | **held** — `missing_address` | a franchise name without a branch; neither the source nor any available document ties the expense to one store, so no candidate was confirmed (the user decided to keep it held) |

The pipeline's licence lookup caches only the first page (100 rows per
service), so the full-page read that established the single operating Ulsan
licence was a separate, uncached verification read.  The confirmed candidate
itself is on the cached first page, which is what the confirmation line refers
to.  The coordinate (35.5347509, 129.3503733) is the licence TM coordinate
converted to WGS84; no Naver candidate for the Ulsan branch was available to
cross-check it.  The four closed Ulsan licence rows and the 영업/정상 status are
provider-only fields that the candidate contract does not carry
([지오코딩](../geocoding.md#인허가-조회)); they exist in the repository only as the
confirmation's `references` text, not as re-checkable cached data.

The confirmation uses `branch: ""` because it must match the licence candidate
exactly, and the licence registers the business as `경복궁` with no branch
name.  The chain branch name seen elsewhere (`경복궁 울산점`, and the closed
licence `경복궁울산점(주)엔타스`) is not a separate branch fact; the business is
identified by the registered name plus the address.

This confirmation does **not** follow the confirmation criteria that
[#64](issue-64.md) set and the user adopted for Gwangju's districts on
2026-09-13 ([issue-99.md](issue-99.md), "마커는 사람 확인으로만 생긴다"): at least
11 visits at the organization, exactly one exact-name search candidate, and
that candidate inside the office's 구.  `경복궁` has one visit, and its Naver
search candidates contain no Ulsan store.  Those criteria exist because
filtering by a boundary can promote a same-name business to the answer
([지오코딩](../geocoding.md): "기관 도시 밖 후보를 거르거나 기관 도시 안 동명이 업소로
바꾸지 않는다").  This record was instead reviewed individually at the user's
request with licence evidence: the full licence read shows that on the
expense date no other `경복궁` in Ulsan was operating, and the remaining
same-name businesses are outside Ulsan.  That still does not rule out payment at
a store outside Ulsan, and no receipt ties the expense to this store.  The user
approved it knowing this, as a one-record exception scoped to
`116b614e978728d0-table1-R3`.  It is not a new general criterion and does not
extend to other `경복궁` records.

The city `geocode --retry-failed` was re-run with the Naver and licence
providers configured (`GEMINI_*` removed from the environment and the model
transport refused).  It reused the cached Naver lookups and added one licence
lookup per record (`경복궁` 145 candidates, `파리바게트` 210 candidates).
Result: `경복궁` `success`/`human_confirmed`, `파리바게트` `failed`/`missing_address`.
City `closure` wrote one result, `unknown` (`license-evidence-not-supplied`:
no Ulsan licence file is under the 원본 루트), and the city `build` succeeded
with 124 records and **1 marker** (`경복궁`, `coordinate_source: license`).
The marker's `closed: false` only means closure did not report `closed`
(`site.py` sets `closed` from closure status `closed` alone); the closure
status is `unknown`, so no closure check was made for this marker.  The
organization artifacts were not regenerated.

## Issue #146 update — Dong-gu titles and a month-only title (2026-09-14)

The period watch point `undeclared_in_year` was 147 in the city artifact
(Dong-gu 146, Ulsan city 1).  [#146](https://github.com/snowjaewon/OfficialDeliciousMap/issues/146)
fixed both causes.

- Dong-gu's eGov listings also link the row-number cell to the article, so
  the scraper stored the number (`46`) as the title and the real title as the
  department.  The scraper now reads the linked cell that is not a bare row
  number as the title and the cell after it as the department.
- The Ulsan city mayor board titles its posting `6월 업무추진비 사용 내역`
  with no year.  A title that starts with a single month is now read as the
  latest such month not after the posting date (here June 2026).

`fetch --city ulsan --org ulsan-donggu` re-walked the Dong-gu boards (6 min 28
s, exit 0).  No attachment was downloaded again: the 146 source hashes, paths,
URLs, posting dates, and containers are identical, and only `title` and
`department` changed (for example `2026년 2분기 업무추진비 집행내역(부구청장)` /
`총무과`).  Missing originals 0, uncollected postings 1,152, and the warning
`unmeasured-attachments=28` are unchanged.  The Ulsan city market 원본 was not
re-collected; its stored title is read by the new rule.

The city fetch artifact was regenerated by concatenating the six organization
fetch artifacts in registry order, the method that produced the earlier city
artifact.  Merging the pre-#146 organization artifacts this way reproduced the
committed `data/ulsan/fetch.json` byte for byte before the new Dong-gu artifact
was merged.  After a merge of `origin/develop` (which brought #137's
companion-tail classification), the city stages and the `ulsan-donggu` and
`ulsan-city` organization stages were re-run without a model (`GEMINI_*`
removed, model transport refused).

| city artifact | before #146 | after #146 |
| --- | ---: | ---: |
| sources / uncollected postings | 873 / 21,863 | 873 / 21,863 |
| target sources (`parse`) | 498 | **594** (Dong-gu +95, city +1) |
| `undeclared_in_year` / `declared_out_of_range` | 147 / 228 | **0** / 279 |
| header mappings / unresolved | 30 / 472 (`model_not_configured` 402, `no_table` 59, `unsupported_format` 11) | 30 / 568 (`model_not_configured` 494, `no_table` 63, `unsupported_format` 11) |
| records | 124 | 124 |
| classify | 2 restaurant, 1 non-restaurant, 121 pending | 3 restaurant, 1 non-restaurant, 120 pending (`model_not_configured` 109, cached `상호명 정보 없음` 11) |
| geocode | `경복궁` human_confirmed; `파리바게트` missing_address | same, plus `스타벅스 코리아 외1` (Buk-gu, 2026-02-04, 82,100원) missing_address |
| build | 124 records, 1 marker | 124 records, 1 marker |

- `ulsan-donggu`: 95 target sources, 51 `declared_out_of_range`, 0
  `undeclared_in_year`.  By the corrected listing titles 116 postings are in
  the period (department 105, deputy 2, director 9); 93 of them have sources
  (the 95 PDFs).  The other 23 department postings carry HWP (15) or HWPX (8)
  attachments, formats not measured for this board, so they were not collected
  and are part of the `unmeasured-attachments=28` warning.  `headermap` 0 mappings, 95 unresolved
  (`model_not_configured` 91, `no_table` 4), so `parse` produced 0 records and
  `build` 0 records / 0 markers.
- `ulsan-city`: the market PDF is a target source; `headermap` leaves it
  `model_not_configured`, so 0 records.
- `스타벅스 코리아 외1` became a restaurant through the shared classification of
  `스타벅스 코리아` after #137.  Its Naver lookup (5 candidates, none in Ulsan)
  and licence lookup ran; no branch or address ties the record to a store, so
  it is held.

The 96 newly targeted sources add no records until their header mappings are
resolved; that needs the model run, which this issue does not include.  No
attachment-board `undeclared_in_year` remains.  The HTML-table boards (city
transfer boards, Jung-gu and Dong-gu mayor) still produce no sources and are
handled in [#145](https://github.com/snowjaewon/OfficialDeliciousMap/issues/145).
The `ulsan-junggu`, `ulsan-namgu`, `ulsan-bukgu`, and `ulsan-ulju`
organization artifacts were not regenerated; the Nam-gu and Buk-gu
organization classifications do not reflect #137.

Checks on the tree after the #146 commits, the develop merge (`1890d2f`), and the
review fixes that narrowed the month-only rule (the Ulsan target counts above are
unchanged by the narrowing): `uv run pytest` 662 passed; `ruff check`, `ruff format
--check` (141 files), `mypy src`, `git diff --check`, and `check-data` passed;
`check-dist --city ulsan` on a clean Ulsan-only output root sealed 12 files.

## LLM budget, privacy, and output boundary

No new Gemini reservation or settlement was written while running this issue;
the 공통 LLM 예산 장부 remained unchanged.  Header-mapping and classification
shortfalls therefore remain explicit (`model_not_configured`), not fabricated
decisions.  No API key, 원본, or personal data was added to the
repository.  `dist/` and the external 원본 루트 remain local validation
artifacts; `git status` must be checked before commit.

The licence lookups use the 공공데이터포털 key from the local `.env`; the key
value is not written to any artifact.  The six organization fetch artifacts are
complete and the city geocode/closure/build have been re-run after the human
review, but the city-shell map-tile check is **not complete** and no
real-device check has been performed.  The organization builds above are
structural partial-output checks only; they do not prove real-data quality,
geocode success, device rendering, or measured performance.

## Partial city HTTP check

The rebuilt city output was served from a clean local static server with
`python -m http.server 8765 --directory dist --bind 127.0.0.1`. These routes
returned HTTP 200: `/`, `/ulsan/`, `/ulsan/index.html`,
`/ulsan/records.json` (48,180 bytes, `application/json`),
`/ulsan/markers.json` (502 bytes, `application/json`),
`/manifest.webmanifest` (642 bytes, `application/manifest+json`), `/sw.js`, and
`/assets/app.js`. This is a route and 정제 산출물 integrity check for the
rebuilt city output after the human review; it is not a map-tile or
real-device check.  The JSON contains 124 records and one marker (`경복궁`);
`파리바게트` and the 121 pending classifications stay in the ledger only.

The 2026-09-14 retries completed for Ulsan city, Buk-gu, and Dong-gu after long
listing reads. Buk-gu's measured `rows=30` option, Nam-gu's measured
`recordCountPerPage=30` option, and Dong-gu mayor's measured monthly search are
isolated to their adapters. No coordinate or real-data map success is claimed
for the partial organization outputs; the only confirmed coordinate is the
city-level `경복궁` confirmation described above.

## Commands and results

The checks below were re-run on 2026-09-14 after the geocode review data commit
(`018f263`) and the merge of `origin/develop` (`7b8502a`), on that tree plus
this report.  `check-dist` ran on a clean Ulsan-only output root built from
the same data.

```text
.\.tools\uv\bin\uv.exe run pytest
# 648 passed

.\.tools\uv\bin\uv.exe run ruff check .
# All checks passed

.\.tools\uv\bin\uv.exe run ruff format --check .
# 140 files already formatted

.\.tools\uv\bin\uv.exe run mypy src
# Success: no issues found in 50 source files

git diff --check
# passed

gitleaks detect --no-banner --redact --log-opts 'origin/develop..HEAD'
# no leaks found

.\.tools\uv\bin\uv.exe run python -m deliciousmap.ci check-data --data-root data
# gwangju
# ulsan

.\.tools\uv\bin\uv.exe run python -m deliciousmap.ci check-dist --dist <clean-output-root> --commit <validated-commit> --city ulsan
# check-dist: sealed 12 files for <validated-commit>

python -m http.server 8765 --directory dist --bind 127.0.0.1
# HTTP 200: /, /ulsan/, /ulsan/index.html, /ulsan/records.json,
# /ulsan/markers.json, /manifest.webmanifest, /sw.js, /assets/app.js

# after the human review (.env loaded, GEMINI_* removed, model transport refused)
.\.tools\uv\bin\uv.exe run python -m deliciousmap geocode --city ulsan --retry-failed
# exit 0; 경복궁 success/human_confirmed, 파리바게트 failed/missing_address
.\.tools\uv\bin\uv.exe run python -m deliciousmap closure --city ulsan
# exit 0; 1 result, unknown (license-evidence-not-supplied)
.\.tools\uv\bin\uv.exe run python -m deliciousmap build --city ulsan
# exit 0; 124 records, 1 marker
```

The remaining acceptance gates are map-tile behavior in a browser and
real-device checks.  `파리바게트` stays held until a branch or address can be
tied to the record; confirming a store by visit or phone is outside this issue.
The HTTP route check above is not substituted for those gates; they remain
explicitly incomplete rather than being marked as passed from the build.

## 2026-09-15 completion check

Base commit `20703d6` (develop after #147 and the #160 regeneration).  Every
figure below was read from the committed `data/ulsan/**` artifacts: `fetch.json`
`payload.sources`/`missing`/`uncollected_postings`/`empty_reason`,
`headermap.json` `mappings`/`unresolved`, `parse.json` `sources`/
`excluded_sources`/`repeated_expenses`, `classify.json` `decisions`,
`geocode.json` and `closure.json` `results`, and `build.json`
`record_count`/`marker_count`.  Board figures join `fetch.json` `board` to
`parse.json` and `records.csv` by source hash.  SHA-256 is `sha256sum` of the
file.  Units: sources and target sources are 원본 files, postings are listing
rows, records are `records.csv` rows.

### Stage exits

With the committed artifacts as input, `headermap`, `parse`, `classify`,
`geocode`, `closure`, and `build` were re-run for each organization
(`--org <slug>`) and then for the city, 42 stage runs in all.  The runner loaded
only `NAVER_SEARCH_*`, `NAVER_MAP_*`, and `DATA_GO_KR_KEY` from `.env`, removed
`GEMINI_*`, and replaced `socket.connect` and `socket.create_connection` with a
refusal.  All 42 runs exited 0 and made no network attempt (`fetch` was not
re-run; it is the live collection recorded above and in #145/#146).  Every
tracked output was byte-identical except the Nam-gu and Buk-gu organization
`headermap.json`.  Those were written before #145 added the optional
`declared` field, and the re-run adds only `"declared": false` to each mapping
(13 in Buk-gu, 17 plus one unresolved mapping in Nam-gu).  The mappings are
otherwise equal, so they are committed as re-serialized.  `ArtifactStore.load`
then read all seven stages of the city and of each organization with the current
code.

### Fetch ledger by organization

| organization | `fetch.json` SHA-256 | 원본 (unique hashes) · missing · uncollected postings | containers | fetch warning |
| --- | --- | --- | --- | --- |
| `ulsan-city` | `73c88b8dfd167652560fa89870fc8f49336c730ae6faaa0b6a79d131d511c087` | 648 (648) · 0 · 11,991 | html 647, pdf 1 | `ulsan-city/expenses-department=adapter-failed` |
| `ulsan-junggu` | `534d9450be114ec12c08728fc8a0304667d3a5df323c8b512e843ba246954111` | 156 (156) · 0 · 1,865 | pdf 118, ole2 23, zip 12, ooxml 2, html 1 | none |
| `ulsan-namgu` | `c07fb8043a4999ec240374caa313ca7ea8b7d6713d37e8f15313089d471684ec` | 392 (392) · 0 · 2,798 | pdf 392 | `unmeasured-attachments=10` |
| `ulsan-donggu` | `4a2d75d529405aab3990151884ab3736801029824a59d38cc389dc3ffc12f58f` | 171 (171) · 0 · 1,152 | pdf 146, html 25 | `unmeasured-attachments=28` |
| `ulsan-bukgu` | `565f67a0ef53bc7c2fdf287c917bdd63e1f95487b9a5c18d92ebb262daf0611b` | 200 (199) · 0 · 1,995 | pdf 200 | `unmeasured-attachments=18` |
| `ulsan-ulju` | `7715c05e07a9217f879ee84d3a413d2623048d26136e7c17479cc1bf915f31e4` | 8 (8) · 0 · 66 | pdf 8 | `expenses-director=adapter-failed, expenses-department=adapter-failed` |
| city (`data/ulsan`) | `f3183f8b88af707bc219ccbb7846d37695f13b19d7ac48516e01465764c41bd8` | 1,575 (1,574) · 0 · 19,867 | pdf 865, html 673, ole2 23, zip 12, ooxml 2 | the five warnings above, joined |

- The city ledger is the six organization ledgers concatenated in registry
  order.  Its counts are the sums of the rows above (1,575 원본, 19,867
  postings).
- Buk-gu's one repeated hash is one PDF attached to two postings, `2025년 4분기
  업무추진비 집행내역` (2026-01-07) and `2025년 4분기 업무추진비 집행현황(농소3동)`
  (2026-08-31).  Both declare 2025, so the file is not a target source and adds no
  record.
- Uncollected postings are listing rows whose posting year is outside 2026.
  The warnings mark what the ledger cannot count: `unmeasured-attachments=N` is
  postings whose attachments have a format not measured for the board (not
  downloaded), and `adapter-failed` is a board whose walk stopped.  Ulsan city
  `expenses-department` stops at a 2020 row dated `202-12-28`, after the
  2026 rows ([#145](issue-145.md)).  The Ulju-gun director and department boards
  collected nothing.  The postings after a stop are not counted.

### Parse, decisions, and map status by organization

| organization | target 원본 · parsed / unresolved (reasons) | out of period (`declared_out_of_range`) | records | restaurant / non-restaurant / pending | geocode | closure | build records / markers |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| `ulsan-city` | 502 · 467 / 35 (`validation_failed` 34, `model_not_configured` 1) | 146 | 3,070 | 62 / 65 / 2,943 | 62 `failed`/`missing_address` | 0 | 3,070 / 0 |
| `ulsan-junggu` | 105 · 1 / 104 (`model_not_configured` 78, `unsupported_format` 14, `no_table` 12) | 51 | 198 | 9 / 14 / 175 | 9 `failed`/`missing_address` | 0 | 198 / 0 |
| `ulsan-namgu` | 271 · 17 / 254 (`model_not_configured` 223, `no_table` 31) | 121 | 66 | 1 / 1 / 64 | 1 `success`/`human_confirmed` | 1 `unknown` | 66 / 1 |
| `ulsan-donggu` | 120 · 23 / 97 (`model_not_configured` 91, `no_table` 4, `validation_failed` 2) | 51 | 33 | 0 / 5 / 28 | 0 | 0 | 33 / 0 |
| `ulsan-bukgu` | 135 · 9 / 126 (`model_not_configured` 110, `no_table` 16) | 65 | 58 | 2 / 0 / 56 | 2 `failed`/`missing_address` | 0 | 58 / 0 |
| `ulsan-ulju` | 6 · 0 / 6 (`model_not_configured` 6) | 2 | 0 | 0 / 0 / 0 | 0 | 0 | 0 / 0 |
| city (`data/ulsan`) | 1,139 · 517 / 622 (`model_not_configured` 509, `no_table` 63, `validation_failed` 36, `unsupported_format` 14) | 436 | 3,425 | 74 / 85 / 3,266 | 1 `success`/`human_confirmed`, 73 `failed`/`missing_address` | 1 `unknown` | 3,425 / 1 |

- The city row equals the column sums of the six organizations.  No
  `posted_out_of_range` or `undeclared_in_year` source remains.
- Pending (3,266 records): 3,174 are `unclassified: model_not_configured`.  The
  other 92 reuse cached shared-classification decisions that are themselves
  pending: `상호명 정보 없음` 81, `업종 확인 불가` 4, `업종 미확인` 3,
  `상호만으로 판정 불가` 2, `업종 판단 불가` 1, `상호만으로 업종 불분명` 1.  By
  organization, 2,862 + 81 in Ulsan city, 175 in Jung-gu, 64 in Nam-gu, 28 in
  Dong-gu, and 45 + 11 in Buk-gu.
- Unsupported format: the 14 `unsupported_format` sources are Jung-gu `ole2`
  원본 (department 10, director 4).  `validation_failed` is 34 Ulsan city
  department days with won amounts in a thousand-won table (`amount_unit`) and
  2 Dong-gu mayor days with a blank amount (`amount_krw`), both in
  [#145](issue-145.md).  These sources stay unresolved.  None is converted to
  records or dropped from the ledger.
- Repeated expenses: Ulsan city has 25 expenses (26 records) that appear once
  in each of two 원본 and are not merged (ADR-0004).  The other organizations have none.
- Coordinate failures: all 73 are `missing_address`.  The 원본 carry a merchant
  name without an address or branch, and search rank is not used to choose one.
  The only coordinate is the record-scoped `경복궁` confirmation described in
  [City geocode human review](#city-geocode-human-review).  Its closure status
  is `unknown` (`license-evidence-not-supplied`).

### Board detail

| organization / board | 원본 · target | parsed / unresolved | records | restaurant / non-restaurant / pending | geocode failed |
| --- | --- | --- | ---: | --- | ---: |
| `ulsan-city/expenses-market` | 1 · 1 | 0 / 1 | 0 | 0 / 0 / 0 | 0 |
| `ulsan-city/expenses-deputy` | 105 · 85 | 85 / 0 | 167 | 2 / 0 / 165 | 2 |
| `ulsan-city/expenses-economic` | 88 · 77 | 77 / 0 | 144 | 1 / 0 / 143 | 1 |
| `ulsan-city/expenses-fez` | 83 · 73 | 73 / 0 | 79 | 0 / 4 / 75 | 0 |
| `ulsan-city/expenses-director` | 179 · 129 | 129 / 0 | 1,180 | 20 / 30 / 1,130 | 20 |
| `ulsan-city/expenses-department` | 192 · 137 | 103 / 34 | 1,500 | 39 / 31 / 1,430 | 39 |
| `ulsan-junggu/expenses-mayor` | 1 · 1 | 1 / 0 | 198 | 9 / 14 / 175 | 9 |
| `ulsan-junggu/expenses-deputy` | 3 · 2 | 0 / 2 | 0 | 0 / 0 / 0 | 0 |
| `ulsan-junggu/expenses-director` | 32 · 21 | 0 / 21 | 0 | 0 / 0 / 0 | 0 |
| `ulsan-junggu/expenses-department` | 120 · 81 | 0 / 81 | 0 | 0 / 0 / 0 | 0 |
| `ulsan-namgu/expenses-deputy` | 8 · 6 | 0 / 6 | 0 | 0 / 0 / 0 | 0 |
| `ulsan-namgu/expenses-director` | 49 · 37 | 0 / 37 | 0 | 0 / 0 / 0 | 0 |
| `ulsan-namgu/expenses-department` | 227 · 155 | 12 / 143 | 44 | 1 / 0 / 43 | 0 (1 confirmed) |
| `ulsan-namgu/expenses-dong` | 99 · 67 | 5 / 62 | 22 | 0 / 1 / 21 | 0 |
| `ulsan-namgu/expenses-health` | 9 · 6 | 0 / 6 | 0 | 0 / 0 / 0 | 0 |
| `ulsan-donggu/expenses-mayor` | 25 · 25 | 23 / 2 | 33 | 0 / 5 / 28 | 0 |
| `ulsan-donggu/expenses-deputy` | 4 · 3 | 0 / 3 | 0 | 0 / 0 / 0 | 0 |
| `ulsan-donggu/expenses-director` | 12 · 9 | 0 / 9 | 0 | 0 / 0 / 0 | 0 |
| `ulsan-donggu/expenses-department` | 130 · 83 | 0 / 83 | 0 | 0 / 0 / 0 | 0 |
| `ulsan-bukgu/expenses` | 200 · 135 | 9 / 126 | 58 | 2 / 0 / 56 | 2 |
| `ulsan-ulju/expenses-deputy` | 8 · 6 | 0 / 6 | 0 | 0 / 0 / 0 | 0 |

Uncollected postings are kept per organization only.  The ledger has no board
field for them ([#145](issue-145.md), remaining limits).  Boards absent from
the table (Ulju-gun director and department) have no 원본.

### LLM budget

`data/_shared/llm-budget.jsonl` (SHA-256
`b1cfd25a8808ed33713947a1cd34243529e9ee56073fccb16422b660329a0e28`) has 755
entries: 1 `prior_usage`, 377 reservations (header mapping 335, classification
42), and 377 settlements.  `Budget.committed()` is USD 0.75009150 against the
USD 15 limit.  The file was last changed by `81fecd8` (#137, Gwangju), and no
Ulsan commit or run changed it.  The Ulsan pipeline made no LLM call.  Its 92
model-evidenced pending decisions above are shared-cache reuse, not new calls.

### Published output, size, and privacy

- `build --city ulsan` with the public map key from `.env` exited 0 and wrote
  `dist/ulsan/records.json` (1,320,202 bytes, 3,425 records) and
  `dist/ulsan/markers.json` (502 bytes, 1 marker).  Records by
  classification/map status: pending 3,266, non-restaurant 85, restaurant with
  geocode failure 73, and mapped 1.
- `check-data --data-root data` passed (20MB cap per refined artifact,
  registered directories, and city/organization classification consistency).  A
  clean build to a scratch output root passed `check-dist --city ulsan` and
  sealed 12 files for `20703d6`.  The build's rewrite of `data/ulsan/build.json`
  was restored.
- `records.json` `merchant`/`purpose`/`department` were scanned for phone,
  card, resident-number, e-mail, masked-name, and name-plus-title patterns.
  The only matches were 406 purposes with office titles (`행정국장` 105, …,
  `총무과장` 36) and `부처님` 2.  No personal name, phone number, or card number was found.  The
  `참석대상` column stays unmapped, as in [#145](issue-145.md).
- `git diff origin/develop..HEAD -- data/gwangju data/_shared` is empty.  No
  other city's refined outputs or confirmed businesses were changed.

### Browser check (local)

`dist` was served with `python -m http.server 8765 --directory dist --bind
127.0.0.1`, and `http://127.0.0.1:8765/ulsan/` was opened in Chrome.  The server
answered 200 or 304 for every request (`/ulsan/`, `markers.json`,
`records.json`, `app.js`, `styles.css`, the manifest, `sw.js`, and the icons).

- Map tiles rendered with the configured key.  No authentication-failure
  notice appeared.
- The `경복궁` marker was drawn in 삼산동, and the list showed `1곳 전체 · 1곳 현재
  지도 영역`.  Clicking the marker opened the detail: 방문 1회, 합계 351,000원,
  울산광역시 남구 산업로 595, 2~3층 (삼산동), 최근 방문 2026-05-21, 방문 기관
  울산광역시 남구, 폐업 확인 없음, 좌표 출처 인허가 자료, and a Naver map link.
- Dragging the map away from the marker changed the count to `1곳 전체 · 0곳
  현재 지도 영역`.
- The 장부 tab loaded `records.json` and showed `전체 3,425건`.  After paging to
  the end (`3,425건 표시`), the ledger showed 판단 보류 3,266, 비식당 85,
  `지오코딩 실패 · 주소 근거 없음` 73, and the one mapped record.  These match
  the counts above.
- Not re-checked here: the zoom-out limit and the pan bounds.  Wheel input did
  not reach the map through the automation.  The automation's scroll,
  screenshot, and script calls also timed out several times (30–45 s), both
  before and after all 3,425 ledger rows were rendered.  The cause was not
  isolated.  Those
  map controls are city-independent code verified in
  [#50](https://github.com/snowjaewon/OfficialDeliciousMap/issues/50).  Real-device
  checks belong to [#77](https://github.com/snowjaewon/OfficialDeliciousMap/issues/77).

### Checks

```text
uv sync --locked
uv run pytest                    # 810 passed
uv run ruff check .              # All checks passed
uv run ruff format --check .     # 162 files already formatted
uv run mypy src                  # Success: no issues found in 55 source files
git diff --check                 # passed
uv run python -m deliciousmap.ci check-data --data-root data   # gwangju, ulsan
uv run python -m deliciousmap.ci check-dist --dist <scratch-root> --commit 20703d6... --city ulsan
                                 # check-dist: sealed 12 files
gitleaks (pre-commit hook)       # see the commit
```

### Remaining limits

- The map has one marker.  3,266 records wait for the model-based
  classification, and 73 restaurant records have no address evidence.  Both are
  outside this issue.
- 622 target 원본 are unresolved (above).  Their records are not in the ledger
  until header mappings are resolved.
- `fetch.json` source paths are absolute paths on the collecting PC, including
  its user directory name, as in the Gwangju ledger.  They are not published to
  `dist`.
