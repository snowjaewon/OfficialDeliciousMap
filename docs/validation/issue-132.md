# Issue #132 validation — Ulsan pipeline run

Validation date: 2026-09-14.  The collection root was an external directory
passed with `--raw-root`; no 원본 file was copied into this
repository.  This report separates implemented pipeline behavior from live
collection and data-quality gates that could not be completed.

## Implementation under test

- Ulsan transfer-board rows with legacy dates such as `20. 11. 5` are parsed
  as 2020 dates.  A two-digit match cannot take a substring of a four-digit
  year.
- A Ulsan board that fails with an adapter/service error is recorded in the
  fetch warning and the next registered board is attempted.  Other cities
  retain the previous fail-fast behavior.
- `build --city ulsan --org <slug>` and `run --city ulsan --org <slug>` do not
  require the city map shell's public Naver key.  A city-wide build still
  requires that key.

## Per-organization evidence

| organization | 원본 / fetch evidence | parse and decision evidence | build / remaining status |
| --- | --- | --- | --- |
| `ulsan-city` | 4 원본 files and 1 수집 장부 row were left by an interrupted city fetch; no fetch artifact or complete source-hash manifest | not run; collection remains incomplete | not built; **collection held** after a server read stalled |
| `ulsan-junggu` | `fetch.json`: 126 sources, 0 missing, 9,443 uncollected postings; source hashes are unique (126). Boards: deputy 3, director 3, department 120. Containers: PDF 94, OLE2 18, ZIP 14. Fetch warning: `expenses-director=service-unavailable`. Fetch manifest SHA-256: `945f20fa964eef6aa87492f6a099c642fc31b277f548e67d463e4b29d4b2bfc1` | header mappings 0; unresolved 86 (`model_not_configured` 63, `no_table` 12, `unsupported_format` 11). Parse sources 86; excluded `declared_out_of_range=40`, `posted_out_of_range=0`, `undeclared_in_year=0`; repeated expenses 8. Classify/geocode/closure results 0; parse reports no records in the 2026-01-01..2026-06-30 period | organization build completed and wrote `dist/ulsan/orgs/ulsan-junggu/{records,markers}.json`; no city shell was touched |
| `ulsan-namgu` | no 원본 files or fetch artifact; live fetch was not completed | not run | **uncollected**; no output claimed |
| `ulsan-donggu` | no 원본 files or fetch artifact; live fetch stalled before the first 첨부 | not run | **collection held**; no output claimed |
| `ulsan-bukgu` | 200 원본 files and 193 수집 장부 rows remain outside the repository. The fetch process stalled before saving `fetch.json`; 수집 장부 SHA-256: `488e4e6164134fb20f14f88093b54c5a2dc9d8158df0ecb5294274d835836986` | not run because there is no completed fetch manifest | **collection held**; no partial files were promoted to refined output |
| `ulsan-ulju` | `fetch.json`: 8 sources, 0 missing, 66 uncollected postings; all 8 source hashes are unique and all are PDF. Fetch warning: `expenses-director=adapter-failed, expenses-department=adapter-failed`. Fetch manifest SHA-256: `7715c05e07a9217f879ee84d3a413d2623048d26136e7c17479cc1bf915f31e4` | header mappings 0; unresolved 6 (`model_not_configured` 6). Parse sources 6; excluded `declared_out_of_range=2`, `posted_out_of_range=0`, `undeclared_in_year=0`; repeated expenses 8. Classify/geocode/closure results 0; parse reports no records in the 2026-01-01..2026-06-30 period | organization `run` and the individual stages completed; build wrote `dist/ulsan/orgs/ulsan-ulju/{records,markers}.json` |

The completed manifests' paths were re-read outside the repository.  Their
leading signatures matched the recorded container for every source: Jung-gu
PDF 94, OLE2 18, ZIP 14; Ulju-gun PDF 8.  No unsupported or missing 원본
was silently converted to a successful source.  For the incomplete Buk-gu and
city collections, no hash claims beyond the external 수집 장부 are
made.

## LLM budget, privacy, and output boundary

No new Gemini reservation or settlement was written while running this issue;
the 공통 LLM 예산 장부 remained unchanged.  Header-mapping and classification
shortfalls therefore remain explicit (`model_not_configured`), not fabricated
decisions.  No API key, 원본, or personal data was added to the
repository.  `dist/` and the external 원본 루트 remain local validation
artifacts; `git status` must be checked before commit.

The city-wide `run --city ulsan` and city-shell page/tile check are **not
complete**: collection did not finish for all six organizations, and the
public Naver map key was not configured in this environment.  The two
organization builds above are structural output checks only; they do not prove
real-data quality, geocode success, device rendering, or measured performance.

## Commands and results

```text
.\.tools\uv\bin\uv.exe run pytest
# 646 passed in 116.16s

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
```

The remaining acceptance gates are the six-organization live fetch, a
city-level merge/build, a local HTTP page check, and independent geocode
evidence.  They are left as explicit incomplete work rather than being marked
as passed from the two organization-scoped builds.
