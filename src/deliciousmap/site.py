"""dist/에 공개하는 것의 단일 출처. 정제 산출물에서 데이터 파일과 정적 화면을 낸다."""

import json
import os
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from html import escape
from importlib.resources import files
from pathlib import Path
from typing import Literal

from deliciousmap import period
from deliciousmap.contracts import (
    BuildInput,
    ClassificationStatus,
    Contract,
    ExcludedSources,
    GeocodeReason,
    GeocodeResult,
    MarkerFile,
    Provider,
    PublishedMarker,
    PublishedRecord,
    Record,
    RecordFile,
    RepeatedExpenses,
    SourceFinding,
    SubmissionTally,
    UnresolvedReason,
)
from deliciousmap.registry import CITIES, City, HoldReason, Organization, Target
from deliciousmap.storage import write_bytes, write_text

ASSET_NAMES = ("app.js", "styles.css")
# 앱 아이콘. `scripts/make_icons.py`로 만든 PNG를 그대로 낸다. 크기는 manifest의 선언과 같다.
ICON_NAMES = ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png")
# 도시 전체 build가 도시마다 내는 화면과 두 데이터 파일.
CITY_FILES = ("index.html", "markers.json", "records.json")
REPORTING_PERIOD = period.LABEL
# 수집 보류 사유의 화면 표기. 사유 자체의 단일 출처는 레지스트리다.
HOLD_REASON_LABELS: dict[HoldReason, str] = {
    "bot_blocked": "봇 차단",
    "drm": "DRM",
    "board_lost": "게시판 유실",
    "below_threshold": "공개 기준 미달",
}
COLLECTION_LABELS = {"collected": "수집 완료", "empty": "레코드 없음", "held": "수집 보류"}
# 사람이 원본과 대조해 확정한 원본 자체의 결함. 사유 자체의 단일 출처는 계약이다.
SOURCE_FINDING_LABELS: dict[SourceFinding, str] = {
    "merchant_blank": "상호 빈칸",
    "total_mismatch": "합계 불일치",
}
# 원본을 끝내 읽지 못한 사유의 화면 표기. 사유를 적지 않고 수만 내면 무엇이 남았는지 알 수 없다.
UNRESOLVED_REASON_LABELS: dict[UnresolvedReason, str] = {
    "unsupported_format": "지원하지 않는 형식",
    "unreadable": "읽지 못함",
    "unsupported_layout": "지원하지 않는 배치",
    "no_table": "표 없음",
    "model_not_configured": "모델 미설정",
    "unavailable": "호출 장애",
    "invalid_response": "잘못된 응답",
    "incomplete_response": "잘린 응답",
    "oversized_request": "요청 크기 초과",
    "budget_exhausted": "예산 소진",
    "unknown_prior_usage": "기존 사용액 미확인",
    "concurrent_execution": "동시 실행",
    "validation_failed": "검증 실패",
    "no_candidates": "후보 없음",
}
# 좌표를 확정하지 못한 사유의 화면 표기. 장부(app.js의 `GEOCODE_REASONS`)와 같은 말을 쓴다.
GEOCODE_REASON_LABELS: dict[GeocodeReason, str] = {
    "no_candidates": "후보 없음",
    "missing_address": "주소 근거 없음",
    "unknown_branch": "지점 미확인",
    "conflicting_evidence": "근거 충돌",
    "ambiguous": "후보 모호",
    "unconfirmed_name": "상호 미확인",
    "no_match": "일치 후보 없음",
    "missing_coordinates": "좌표 없음",
    "lookup_error": "조회 실패",
    "insufficient_evidence": "근거 부족",
    "merged_merchant": "합쳐 적은 상호",
}
# 방문 구간: (키, 필터 버튼, 범례). 필터·범례·마커 색이 같은 구간을 쓴다. 판정은 app.js가 한다.
VISIT_BAND_LABELS = (
    ("20", "20+", "20회 이상"),
    ("10", "10–19", "10–19회"),
    ("5", "5–9", "5–9회"),
    ("1", "1–4", "1–4회"),
)
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


def public_paths(city_slugs: Iterable[str]) -> frozenset[str]:
    """도시 전체 build가 `dist/`에 내는 공개 파일 전부. 배포 검사는 이것만 허용한다."""
    assets = (*ASSET_NAMES, *ICON_NAMES)
    shell = {"index.html", "manifest.webmanifest", "sw.js", *(f"assets/{n}" for n in assets)}
    return frozenset({*shell, *(f"{slug}/{name}" for slug in city_slugs for name in CITY_FILES)})


def map_key_from_environment(environ: Mapping[str, str] | None = None) -> MapKey:
    """값은 어디에도 출력하지 않고 변수 이름만 알린다."""
    values = os.environ if environ is None else environ
    return MapKey(
        values.get(CLIENT_ID_VARIABLE, "").strip(),
        values.get(KEY_PARAM_VARIABLE, "").strip() or KEY_PARAMS[0],
    )


@dataclass(frozen=True)
class CollectionStatus:
    """기관 하나의 수집 상태. 레코드 없음을 집행 없음으로 읽지 않도록 상태를 구분한다."""

    slug: str
    name: str
    status: Literal["collected", "empty", "held"]
    record_count: int
    hold_reason: HoldReason | None = None


@dataclass(frozen=True)
class SourceScope:
    """화면이 밝히는 이번 제출의 범위. 읽은 수만 내면 장부가 완전해 보인다.

    `excluded`는 기간으로 뺀 원본, `repeated`는 누적 재게시로 합쳐 장부에서 뺀 수다.
    """

    targets: int
    excluded: ExcludedSources
    repeated: RepeatedExpenses
    # 제출 시점 기준이 공개하는 남은 미해결(#106). 세지 않은 값은 0으로 내지 않는다.
    tally: SubmissionTally = SubmissionTally()

    @property
    def total(self) -> int:
        return self.targets + self.excluded.total


def collection_status(
    organizations: tuple[Organization, ...], records: tuple[Record, ...]
) -> tuple[CollectionStatus, ...]:
    """수집 상태는 선언한 보류 사유와 이번 빌드의 레코드 유무에서 계산한다."""
    counts = Counter(record.organization for record in records)
    return tuple(
        CollectionStatus(
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


def write_city_data(directory: Path, target: Target, value: BuildInput) -> tuple[Path, ...]:
    """지도용 축약 마커와 전체 장부를 따로 낸다. 두 파일의 건수는 다를 수 있다."""
    marker_path = directory / "markers.json"
    _write_json(marker_path, _marker_file(target, value))
    record_path = directory / "records.json"
    _write_json(record_path, _record_file(target, value))
    return (marker_path, record_path)


def _write_json(path: Path, content: Contract) -> None:
    payload = content.model_dump(mode="json")
    write_text(path, json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _marker_file(target: Target, value: BuildInput) -> MarkerFile:
    closures = {item.business_id: item for item in value.closures}
    geocodes = {item.record_id: item for item in value.geocodes}
    records = {item.record_id: item for item in value.records}
    markers = []
    for candidate in value.candidates:
        # 묶인 레코드는 같은 좌표를 공유하므로 첫 레코드의 근거로 출처와 주소를 밝힌다.
        source, address = _coordinate_origin(geocodes[candidate.record_ids[0]])
        visits = [records[record_id] for record_id in candidate.record_ids]
        priced = [visit.amount_krw for visit in visits if visit.amount_krw is not None]
        markers.append(
            PublishedMarker(
                business_id=candidate.business_id,
                merchant=candidate.merchant,
                visit_count=len(candidate.record_ids),
                latitude=candidate.latitude,
                longitude=candidate.longitude,
                closed=closures[candidate.business_id].status == "closed",
                coordinate_source=source,
                address=address,
                last_visited_on=max(visit.spent_on for visit in visits),
                total_amount_krw=sum(priced, Decimal(0)),
                unpriced_visit_count=len(visits) - len(priced),
                organizations=tuple(sorted({visit.organization for visit in visits})),
            )
        )
    return MarkerFile(city=target.city.slug, org=target.org, markers=tuple(markers))


def _record_file(target: Target, value: BuildInput) -> RecordFile:
    decisions = {item.record_id: item for item in value.decisions}
    geocodes = {item.record_id: item for item in value.geocodes}
    return RecordFile(
        city=target.city.slug,
        org=target.org,
        records=tuple(
            _published_record(
                record,
                decisions[record.record_id].status,
                geocodes.get(record.record_id),
            )
            for record in value.records
        ),
    )


def _coordinate_origin(result: GeocodeResult) -> tuple[Provider, str]:
    """좌표를 준 제공자와 그 근거의 주소. 사람이 확인한 건은 확인한 후보와 주소가 정본이다.

    업소 확인은 상호·지점·주소가 일치한 후보만 채택하므로(`identity.decide_identity`) 주소 없는
    후보는 좌표의 근거가 될 수 없다.
    """
    if result.reason == "human_confirmed" and result.confirmation is not None:
        return result.confirmation.candidate_source.provider, result.confirmation.address
    # 여러 제공자의 근거가 같은 좌표로 겹치면 제공자 이름 순으로 하나를 밝힌다.
    origins = sorted(
        (candidate.source.provider, candidate.address)
        for candidate in result.lookup.candidates
        if (candidate.latitude, candidate.longitude) == (result.latitude, result.longitude)
        and candidate.address is not None
    )
    if not origins:
        raise ValueError("a confirmed coordinate must come from one of its candidates")
    return origins[0]


def _published_record(
    record: Record, classification: ClassificationStatus, geocode: GeocodeResult | None
) -> PublishedRecord:
    """장부는 마커가 되지 못한 레코드도 판정 상태·사유와 함께 보존한다."""
    fields = record.model_dump(mode="json")
    for provenance in ("source_hash", "source_location", "repeats", "expense"):
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
    statuses: tuple[CollectionStatus, ...],
    scope: SourceScope,
) -> tuple[Path, ...]:
    """Write shared assets, the city landing, and one city entry page."""
    written: list[Path] = []
    city_page = city_directory / "index.html"
    write_text(city_page, _city_page(city, map_key, statuses, scope))
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
    # 텍스트 자산은 읽을 때 줄바꿈이 LF로 맞춰진다. 아이콘은 바이트를 그대로 옮긴다.
    for name in ICON_NAMES:
        path = asset_root / name
        write_bytes(path, packaged_assets.joinpath(name).read_bytes())
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


def _icon_links(root: str) -> str:
    """manifest와 아이콘. iPhone Safari는 manifest 아이콘 대신 apple-touch-icon을 홈 화면에 쓴다."""
    return f"""    <link rel="manifest" href="{root}manifest.webmanifest">
    <link rel="icon" type="image/png" sizes="192x192" href="{root}assets/icon-192.png">
    <link rel="apple-touch-icon" href="{root}assets/apple-touch-icon.png">"""


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
{_icon_links("./")}
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
{_install_guide()}
    <script id="site-config" type="application/json">{json.dumps({"site_root": "./"})}</script>
    <script src="./assets/app.js" defer></script>
  </body>
</html>
"""


def _install_guide() -> str:
    """홈 화면 설치 안내의 자리. 문구와 표시 여부는 브라우저에 따라 app.js가 정한다."""
    return """    <aside class="install-guide" data-install-guide aria-label="앱 설치 안내" hidden>
      <p data-install-message></p>
      <button class="install-accept" type="button" data-install-accept hidden>설치</button>
      <button class="install-dismiss" type="button" data-install-dismiss
              aria-label="설치 안내 닫기">×</button>
    </aside>"""


def _map_notice(statuses: tuple[CollectionStatus, ...]) -> str:
    """수집 보류가 있을 때만 지도 위에 짧게 알린다. 없으면 안내를 두지 않는다."""
    held = [item for item in statuses if item.status == "held"]
    if not held:
        return ""
    message = f"수집 보류 기관 {len(held)}곳이 있어 비어 있는 지역이 집행 없음을 뜻하지 않습니다."
    return f"""            <p class="collection-warning map-warning" data-collection-hold>
              {escape(message)}
            </p>"""


def _visit_filters() -> str:
    buttons = [
        '            <button type="button" aria-pressed="true" data-visits="all">전체</button>',
        *(
            f'            <button type="button" aria-pressed="false" data-visits="{key}">'
            f"{label}</button>"
            for key, label, _ in VISIT_BAND_LABELS
        ),
    ]
    return "\n".join(buttons)


def _map_legend() -> str:
    items = "\n".join(
        f'              <li><span class="legend-swatch band-{key}"></span>{label}</li>'
        for key, _, label in VISIT_BAND_LABELS
    )
    return f"""            <div class="map-legend" aria-label="마커 색 범례">
              <p>방문 횟수</p>
              <ul>
{items}
              <li><span class="legend-swatch is-closed"></span>폐업</li>
              </ul>
            </div>"""


def _collection_table(statuses: tuple[CollectionStatus, ...]) -> str:
    """기관별 수집 상태. 선언된 기관이 없으면 그 사실을 그대로 적는다."""
    if not statuses:
        return "      <p>등록된 수집 대상 기관이 없습니다.</p>"
    rows = "\n".join(
        f'          <tr><th scope="row">{escape(item.name)}</th>'
        f"<td>{COLLECTION_LABELS[item.status]}</td>"
        f"<td>{escape(_collection_detail(item))}</td></tr>"
        for item in statuses
    )
    return f"""      <table class="collection-table">
        <thead>
          <tr><th scope="col">기관</th><th scope="col">상태</th><th scope="col">내용</th></tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>"""


def _collection_detail(item: CollectionStatus) -> str:
    if item.hold_reason is not None:
        return HOLD_REASON_LABELS[item.hold_reason]
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


def _scope_line(scope: SourceScope) -> str:
    """원본을 세지 않은 산출물에는 줄을 내지 않는다. 0개라고 적으면 없는 사실을 지어내는 것이다."""
    if scope.total == 0:
        return ""
    return (
        '\n      <p class="collection-scope">'
        f"게시글 원본 {scope.total:,}개 중 대상 {scope.targets:,}개"
        f" (기간 미표기 제외 {scope.excluded.undeclared_in_year:,}개)</p>"
    )


def _repeated_expense_line(repeated: RepeatedExpenses) -> str:
    """누적 재게시로 장부에서 뺀 수. 밝히지 않으면 건수가 조용히 줄어든 것으로 보인다.

    기준은 [ADR-0004](../../docs/adr/0004-merge-repeated-reposts.md)이다. 합친 것도 남긴 것도
    없으면 낼 말이 없어 줄을 내지 않는다. `parse` v3는 언제나 세므로(`extract.merge_repeats`)
    그 경우는 세지 않은 산출물이 아니라 반복이 없었다는 뜻이다. 한쪽이라도 있으면 나머지 0은
    센 뒤의 사실이므로 감추지 않는다.

    한 묶음이 언제나 한 건으로 줄지는 않는다. 남는 건수는 한 원본이 적은 최대 건수이므로,
    합친 묶음 수와 장부에서 뺀 레코드 수를 따로 낸다.

    사람이 원본을 대조해 확정한 수는 따로 낸다([ADR-0006](
    ../../docs/adr/0006-human-confirmed-reposts.md)). 확정이 없으면 그 말은 내지 않는다 —
    기준이 센 수만으로 장부가 다 설명되고, 하지 않은 검토의 0건은 군말이다.
    """
    if repeated == RepeatedExpenses():
        return ""
    merged = (
        "부서가 이미 공개한 기간을 다시 올려 같은 지출이 여러 원본에 반복된 "
        f"{repeated.merged_expenses:,}묶음을 합쳐,"
        f" 장부에서 {repeated.merged_records:,}건을 뺐습니다."
        if repeated.merged_expenses
        else "부서가 이미 공개한 기간을 다시 올려 반복된 지출 가운데 합친 것은 없습니다."
    )
    left = (
        "다시 올린 것인지 따로 쓴 것인지 가를 근거가 없어 남긴 "
        f"{repeated.unmerged_expenses:,}묶음 {repeated.unmerged_records:,}건은"
        " 장부에 중복으로 보일 수 있습니다."
        if repeated.unmerged_expenses
        else "다시 올린 것인지 따로 쓴 것인지 가를 근거가 없어 남긴 묶음은 없습니다."
    )
    return f'\n      <p class="collection-scope">{merged}{_confirmed_line(repeated)} {left}</p>'


def _confirmed_line(repeated: RepeatedExpenses) -> str:
    """사람이 확정해 합친 수와 남긴 수. 확정한 것이 없으면 낼 말이 없다(ADR-0006)."""
    said = ""
    if repeated.confirmed_expenses:
        said += (
            f" 원본을 다시 대조해 같은 지출로 확정한 {repeated.confirmed_expenses:,}묶음"
            f" {repeated.confirmed_records:,}건도 함께 뺐습니다."
        )
    if repeated.separate_expenses:
        said += (
            f" 원본을 다시 대조해 별개 지출로 확정한 {repeated.separate_expenses:,}묶음"
            f" {repeated.separate_records:,}건은 장부에 그대로 남습니다."
        )
    return said


def _tally_lines(tally: SubmissionTally) -> str:
    """제출 시점 기준이 공개하는 남은 미해결(#106). 세지 않은 값은 줄을 내지 않는다."""
    return "".join(
        f'\n      <p class="collection-scope">{line}</p>'
        for line in (
            _unresolved_source_line(tally),
            _unmapped_record_line(tally),
            _unsplit_expense_line(tally),
        )
        if line
    )


def _unsplit_expense_line(tally: SubmissionTally) -> str:
    """상호 칸에 업소 둘 이상이 적혀 업소별로 가르지 못한 지출(#117).

    사람이 확인해야 업소마다 갈리므로 확인 전에는 한 레코드로 둔다. 수를 밝히지 않으면 그
    지출들이 업소 하나짜리 레코드로 읽힌다. 지도에 오르지 못한 수는 여기서 말하지 않는다 —
    비식당·판단 보류도, 구분자가 있어도 확정된 레코드도 이 수에 들어 있기 때문이다. 좌표를
    확정하지 못한 수는 `합쳐 적은 상호` 사유로 위 줄이 따로 낸다. 가르지 못한 지출이 없으면
    낼 말이 없어 줄을 내지 않는다.
    """
    if not tally.unsplit_expenses:
        return ""
    return (
        f"상호 칸에 업소 둘 이상이 적힌 지출 {tally.unsplit_expenses:,}건은 사람 확인 전이라"
        " 업소별로 가르지 못하고 레코드 하나로 남습니다."
    )


def _unresolved_source_line(tally: SubmissionTally) -> str:
    """원본 결함 확정과 그 밖의 미해결 원본. 원본을 세지 않은 산출물에는 낼 말이 없다.

    사람이 원본과 대조해 원본 자체의 결함으로 확정한 원본만 따로 센다. 대조가 없으면 사유가
    같아도 미해결이므로, 아직 확정한 원본이 없다는 것도 밝힌다 — 읽지 못한 원본이 남아 있는데
    이 줄이 없으면 대조를 마친 것처럼 읽힌다. 미해결이 0개인 것도 센 뒤의 사실이므로 감추지
    않는다. 확정할 원본도 미해결도 없으면 대조 자체가 할 일이 아니라 그 말을 내지 않는다.
    이 공개가 [#9](https://github.com/snowjaewon/OfficialDeliciousMap/issues/9)의 0개 기준을
    대신하지는 않는다.
    """
    if not tally.counted_sources:
        return ""
    said = ""
    if tally.confirmed_defects:
        confirmed = sum(item.sources for item in tally.confirmed_defects)
        detail = " · ".join(
            f"{SOURCE_FINDING_LABELS[item.finding]} {item.sources:,}개"
            f"(지출 후보 {item.candidates:,}건)"
            for item in tally.confirmed_defects
        )
        said += (
            f"사람이 원본과 대조해 원본 자체의 결함으로 확정한 원본 {confirmed:,}개는"
            f" 레코드를 내지 않습니다: {detail}. "
        )
    elif tally.unresolved_sources:
        said += "사람이 원본과 대조해 원본 자체의 결함으로 확정한 원본은 아직 없습니다. "
    if not tally.unresolved_sources:
        return f"{said}아직 확정하지 못해 미해결로 남은 원본은 없습니다."
    remaining = sum(item.sources for item in tally.unresolved_sources)
    detail = " · ".join(
        f"{UNRESOLVED_REASON_LABELS[item.reason]} {item.sources:,}개"
        f"({_candidate_text(item.candidates)})"
        for item in tally.unresolved_sources
    )
    return f"{said}아직 확정하지 못해 미해결로 남은 원본 {remaining:,}개: {detail}."


def _candidate_text(count: int | None) -> str:
    """후보 수를 모르는 원본이 섞이면 알 수 없음으로 적는다. 0건 손실로 보고하지 않는다."""
    return "지출 후보 수 알 수 없음" if count is None else f"지출 후보 {count:,}건"


def _unmapped_record_line(tally: SubmissionTally) -> str:
    """지도에 오르지 못한 레코드. 밝히지 않으면 장부가 지도와 같아 보인다(#106)."""
    if not tally.classified_records:
        return ""
    parts = []
    if tally.pending_records:
        parts.append(f"식당 여부를 가르지 못한 판단 보류 {tally.pending_records:,}건")
    if tally.unconfirmed_places:
        unconfirmed = sum(item.records for item in tally.unconfirmed_places)
        detail = " · ".join(
            f"{GEOCODE_REASON_LABELS[item.reason]} {item.records:,}건"
            for item in tally.unconfirmed_places
        )
        parts.append(
            f"식당 {tally.restaurant_records:,}건 가운데"
            f" 좌표를 확정하지 못한 {unconfirmed:,}건({detail})"
        )
    if not parts:
        return "판단 보류와 좌표 미확정 없이 모든 레코드를 판정했습니다."
    return f"{' · '.join(parts)}은 지도에 오르지 못하고 장부에만 남습니다."


def _city_page(
    city: City, map_key: MapKey, statuses: tuple[CollectionStatus, ...], scope: SourceScope
) -> str:
    city_name = escape(city.name)
    scope_lines = (
        f"{_scope_line(scope)}{_repeated_expense_line(scope.repeated)}{_tally_lines(scope.tally)}"
    )
    config = json.dumps(
        {
            "city": city.slug,
            # 장부는 레코드의 기관 slug를 담으므로 화면에서 쓸 이름을 함께 내려 준다.
            "organizations": {item.slug: item.name for item in statuses},
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
{_icon_links(SITE_ROOT)}
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
        <div class="map-stage">
          <div id="map" class="map" aria-label="{city_name} 식당 지도">
            <p class="loading">지도를 준비하고 있습니다.</p>
          </div>
          <div class="map-overlay">
{_map_notice(statuses)}
{_map_legend()}
          </div>
        </div>
        <aside class="list-panel" data-list-panel data-sheet="collapsed" aria-label="식당 목록">
          <button class="sheet-handle" type="button" data-sheet-handle
                  aria-label="목록 높이 바꾸기"></button>
          <form class="search-panel" data-search-form>
            <label class="search-field"><span class="sr-only">식당명 검색</span>
              <input type="search" name="query" placeholder="식당명 검색" autocomplete="off">
            </label>
            <fieldset class="visit-filters"><legend class="sr-only">방문 횟수</legend>
{_visit_filters()}
            </fieldset>
            <p class="result-count" aria-live="polite">
              <strong data-total-count>0</strong>곳 전체 ·
              <strong data-viewport-count>—</strong>곳 현재 지도 영역
            </p>
          </form>
          <div class="list-view" data-list-view>
            <ol class="restaurant-list" data-restaurant-list></ol>
            <button class="more-button" type="button" data-restaurant-more hidden>
              다음 식당 보기
            </button>
          </div>
          <article class="restaurant-detail" data-restaurant-detail hidden></article>
        </aside>
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
{_collection_table(statuses)}{scope_lines}
      <p class="collection-warning">
        레코드 없음과 수집 보류는 집행이 없었다는 뜻이 아닙니다.
      </p>
    </dialog>
{_install_guide()}
    <script id="site-config" type="application/json">{config}</script>
    <script src="{SITE_ROOT}assets/app.js" defer></script>
  </body>
</html>
"""
