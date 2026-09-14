# Issue #132 validation — Ulsan pipeline run

Validation date: 2026-09-14.  The collection root was an external directory
passed with `--raw-root`; no 원본 was copied into this
repository.  This report separates implemented pipeline behavior from live
collection and data-quality gates that could not be completed.

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
  `undeclared_in_year`.  `headermap` 0 mappings, 95 unresolved
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

Checks on the tree after the #146 commits and the develop merge (`1890d2f`) plus
these artifacts: `uv run pytest` 657 passed; `ruff check`, `ruff format
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
