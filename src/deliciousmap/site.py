"""Static site shell generated from refined build inputs."""

import json
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from html import escape
from importlib.resources import files
from pathlib import Path
from typing import Literal

from deliciousmap.contracts import (
    ClassificationStatus,
    GeocodeResult,
    Provider,
    PublishedRecord,
    Record,
)
from deliciousmap.registry import CITIES, City, HoldReason, Organization
from deliciousmap.storage import write_text

ASSET_NAMES = ("app.js", "styles.css")
REPORTING_PERIOD = "2026년 상반기"
# 수집 보류 사유의 화면 표기. 사유 자체의 단일 출처는 레지스트리다.
HOLD_REASON_LABELS: dict[HoldReason, str] = {
    "bot_blocked": "봇 차단",
    "drm": "DRM",
    "board_lost": "게시판 유실",
    "below_threshold": "공개 기준 미달",
}
COLLECTION_LABELS = {"collected": "수집 완료", "empty": "레코드 없음", "held": "수집 보류"}
CLIENT_ID_VARIABLE = "NAVER_MAP_CLIENT_ID"
KEY_PARAM_VARIABLE = "NAVER_MAP_KEY_PARAM"
# 신규 발급 키는 ncpKeyId, 2026-06 이전의 구형 키만 ncpClientId를 쓴다.
KEY_PARAMS = ("ncpKeyId", "ncpClientId")
# 도시 진입 페이지에서 본 공통 자산·랜딩의 위치. 도시 화면은 언제나 한 단계 아래에 둔다.
SITE_ROOT = "../"


@dataclass(frozen=True)
class MapKey:
    """브라우저에 공개되는 지도 SDK 키. 비밀값이 아니지만 저장소에는 두지 않는다."""

    client_id: str
    key_param: str = KEY_PARAMS[0]

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise ValueError(CLIENT_ID_VARIABLE)
        if self.key_param not in KEY_PARAMS:
            raise ValueError(KEY_PARAM_VARIABLE)


def map_key_from_environment(environ: Mapping[str, str] | None = None) -> MapKey:
    """값은 어디에도 출력하지 않고 변수 이름만 알린다."""
    values = os.environ if environ is None else environ
    return MapKey(
        values.get(CLIENT_ID_VARIABLE, "").strip(),
        values.get(KEY_PARAM_VARIABLE, "").strip() or KEY_PARAMS[0],
    )


@dataclass(frozen=True)
class OrganizationCoverage:
    """기관 하나의 수집 상태. 레코드 없음을 집행 없음으로 읽지 않도록 상태를 구분한다."""

    slug: str
    name: str
    status: Literal["collected", "empty", "held"]
    record_count: int
    hold_reason: HoldReason | None = None


def coverage(
    organizations: tuple[Organization, ...], records: tuple[Record, ...]
) -> tuple[OrganizationCoverage, ...]:
    """수집 상태는 선언한 보류 사유와 이번 빌드의 레코드 유무에서 계산한다."""
    counts = Counter(record.organization for record in records)
    return tuple(
        OrganizationCoverage(
            slug=organization.slug,
            name=organization.name,
            status=(
                "held"
                if organization.hold_reason is not None
                else "collected"
                if counts[organization.slug]
                else "empty"
            ),
            record_count=counts[organization.slug],
            hold_reason=organization.hold_reason,
        )
        for organization in organizations
    )


def coordinate_source(result: GeocodeResult) -> Provider:
    """좌표를 준 제공자. 사람이 확인한 건은 확인한 후보의 제공자가 정본이다."""
    if result.confirmation is not None:
        return result.confirmation.candidate_source.provider
    providers = sorted(
        {
            candidate.source.provider
            for candidate in result.lookup.candidates
            if (candidate.latitude, candidate.longitude) == (result.latitude, result.longitude)
        }
    )
    if not providers:
        raise ValueError("a confirmed coordinate must come from one of its candidates")
    # 여러 제공자의 근거가 같은 좌표로 겹치면 이름 순으로 하나를 밝힌다.
    return providers[0]


def published_record(
    record: Record, classification: ClassificationStatus, geocode: GeocodeResult | None
) -> PublishedRecord:
    """장부는 마커가 되지 못한 레코드도 판정 상태·사유와 함께 보존한다."""
    fields = record.model_dump(mode="json")
    for provenance in ("source_hash", "source_location"):
        fields.pop(provenance)
    if classification != "restaurant":
        return PublishedRecord.model_validate(
            {**fields, "classification": classification, "map_status": classification}
        )
    if geocode is None:
        raise ValueError("a restaurant record must carry its geocoding result")
    return PublishedRecord.model_validate(
        {
            **fields,
            "classification": classification,
            "map_status": "mapped" if geocode.status == "success" else "geocode_failed",
            "geocode_reason": geocode.reason,
            "business_id": geocode.business_id,
        }
    )


def write_site_shell(
    output_root: Path,
    city: City,
    city_directory: Path,
    map_key: MapKey,
    collection: tuple[OrganizationCoverage, ...],
) -> tuple[Path, ...]:
    """Write shared assets, the city landing, and one city entry page."""
    written: list[Path] = []
    city_page = city_directory / "index.html"
    write_text(city_page, _city_page(city, map_key, collection))
    written.append(city_page)

    # 진입 페이지를 먼저 쓰고 랜딩을 만들어, 이번 실행의 도시도 링크 대상이 되게 한다.
    landing = output_root / "index.html"
    write_text(landing, _landing_page(output_root))
    written.append(landing)

    asset_root = output_root / "assets"
    packaged_assets = files("deliciousmap.site_assets")
    for name in ASSET_NAMES:
        path = asset_root / name
        write_text(path, packaged_assets.joinpath(name).read_text(encoding="utf-8"))
        written.append(path)

    manifest = output_root / "manifest.webmanifest"
    write_text(
        manifest,
        packaged_assets.joinpath("manifest.webmanifest").read_text(encoding="utf-8"),
    )
    written.append(manifest)
    service_worker = output_root / "sw.js"
    write_text(service_worker, packaged_assets.joinpath("sw.js").read_text(encoding="utf-8"))
    written.append(service_worker)
    return tuple(written)


def _landing_page(output_root: Path) -> str:
    """빌드된 도시만 링크한다. 아직 만들지 않은 도시를 열 수 있는 것처럼 보이지 않게 한다."""
    cards = "\n".join(_city_card(city, output_root) for city in CITIES)
    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#173f35">
    <meta property="og:title" content="공무원 맛집 지도">
    <meta property="og:description" content="업무추진비 레코드에서 자주 찾은 식당을 확인하세요.">
    <title>공무원 맛집 지도</title>
    <link rel="manifest" href="./manifest.webmanifest">
    <link rel="stylesheet" href="./assets/styles.css">
  </head>
  <body class="landing-page">
    <main class="landing-shell">
      <p class="eyebrow">{REPORTING_PERIOD} 업무추진비</p>
      <h1>어느 도시의 맛집을 찾으세요?</h1>
      <p class="lede">공개된 레코드를 모아 공무원이 자주 찾은 식당을 보여줍니다.</p>
      <nav class="city-grid" aria-label="도시 선택">
{cards}
      </nav>
    </main>
  </body>
</html>
"""


def _map_notice(collection: tuple[OrganizationCoverage, ...]) -> str:
    """수집 보류가 있을 때만 지도 위에 짧게 알린다. 없으면 안내를 두지 않는다."""
    held = [item for item in collection if item.status == "held"]
    if not collection:
        message = "이 도시는 아직 수집 대상 기관이 선언되지 않았습니다."
    elif held:
        message = (
            f"수집 보류 기관 {len(held)}곳이 있어 비어 있는 지역이 집행 없음을 뜻하지 않습니다."
        )
    else:
        return ""
    return f"""          <p class="collection-warning map-warning" data-collection-hold>
            {escape(message)}
          </p>"""


def _collection_table(collection: tuple[OrganizationCoverage, ...]) -> str:
    """기관별 수집 상태. 선언된 기관이 없으면 그 사실을 그대로 적는다."""
    if not collection:
        return "      <p>등록된 수집 대상 기관이 없습니다.</p>"
    rows = "\n".join(
        f'          <tr><th scope="row">{escape(item.name)}</th>'
        f"<td>{COLLECTION_LABELS[item.status]}</td>"
        f"<td>{escape(_collection_detail(item))}</td></tr>"
        for item in collection
    )
    return f"""      <table class="collection-table">
        <thead>
          <tr><th scope="col">기관</th><th scope="col">상태</th><th scope="col">내용</th></tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>"""


def _collection_detail(item: OrganizationCoverage) -> str:
    if item.status == "held":
        return HOLD_REASON_LABELS[item.hold_reason] if item.hold_reason else "사유 미기재"
    if item.status == "collected":
        return f"레코드 {item.record_count:,}건"
    return "이번 빌드에 레코드 없음"


def _city_card(city: City, output_root: Path) -> str:
    name = escape(city.name)
    if not (output_root / city.slug / "index.html").is_file():
        return (
            '          <p class="city-card is-pending">'
            f"<strong>{name}</strong><span>준비 중</span></p>"
        )
    return (
        f'          <a class="city-card" href="./{city.slug}/">'
        f"<strong>{name}</strong><span>지도 열기</span></a>"
    )


def _city_page(city: City, map_key: MapKey, collection: tuple[OrganizationCoverage, ...]) -> str:
    city_name = escape(city.name)
    config = json.dumps(
        {
            "city": city.slug,
            "map_bounds": asdict(city.map_bounds),
            "naver_map_client_id": map_key.client_id,
            "naver_map_key_param": map_key.key_param,
            "site_root": SITE_ROOT,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).replace("<", r"\u003c")
    return f"""<!doctype html>
<html lang="ko" data-city="{city.slug}"
      data-markers-url="./markers.json" data-records-url="./records.json">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <meta name="theme-color" content="#173f35">
    <meta property="og:title" content="{city_name} 공무원 맛집 지도">
    <meta property="og:description"
          content="{city_name} 업무추진비 레코드에서 자주 찾은 식당을 확인하세요.">
    <title>{city_name} 공무원 맛집 지도</title>
    <link rel="manifest" href="{SITE_ROOT}manifest.webmanifest">
    <link rel="stylesheet" href="{SITE_ROOT}assets/styles.css">
  </head>
  <body class="city-page">
    <header class="topbar">
      <a class="back-link" href="{SITE_ROOT}" aria-label="도시 선택으로 돌아가기">← 도시</a>
      <div><p class="eyebrow">{REPORTING_PERIOD}</p><h1>{city_name}</h1></div>
      <button class="source-button" type="button" data-open-sources>자료 범위</button>
    </header>
    <nav class="tabs" aria-label="화면 선택">
      <button type="button" role="tab" aria-selected="true" data-tab="map">지도</button>
      <button type="button" role="tab" aria-selected="false" data-tab="records">장부</button>
    </nav>
    <main>
      <section class="map-panel" data-panel="map">
        <form class="search-panel" data-search-form>
          <label class="search-field"><span class="sr-only">식당명 검색</span>
            <input type="search" name="query" placeholder="식당명 검색" autocomplete="off">
          </label>
          <fieldset class="visit-filters"><legend class="sr-only">방문 횟수</legend>
            <button type="button" aria-pressed="true" data-visits="all">전체</button>
            <button type="button" aria-pressed="false" data-visits="20">20+</button>
            <button type="button" aria-pressed="false" data-visits="10">10–19</button>
            <button type="button" aria-pressed="false" data-visits="5">5–9</button>
            <button type="button" aria-pressed="false" data-visits="1">1–4</button>
          </fieldset>
          <p class="result-count" aria-live="polite">
            <strong data-total-count>0</strong>곳 전체 ·
            <strong data-viewport-count>—</strong>곳 현재 지도 영역
          </p>
          <div class="search-results" data-search-results hidden></div>
{_map_notice(collection)}
        </form>
        <div id="map" class="map" aria-label="{city_name} 식당 지도">
          <p class="loading">지도를 준비하고 있습니다.</p>
        </div>
        <aside class="restaurant-sheet" data-restaurant-sheet hidden></aside>
      </section>
      <section class="records-panel" data-panel="records" hidden>
        <header><p class="eyebrow">마커가 없는 레코드도 포함</p><h2>전체 장부</h2></header>
        <p class="loading" data-records-status>장부 탭을 열면 레코드를 불러옵니다.</p>
        <div class="records-list" data-records-list></div>
        <button class="more-button" type="button" data-records-more hidden>다음 레코드 보기</button>
      </section>
    </main>
    <dialog class="source-dialog" data-source-dialog>
      <button type="button" class="dialog-close" data-close-sources aria-label="닫기">×</button>
      <p class="eyebrow">자료 범위</p><h2>대상 기간 {REPORTING_PERIOD}</h2>
{_collection_table(collection)}
      <p class="collection-warning">
        레코드 없음과 수집 보류는 집행이 없었다는 뜻이 아닙니다.
      </p>
    </dialog>
    <script id="site-config" type="application/json">{config}</script>
    <script src="{SITE_ROOT}assets/app.js" defer></script>
  </body>
</html>
"""
