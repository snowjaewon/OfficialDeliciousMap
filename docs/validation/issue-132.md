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
| `ulsan-city` | `fetch.json`: 1 source, 0 missing, 6,409 uncollected postings; the market PDF is the only received 원본, while transfer-board rows have no published 원본 | `headermap`/`parse`: 0 sources and 0 records for the in-period input; `classify`/`geocode`/`closure`: 0 results | organization build completed with 0 records and 0 markers; transfer-board rows remain represented by the uncollected count |
| `ulsan-junggu` | `fetch.json`: 126 sources, 0 missing, 9,443 uncollected postings; source hashes are unique (126). Boards: deputy 3, director 3, department 120. Containers: PDF 94, OLE2 18, ZIP 14. Fetch warning: `expenses-director=service-unavailable`. Fetch manifest SHA-256: `945f20fa964eef6aa87492f6a099c642fc31b277f548e67d463e4b29d4b2bfc1` | header mappings 0; unresolved 86 (`model_not_configured` 63, `no_table` 12, `unsupported_format` 11). Parse sources 86; excluded `declared_out_of_range=40`, `posted_out_of_range=0`, `undeclared_in_year=0`; repeated expenses 8. Classify/geocode/closure results 0; parse reports no records in the 2026-01-01..2026-06-30 period | organization build completed and wrote `dist/ulsan/orgs/ulsan-junggu/{records,markers}.json`; no city shell was touched |
| `ulsan-namgu` | `fetch.json`: 392 sources, 0 missing, 2,798 uncollected postings; source hashes are unique. Boards: deputy 8, director 49, department 227, dong 99, health 9. All source containers are PDF. Warning: `unmeasured-attachments=10` | `headermap`: 17 mappings, 254 unresolved sources, 1 unresolved mapping. `parse`: 271 sources, 17 parsed sources, 66 records, 254 unresolved sources. `classify`: 66 decisions, 1 pending | The approved Naver retry returned five candidates for `경복궁`, but identity remained `missing_address` because the source record has no address. `closure` completed with 0 results and `build` wrote `dist/ulsan/orgs/ulsan-namgu/{records,markers}.json` with 66 records and 0 markers. No coordinate is claimed |
| `ulsan-donggu` | `fetch.json`: 146 sources, 0 missing, 1,152 uncollected postings; all source containers are PDF. Warning: `unmeasured-attachments=28` | `headermap`/`parse`: 0 sources and 0 records for the in-period input; `classify`/`geocode`/`closure`: 0 results | organization build completed with 0 records and 0 markers. The mayor board was collected through measured `searchWrd=2026MM` queries; no coordinate is claimed |
| `ulsan-bukgu` | `fetch.json`: 200 sources, 0 missing, 1,995 uncollected postings; all 200 source containers are PDF. Warning: `unmeasured-attachments=18` | `headermap`: 13 mappings, 126 unresolved sources. `parse`: 135 sources, 9 parsed sources, 58 records, 126 unresolved sources. `classify`: 58 decisions, 1 pending | The approved Naver retry returned five candidates for `파리바게트`, but identity remained `missing_address` because the source record has no address. `closure` completed with 0 results and `build` wrote `dist/ulsan/orgs/ulsan-bukgu/{records,markers}.json` with 58 records and 0 markers. No coordinate is claimed |
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

The resulting city artifact contains 873 source hashes and 21,863 uncollected
postings.  `headermap` has 30 mappings, 472 unresolved sources, and 1
unresolved mapping.  `parse` examined 498 sources and produced 124 records;
`classify` wrote 124 decisions with 1 pending decision.  With the approved
`.env` credentials, the city geocode retry received five Naver candidates for
each of the two records requiring lookup.  Both remained `missing_address` because
the source records do not contain addresses, so no coordinate was claimed.
City `closure` completed with 0 results and the city `build` then succeeded with
124 records and 0 markers after loading the public map key from `.env`.

## LLM budget, privacy, and output boundary

No new Gemini reservation or settlement was written while running this issue;
the 공통 LLM 예산 장부 remained unchanged.  Header-mapping and classification
shortfalls therefore remain explicit (`model_not_configured`), not fabricated
decisions.  No API key, 원본, or personal data was added to the
repository.  `dist/` and the external 원본 루트 remain local validation
artifacts; `git status` must be checked before commit.

The six organization fetch artifacts are complete, but the city-wide
`run --city ulsan` and city-shell page/tile check are **not complete** because
the two records still lack independent address evidence and no real-device or
map-tile behavior check has been performed.  The organization builds above are
structural partial-output checks only; they do not prove real-data quality,
geocode success, device rendering, or measured performance.

## Partial city HTTP check

The rebuilt city output was served from a clean local static server with
`python -m http.server 8765 --directory dist --bind 127.0.0.1`. These routes
returned HTTP 200: `/`, `/ulsan/`, `/ulsan/index.html`,
`/ulsan/records.json` (48,126 bytes, `application/json`),
`/ulsan/markers.json` (68 bytes, `application/json`), and
`/manifest.webmanifest` (642 bytes, `application/manifest+json`). This is a
route and 정제 산출물 integrity check for the rebuilt city output; it is not a
map-tile or real-device check.  The JSON contains 124 records and zero markers
because both Naver candidates remain unconfirmed for lack of source addresses.

The 2026-09-14 retries completed for Ulsan city, Buk-gu, and Dong-gu after long
listing reads. Buk-gu's measured `rows=30` option, Nam-gu's measured
`recordCountPerPage=30` option, and Dong-gu mayor's measured monthly search are
isolated to their adapters. The approved Naver retry returned candidates for
the two records with names, but both remained explicitly failed with
`missing_address`; no coordinate or real-data map success is claimed for these
partial organization outputs.

## Commands and results

```text
.\.tools\uv\bin\uv.exe run pytest
# 648 passed (latest local run)

.\.tools\uv\bin\uv.exe run ruff check .
# All checks passed

.\.tools\uv\bin\uv.exe run ruff format --check .
# 139 files already formatted

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
# /ulsan/markers.json, /manifest.webmanifest
```

The remaining acceptance gates are independent address evidence for the two
geocode records, an HTTP page check against the complete city output and
map-tile behavior, and real-device checks.
The partial-output HTTP route check above is not
substituted for those gates; they remain explicitly incomplete rather than
being marked as passed from the partial build.
