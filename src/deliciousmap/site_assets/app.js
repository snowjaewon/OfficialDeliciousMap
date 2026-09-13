"use strict";

(function expose(factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof window !== "undefined" && window.document) {
    window.addEventListener("DOMContentLoaded", () => {
      api.start(window).catch((error) => {
        const status = window.document.querySelector("#map .loading");
        if (status) status.textContent = "지도 데이터를 불러오지 못했습니다.";
        window.console.error(error);
      });
    });
  }
})(function createApp() {
  const VISIT_BANDS = {
    all: () => true,
    20: (count) => count >= 20,
    10: (count) => count >= 10 && count <= 19,
    5: (count) => count >= 5 && count <= 9,
    1: (count) => count >= 1 && count <= 4,
  };
  // 마커 색과 범례가 쓰는 구간. 필터와 같은 구간을 많은 쪽부터 적는다.
  const BAND_ORDER = ["20", "10", "5", "1"];
  // 목록은 한 번에 이만큼 그린다. 서울처럼 식당이 많아도 첫 목록이 늦지 않게 한다.
  const LIST_BATCH = 50;
  // 첫 화면의 확대 상한. 몇 곳만 모여 있어도 동네가 보이는 수준에서 멈춘다.
  const INITIAL_ZOOM_LIMIT = 14;
  // 첫 화면에서 양끝을 뺄 비율. 식당이 이보다 적으면 모두 담는다.
  const OUTLIER_SHARE = 0.05;
  const OUTLIER_MINIMUM = 20;
  const SHEET_STATES = ["collapsed", "half", "full"];
  // 이만큼 움직여야 시트 손잡이를 끈 것으로 본다(화소).
  const DRAG_THRESHOLD = 6;

  // 좌표를 준 자료의 이름. 지도에서 모양으로 구분하지 않고 상세에서만 밝힌다.
  const COORDINATE_SOURCES = {
    local: "담당자 준비 자료",
    naver: "네이버 지역검색",
    license: "인허가 자료",
  };

  // 마커가 되지 못한 이유. 판정 상태만으로는 알 수 없는 사유를 장부에서 함께 밝힌다.
  const GEOCODE_REASONS = {
    no_candidates: "후보 없음",
    missing_address: "주소 근거 없음",
    unknown_branch: "지점 미확인",
    conflicting_evidence: "근거 충돌",
    ambiguous: "후보 모호",
    unconfirmed_name: "상호 미확인",
    no_match: "일치 후보 없음",
    missing_coordinates: "좌표 없음",
    lookup_error: "조회 실패",
    insufficient_evidence: "근거 부족",
  };

  const INSTALL_GUIDE_KEY = "deliciousmap:install-guide";
  const INSTALL_MESSAGES = {
    offer: "앱으로 설치하면 홈 화면에서 바로 열 수 있습니다.",
    safari: "Safari의 공유 메뉴에서 ‘홈 화면에 추가’를 누르면 앱처럼 열 수 있습니다.",
  };
  const OTHER_IOS_BROWSERS = /CriOS|FxiOS|EdgiOS|OPiOS|KAKAOTALK|NAVER|DaumApps|Instagram|FBAN|FBAV|Line\//;

  const MAP_STATUSES = {
    mapped: "지도 표시",
    geocode_failed: "지오코딩 실패",
    non_restaurant: "비식당",
    pending: "판단 보류",
  };

  function recordState(record) {
    const status = MAP_STATUSES[record.map_status];
    const reason = GEOCODE_REASONS[record.geocode_reason];
    return record.map_status === "geocode_failed" && reason ? `${status} · ${reason}` : status;
  }

  // 원본이 상호 끝에 이름 없이 수만 밝힌 업소. 이름이 없어 조회조차 하지 못한다(#127).
  function unnamedCompanionNote(record) {
    const unnamed = record.unnamed_companions;
    if (unnamed === null) return "이름 없는 동행 업소 수 미상";
    return unnamed > 0 ? `이름 없는 동행 업소 ${unnamed.toLocaleString("ko-KR")}곳` : "";
  }

  function normalizeSearch(value) {
    return String(value).normalize("NFKC").trim().toLocaleLowerCase("ko-KR");
  }

  function selectedVisitBands(visitBands) {
    if (visitBands === "all" || visitBands === undefined || visitBands === null) return [];
    const values =
      visitBands instanceof Set ? [...visitBands] : Array.isArray(visitBands) ? visitBands : [visitBands];
    for (const band of values) {
      if (band === "all" || !Object.hasOwn(VISIT_BANDS, band)) throw new Error("unknown visit band");
    }
    return values;
  }

  function filterMarkers(markers, query, visitBands) {
    const normalizedQuery = normalizeSearch(query);
    const selected = selectedVisitBands(visitBands);
    return markers.filter(
      (marker) =>
        (selected.length === 0 || selected.some((band) => VISIT_BANDS[band](marker.visit_count))) &&
        normalizeSearch(marker.merchant).includes(normalizedQuery),
    );
  }

  function setupVisitFilters(documentObject, onChange = () => {}) {
    const selected = new Set();
    const buttons = [...documentObject.querySelectorAll("[data-visits]")];

    function syncButtons() {
      for (const button of buttons) {
        button.setAttribute(
          "aria-pressed",
          String(button.dataset.visits === "all" ? selected.size === 0 : selected.has(button.dataset.visits)),
        );
      }
    }

    for (const button of buttons) {
      button.addEventListener("click", (event) => {
        const band = button.dataset.visits;
        if (band === "all") selected.clear();
        else if (selected.has(band)) selected.delete(band);
        else selected.add(band);
        syncButtons();
        onChange(event);
      });
    }
    syncButtons();
    return selected;
  }

  function visitBand(count) {
    return BAND_ORDER.find((band) => VISIT_BANDS[band](count));
  }

  function rankMarkers(markers) {
    return [...markers].sort(
      (left, right) =>
        right.visit_count - left.visit_count ||
        left.merchant.localeCompare(right.merchant, "ko-KR") ||
        String(left.business_id).localeCompare(String(right.business_id)),
    );
  }

  function percentile(sorted, share) {
    return sorted[Math.round(share * (sorted.length - 1))];
  }

  // 첫 화면은 도시 안의 식당이 모인 영역이다. 식당이 많으면 양끝의 먼 곳을 빼고 잡는다.
  function initialViewBounds(markers, cityBounds) {
    const inside = markers.filter((marker) => markerInBounds(marker, cityBounds));
    if (inside.length === 0) return undefined;
    const share = inside.length >= OUTLIER_MINIMUM ? OUTLIER_SHARE : 0;
    const latitudes = inside.map((marker) => marker.latitude).sort((a, b) => a - b);
    const longitudes = inside.map((marker) => marker.longitude).sort((a, b) => a - b);
    return {
      south: percentile(latitudes, share),
      west: percentile(longitudes, share),
      north: percentile(latitudes, 1 - share),
      east: percentile(longitudes, 1 - share),
    };
  }

  // 웹 메르카토르에서 화소만큼 남쪽의 위도. 지도를 가린 시트 위에 식당이 오도록 중심을 내린다.
  function latitudeSouthOf(latitude, zoom, pixels) {
    if (!pixels) return latitude;
    const degreesPerPixel = (360 / (256 * 2 ** zoom)) * Math.cos((latitude * Math.PI) / 180);
    return latitude - pixels * degreesPerPixel;
  }

  function nearestSheetState(visible, heights) {
    return SHEET_STATES.reduce((best, state) =>
      Math.abs(heights[state] - visible) < Math.abs(heights[best] - visible) ? state : best,
    );
  }

  function countMarkersInBounds(markers, bounds) {
    return markers.filter((marker) => markerInBounds(marker, bounds)).length;
  }

  function markerInBounds(marker, bounds) {
    return (
      marker.latitude >= bounds.south &&
      marker.latitude <= bounds.north &&
      marker.longitude >= bounds.west &&
      marker.longitude <= bounds.east
    );
  }

  function createRecordsLoader(fetchRecords) {
    let request;
    return function loadRecords(...args) {
      if (!request) {
        request = Promise.resolve()
          .then(() => fetchRecords(...args))
          .catch((error) => {
            request = undefined;
            throw error;
          });
      }
      return request;
    };
  }

  function recordMetric(windowObject, name, startedAt) {
    const entry = {
      name,
      duration_ms: Number((windowObject.performance.now() - startedAt).toFixed(2)),
    };
    const metrics = windowObject.deliciousmapMetrics || [];
    metrics.push(entry);
    windowObject.deliciousmapMetrics = metrics.slice(-200);
    windowObject.dispatchEvent(new windowObject.CustomEvent("deliciousmap:metric", { detail: entry }));
  }

  function summarizeMetrics(metrics, name) {
    const durations = metrics
      .filter((entry) => entry.name === name && Number.isFinite(entry.duration_ms))
      .map((entry) => entry.duration_ms)
      .sort((left, right) => right - left);
    return {
      count: durations.length,
      maximum_ms: durations[0] ?? null,
      second_slowest_ms: durations[1] ?? null,
    };
  }

  function interactionStartedAt(windowObject, event) {
    const timestamp = event?.domEvent?.timeStamp ?? event?.timeStamp;
    const now = windowObject.performance.now();
    if (!Number.isFinite(timestamp)) return now;
    if (timestamp >= 0 && timestamp <= now + 1000) return timestamp;
    const relative = timestamp - (windowObject.performance.timeOrigin || 0);
    return relative >= 0 && relative <= now + 1000 ? relative : now;
  }

  function recordMetricAfterPaint(windowObject, name, startedAt) {
    return new Promise((resolve) => {
      windowObject.requestAnimationFrame(() => {
        windowObject.requestAnimationFrame(() => {
          recordMetric(windowObject, name, startedAt);
          resolve();
        });
      });
    });
  }

  async function fetchJson(windowObject, url) {
    const response = await windowObject.fetch(url);
    if (!response.ok) throw new Error(`request failed: ${response.status}`);
    return response.json();
  }

  function readConfig(documentObject) {
    const element = documentObject.getElementById("site-config");
    if (!element) throw new Error("site configuration is missing");
    return JSON.parse(element.textContent);
  }

  function switchTab(documentObject, selected) {
    for (const tab of documentObject.querySelectorAll("[data-tab]")) {
      tab.setAttribute("aria-selected", String(tab.dataset.tab === selected));
    }
    for (const panel of documentObject.querySelectorAll("[data-panel]")) {
      panel.hidden = panel.dataset.panel !== selected;
    }
  }

  function setupSourceDialog(documentObject) {
    const dialog = documentObject.querySelector("[data-source-dialog]");
    documentObject.querySelector("[data-open-sources]")?.addEventListener("click", () => {
      dialog.showModal();
    });
    documentObject.querySelector("[data-close-sources]")?.addEventListener("click", () => {
      dialog.close();
    });
  }

  function renderRecords(documentObject, records, organizations = {}) {
    const list = documentObject.querySelector("[data-records-list]");
    const status = documentObject.querySelector("[data-records-status]");
    const more = documentObject.querySelector("[data-records-more]");
    const batchSize = 100;
    let shown = 0;

    function appendBatch() {
      const fragment = documentObject.createDocumentFragment();
      for (const record of records.slice(shown, shown + batchSize)) {
        const article = documentObject.createElement("article");
        article.className = "record-card";
        const heading = documentObject.createElement("h3");
        heading.textContent = record.merchant;
        const summary = documentObject.createElement("p");
        const amount = new Intl.NumberFormat("ko-KR").format(Number(record.amount_krw));
        const organization = organizations[record.organization] ?? record.organization;
        summary.textContent = `${record.spent_on} · ${organization} · ${amount}원`;
        const purpose = documentObject.createElement("p");
        purpose.textContent = record.purpose || "목적 미기재";
        const state = documentObject.createElement("span");
        state.className = `record-state state-${record.map_status}`;
        state.textContent = recordState(record);
        article.append(heading, summary, purpose, state);
        const unnamed = unnamedCompanionNote(record);
        if (unnamed) article.append(textElement(documentObject, "p", "record-companions", unnamed));
        fragment.append(article);
      }
      shown = Math.min(shown + batchSize, records.length);
      list.append(fragment);
      more.hidden = shown >= records.length;
      status.textContent = `전체 ${records.length.toLocaleString("ko-KR")}건 · ${shown.toLocaleString("ko-KR")}건 표시`;
    }

    more.addEventListener("click", appendBatch);
    appendBatch();
  }

  function textElement(documentObject, tagName, className, text) {
    const element = documentObject.createElement(tagName);
    element.className = className;
    element.textContent = text;
    return element;
  }

  function restaurantItem(documentObject, marker, rank, onSelect) {
    const item = documentObject.createElement("li");
    const button = documentObject.createElement("button");
    button.type = "button";
    button.className = "restaurant-item";
    const body = documentObject.createElement("span");
    body.className = "item-body";
    body.append(
      textElement(documentObject, "strong", "item-name", marker.merchant),
      textElement(documentObject, "span", "item-address", marker.address),
    );
    if (marker.closed) body.append(textElement(documentObject, "span", "closed-tag", "폐업"));
    button.append(
      textElement(documentObject, "span", "item-rank", String(rank)),
      body,
      textElement(
        documentObject,
        "span",
        `visit-badge band-${visitBand(marker.visit_count)}`,
        `${marker.visit_count.toLocaleString("ko-KR")}회`,
      ),
    );
    button.addEventListener("click", (event) => onSelect(marker, event));
    item.append(button);
    return item;
  }

  // 받은 순서 그대로 목록을 그린다. 순서는 호출하는 쪽이 rankMarkers로 매겨 넘긴다.
  // 방문 횟수가 같으면 같은 순위다. 이름순은 보이는 순서일 뿐 순위가 아니다.
  function renderRestaurantList(documentObject, markers, onSelect) {
    const list = documentObject.querySelector("[data-restaurant-list]");
    const more = documentObject.querySelector("[data-restaurant-more]");
    const listView = documentObject.querySelector("[data-list-view]");
    let shown = 0;
    let rank = 0;

    function appendBatch() {
      const fragment = documentObject.createDocumentFragment();
      for (let index = shown; index < Math.min(shown + LIST_BATCH, markers.length); index += 1) {
        if (index === 0 || markers[index - 1].visit_count !== markers[index].visit_count) {
          rank = index + 1;
        }
        fragment.append(restaurantItem(documentObject, markers[index], rank, onSelect));
      }
      shown = Math.min(shown + LIST_BATCH, markers.length);
      list.append(fragment);
      more.hidden = shown >= markers.length;
    }

    list.replaceChildren();
    if (listView) {
      listView.scrollTop = 0;
      listView.savedScrollTop = 0;
    }
    // 다시 그릴 때마다 새 목록의 더 보기로 바꾼다. 리스너를 쌓으면 한 번에 여러 묶음이 붙는다.
    more.onclick = appendBatch;
    if (markers.length === 0) {
      list.append(textElement(documentObject, "li", "list-empty", "조건에 맞는 식당이 없습니다."));
      more.hidden = true;
      return;
    }
    appendBatch();
  }

  function showRestaurantList(documentObject) {
    const detail = documentObject.querySelector("[data-restaurant-detail]");
    const listView = documentObject.querySelector("[data-list-view]");
    if (detail) detail.hidden = true;
    if (listView?.hidden) {
      listView.hidden = false;
      // 숨겼던 목록은 스크롤 위치를 잃는다. 상세를 열기 전에 보던 자리로 돌린다.
      listView.scrollTop = listView.savedScrollTop ?? 0;
    }
  }

  function loadNaverMaps(windowObject, config) {
    if (windowObject.naver?.maps) return Promise.resolve(windowObject.naver.maps);
    if (!config.naver_map_client_id) {
      return Promise.reject(new Error("NAVER_MAP_CLIENT_ID is not configured"));
    }
    return new Promise((resolve, reject) => {
      const script = windowObject.document.createElement("script");
      const parameter = encodeURIComponent(config.naver_map_key_param);
      const key = encodeURIComponent(config.naver_map_client_id);
      script.src = `https://oapi.map.naver.com/openapi/v3/maps.js?${parameter}=${key}`;
      script.onload = () =>
        windowObject.naver?.maps
          ? resolve(windowObject.naver.maps)
          : reject(new Error("Naver Maps did not initialize"));
      script.onerror = () => reject(new Error("Naver Maps could not be loaded"));
      windowObject.document.head.append(script);
    });
  }

  function naverBoundsToPlain(bounds) {
    const southWest = bounds.getSW();
    const northEast = bounds.getNE();
    return {
      south: southWest.lat(),
      west: southWest.lng(),
      north: northEast.lat(),
      east: northEast.lng(),
    };
  }

  function viewportBounds(mapState) {
    // 지도 인증·초기화가 끝나기 전이나 실패한 뒤에는 현재 영역을 알 수 없다.
    if (!mapState) return undefined;
    try {
      return naverBoundsToPlain(mapState.map.getBounds());
    } catch (error) {
      return undefined;
    }
  }

  function markerIcon(naverMaps, marker) {
    const classes = ["map-marker", `band-${visitBand(marker.visit_count)}`];
    if (marker.closed) classes.push("is-closed");
    if (marker.selected) classes.push("is-selected");
    return {
      content: `<button class="${classes.join(" ")}" type="button" aria-label="식당 마커"><span>${marker.visit_count}</span></button>`,
      anchor: new naverMaps.Point(22, 22),
    };
  }

  function formatWon(amount) {
    return `${new Intl.NumberFormat("ko-KR").format(Number(amount))}원`;
  }

  function renderRestaurant(documentObject, marker, withinCity, organizations = {}) {
    const detail = documentObject.querySelector("[data-restaurant-detail]");
    const close = textElement(documentObject, "button", "detail-close", "← 목록");
    close.type = "button";
    close.addEventListener("click", () => showRestaurantList(documentObject));
    const visits = `방문 ${marker.visit_count.toLocaleString("ko-KR")}회`;
    const names = marker.organizations.map((slug) => organizations[slug] ?? slug);
    const children = [
      close,
      textElement(documentObject, "h2", "detail-name", marker.merchant),
      textElement(
        documentObject,
        "p",
        "detail-visits",
        `${visits} · 합계 ${formatWon(marker.total_amount_krw)}`,
      ),
      textElement(documentObject, "p", "detail-address", marker.address),
      textElement(documentObject, "p", "detail-line", `최근 방문 ${marker.last_visited_on}`),
      textElement(documentObject, "p", "detail-line", `방문 기관 ${names.join(", ")}`),
    ];
    children.push(
      textElement(
        documentObject,
        "p",
        marker.closed ? "closed-state" : "open-state",
        marker.closed ? "폐업 확인" : "폐업 확인 없음",
      ),
    );
    if (!withinCity) {
      children.push(
        textElement(documentObject, "p", "outside-city", "도시 지도 범위 밖의 식당입니다."),
      );
    }
    children.push(
      textElement(
        documentObject,
        "p",
        "coordinate-source",
        `좌표 출처: ${COORDINATE_SOURCES[marker.coordinate_source] ?? "미상"}`,
      ),
    );
    const link = textElement(documentObject, "a", "naver-link", "네이버 지도에서 확인");
    link.href = `https://map.naver.com/p/search/${encodeURIComponent(marker.merchant)}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    children.push(link);
    detail.replaceChildren(...children);
    detail.scrollTop = 0;
    detail.hidden = false;
    const listView = documentObject.querySelector("[data-list-view]");
    // 상세끼리 옮겨 다닐 때는 이미 숨긴 목록의 위치를 덮어쓰지 않는다.
    if (listView && !listView.hidden) {
      listView.savedScrollTop = listView.scrollTop;
      listView.hidden = true;
    }
  }

  function selectMarker(windowObject, documentObject, config, mapState, marker, event) {
    const startedAt = interactionStartedAt(windowObject, event);
    const withinCity = markerInBounds(marker, config.map_bounds);
    renderRestaurant(documentObject, marker, withinCity, config.organizations);
    if (mapState && withinCity) {
      try {
        const zoom = Math.max(mapState.map.getZoom(), 16);
        // 모바일 시트가 지도 아래를 가리면 그 절반만큼 중심을 내려 식당을 보이는 곳에 둔다.
        const covered = mapState.coveredBottom?.() ?? 0;
        // panTo 뒤에 setZoom을 부르면 이동이 끊겨 원래 중심에서 확대된다. 좌표와 줌을 한 번에 옮긴다.
        mapState.map.morph(
          new mapState.naverMaps.LatLng(
            latitudeSouthOf(marker.latitude, zoom, covered / 2),
            marker.longitude,
          ),
          zoom,
        );
      } catch (error) {
        // 지도를 움직이지 못해도 선택한 식당의 상세는 그대로 보여 준다.
        windowObject.console.error(error);
      }
    }
    return recordMetricAfterPaint(windowObject, "marker-selection", startedAt);
  }

  function toNaverBounds(naverMaps, { south, west, north, east }) {
    return new naverMaps.LatLngBounds(
      new naverMaps.LatLng(south, west),
      new naverMaps.LatLng(north, east),
    );
  }

  // 도시 전체는 축소 한계로 남기고, 첫 화면은 식당이 모인 영역으로 옮긴다. 식당이 없으면 옮기지 않는다.
  function showInitialView(naverMaps, map, config, markers, bottomInset) {
    const initial = initialViewBounds(markers, config.map_bounds);
    if (!initial) return;
    const edge = 48;
    map.fitBounds(toNaverBounds(naverMaps, initial), {
      top: edge,
      right: edge,
      bottom: edge + bottomInset,
      left: edge,
    });
    if (map.getZoom() > INITIAL_ZOOM_LIMIT) map.setZoom(INITIAL_ZOOM_LIMIT, false);
  }

  function createMap(
    windowObject,
    naverMaps,
    config,
    markers,
    onViewportChange,
    onSelect,
    { bottomInset = 0, onClearSelection = () => {} } = {},
  ) {
    const documentObject = windowObject.document;
    const cityBounds = toNaverBounds(naverMaps, config.map_bounds);
    const mapElement = documentObject.getElementById("map");
    mapElement.replaceChildren();
    const map = new naverMaps.Map(mapElement, {
      bounds: cityBounds,
      maxBounds: cityBounds,
      zoomControl: false,
    });

    let markReady;
    const ready = new Promise((resolve) => {
      markReady = resolve;
    });
    let selectedMarkerKey;
    const topMarkerZIndex =
      markers.reduce((highest, marker) => Math.max(highest, marker.visit_count), 0) + 1;
    const overlays = markers.map((data) => {
      const overlay = new naverMaps.Marker({
        map,
        position: new naverMaps.LatLng(data.latitude, data.longitude),
        icon: markerIcon(naverMaps, data),
        title: data.merchant,
        // 방문이 많은 식당이 겹친 마커 위에 온다.
        zIndex: data.visit_count,
      });
      naverMaps.Event.addListener(overlay, "click", (event) => {
        setMarkerSelection(data);
        onSelect(data, event);
      });
      return { data, overlay };
    });

    function setMarkerSelection(markerOrId) {
      selectedMarkerKey =
        markerOrId === undefined
          ? undefined
          : typeof markerOrId === "object"
            ? (markerOrId.business_id ?? markerOrId)
            : markerOrId;
      for (const item of overlays) {
        const selected = (item.data.business_id ?? item.data) === selectedMarkerKey;
        const icon = markerIcon(naverMaps, { ...item.data, selected });
        if (typeof item.overlay.setIcon === "function") item.overlay.setIcon(icon);
        else item.overlay.options.icon = icon;
        const zIndex = selected ? topMarkerZIndex : item.data.visit_count;
        if (typeof item.overlay.setZIndex === "function") item.overlay.setZIndex(zIndex);
        else item.overlay.options.zIndex = zIndex;
      }
    }

    function clearSelection() {
      if (selectedMarkerKey === undefined) return;
      setMarkerSelection(undefined);
      onClearSelection();
    }

    naverMaps.Event.addListener(map, "click", clearSelection);

    const reportViewport = () => onViewportChange(naverBoundsToPlain(map.getBounds()));
    // SDK는 첫 화면에서 idle 없이 init만 보낸다. 도시 전체가 보이는 이 시점에 축소 한계를 고정한다.
    naverMaps.Event.addListener(map, "init", () => {
      map.setOptions({ minZoom: map.getZoom(), maxBounds: cityBounds });
      showInitialView(naverMaps, map, config, markers, bottomInset);
      reportViewport();
      markReady();
    });
    naverMaps.Event.addListener(map, "idle", reportViewport);
    map.fitBounds(cityBounds);
    return { map, overlays, ready, setMarkerSelection, clearSelection };
  }

  // 목록 시트를 끌어 세 높이 중 가까운 곳에 놓는다. 넓은 화면에서는 목록이 지도 옆이라 하는 일이 없다.
  // 시트인지는 styles.css가 손잡이를 보이는지로 안다. 폭 기준을 한 곳에만 둔다.
  function setupListSheet(windowObject, documentObject) {
    const panel = documentObject.querySelector("[data-list-panel]");
    const handle = documentObject.querySelector("[data-sheet-handle]");
    const header = documentObject.querySelector("[data-search-form]");
    const active = () =>
      Boolean(panel && header && handle) &&
      windowObject.getComputedStyle(handle).display !== "none";
    let state = "collapsed";
    let drag;
    let draggedLast = false;

    function heights() {
      const full = panel.offsetHeight;
      const collapsed = Math.min(full, handle.offsetHeight + header.offsetHeight);
      return { collapsed, half: Math.max(collapsed, Math.round(full * 0.5)), full };
    }

    function settle(next, measuredHeights) {
      state = next;
      // 장부 탭처럼 지도가 숨어 있으면 높이를 잴 수 없다. 0으로 적으면 시트가 화면 밖으로 사라진다.
      if (!active()) return;
      const dimensions = measuredHeights ?? heights();
      if (!measuredHeights && panel.offsetHeight === 0) return;
      panel.dataset.sheet = next;
      panel.style.setProperty("--sheet-visible", `${dimensions[next]}px`);
    }

    // 창 폭이 바뀌어 시트가 되었다 말았다 할 수 있으므로 리스너는 늘 두고 누를 때 확인한다.
    if (panel && header && handle) {
      const startDrag = (event, source) => {
        if (!active()) return;
        // 검색 입력·필터 버튼은 브라우저의 입력/클릭을 그대로 둔다. 손잡이는 예외다.
        if (source !== handle && event.target?.closest?.("input, button, label")) return;
        // 끌기 뒤에 click이 오지 않는 기기도 있다. 새로 누를 때마다 지난 끌기를 잊는다.
        draggedLast = false;
        const measuredHeights = heights();
        drag = {
          startY: event.clientY,
          startVisible: measuredHeights[state],
          visible: undefined,
          heights: measuredHeights,
        };
        source.setPointerCapture?.(event.pointerId);
        panel.classList.add("is-dragging");
      };
      const moveDrag = (event) => {
        // 손가락이 조금 떨린 것은 끌기가 아니라 누르기다.
        if (!drag || Math.abs(event.clientY - drag.startY) < DRAG_THRESHOLD) return;
        const { collapsed, full } = drag.heights;
        const visible = drag.startVisible + (drag.startY - event.clientY);
        drag.visible = Math.min(full, Math.max(collapsed, visible));
        panel.style.setProperty("--sheet-visible", `${drag.visible}px`);
      };
      const finish = () => {
        if (!drag) return;
        const measuredHeights = drag.heights;
        panel.classList.remove("is-dragging");
        // 조금도 끌지 않았으면 누른 것이다. 그때는 뒤따르는 click이 높이를 바꾼다.
        draggedLast = drag.visible !== undefined;
        settle(draggedLast ? nearestSheetState(drag.visible, measuredHeights) : state, measuredHeights);
        drag = undefined;
      };
      for (const source of [handle, header]) {
        source.addEventListener("pointerdown", (event) => startDrag(event, source));
        source.addEventListener("pointermove", moveDrag);
        source.addEventListener("pointerup", finish);
        source.addEventListener("pointercancel", finish);
      }
      // 누르거나 키보드로 고르면 한 단계씩 올리고, 가장 높으면 접는다.
      handle.addEventListener("click", () => {
        if (!active()) return;
        if (draggedLast) {
          draggedLast = false;
          return;
        }
        settle(SHEET_STATES[(SHEET_STATES.indexOf(state) + 1) % SHEET_STATES.length]);
      });
    }
    windowObject.addEventListener?.("resize", () => settle(state));
    settle(state);

    return {
      // 시트를 적어도 이 높이까지 올린다. 이미 더 높으면 그대로 둔다.
      raise(next) {
        if (SHEET_STATES.indexOf(next) > SHEET_STATES.indexOf(state)) settle(next);
      },
      state: () => state,
      restore(next) {
        if (SHEET_STATES.includes(next)) settle(next);
      },
      // 지도 탭으로 돌아오면 숨어 있는 동안 바뀐 창 크기에 높이를 다시 맞춘다.
      refresh: () => settle(state),
      coveredBottom: () => (active() ? heights()[state] : 0),
      collapsedHeight: () => (active() ? heights().collapsed : 0),
    };
  }

  // 끝난 설치 안내(닫았거나, 설치 창에서 거절했거나, Safari 안내를 한 번 보였음)는 이 브라우저의
  // 저장소에만 기억한다. 저장소를 못 쓰면 다음 화면에서 다시 보일 수 있지만 지금 화면은 닫힌다.
  function installGuideDone(windowObject) {
    try {
      return windowObject.localStorage.getItem(INSTALL_GUIDE_KEY) === "done";
    } catch (error) {
      return false;
    }
  }

  function rememberInstallGuideDone(windowObject) {
    try {
      windowObject.localStorage.setItem(INSTALL_GUIDE_KEY, "done");
    } catch (error) {
      // 기억하지 못해도 지금 화면의 안내는 그대로 다룬다.
    }
  }

  // 홈 화면 앱으로 열렸는지. iPhone Safari는 navigator.standalone으로, 나머지는 표시 방식으로 안다.
  function openedAsApp(windowObject) {
    return (
      windowObject.navigator.standalone === true ||
      Boolean(windowObject.matchMedia?.("(display-mode: standalone)").matches)
    );
  }

  // 공유 메뉴의 "홈 화면에 추가"를 쓰는 iOS Safari. 데스크톱 사이트를 요청한 iPad는 Mac처럼 보이지만
  // 터치가 있다. 다른 iOS 브라우저와 앱 안 브라우저는 메뉴가 달라 Safari 안내가 맞지 않는다.
  function isIosSafari(navigatorObject) {
    const agent = navigatorObject.userAgent || "";
    const ios =
      /iPhone|iPad|iPod/.test(agent) ||
      (/Macintosh/.test(agent) && navigatorObject.maxTouchPoints > 1);
    return ios && /Version\/[\d.]+.*Safari\//.test(agent) && !OTHER_IOS_BROWSERS.test(agent);
  }

  // 홈 화면 설치 안내. Android Chrome은 설치 제안 이벤트를 받아 버튼으로 설치 창을 열고,
  // 그 이벤트가 없는 iOS Safari에는 공유 메뉴에서 추가하는 방법을 알린다.
  function setupInstallGuide(windowObject) {
    const documentObject = windowObject.document;
    const guide = documentObject.querySelector("[data-install-guide]");
    const message = documentObject.querySelector("[data-install-message]");
    const accept = documentObject.querySelector("[data-install-accept]");
    const dismiss = documentObject.querySelector("[data-install-dismiss]");
    if (!guide || !message || !accept || !dismiss || openedAsApp(windowObject)) return;
    let offer;

    function show(text) {
      message.textContent = text;
      guide.hidden = false;
    }

    function hide() {
      offer = undefined;
      guide.hidden = true;
    }

    windowObject.addEventListener("beforeinstallprompt", (event) => {
      // 닫은 사람에게도 브라우저의 기본 설치 안내를 띄우지 않도록 늘 막는다.
      event.preventDefault();
      if (installGuideDone(windowObject)) return;
      offer = event;
      accept.hidden = false;
      show(INSTALL_MESSAGES.offer);
    });
    // 브라우저 메뉴로 설치해도 이 화면의 버튼은 쓸모가 없어진다. 설치한 동안은 Chrome이 설치 제안을
    // 다시 보내지 않으므로 기억하지 않는다. 기억하면 앱을 지운 뒤에도 안내가 돌아오지 않는다.
    windowObject.addEventListener("appinstalled", hide);
    accept.addEventListener("click", async () => {
      if (!offer) return;
      // 설치 제안은 한 번만 쓸 수 있다.
      const pending = offer;
      hide();
      await pending.prompt();
      const choice = await pending.userChoice;
      if (choice.outcome === "dismissed") rememberInstallGuideDone(windowObject);
    });
    dismiss.addEventListener("click", () => {
      rememberInstallGuideDone(windowObject);
      hide();
    });
    // Safari 안내는 한 번만 보인다. 본 화면에서는 닫을 때까지 남는다.
    if (isIosSafari(windowObject.navigator) && !installGuideDone(windowObject)) {
      show(INSTALL_MESSAGES.safari);
      rememberInstallGuideDone(windowObject);
    }
  }

  function registerServiceWorker(windowObject) {
    if (!("serviceWorker" in windowObject.navigator)) return;
    const config = readConfig(windowObject.document);
    const url = new URL(`${config.site_root}sw.js`, windowObject.location.href);
    windowObject.navigator.serviceWorker
      .register(url, { scope: config.site_root })
      .catch(() => {});
  }

  async function start(windowObject) {
    const documentObject = windowObject.document;
    const root = documentObject.documentElement;
    // 설치 안내와 service worker는 랜딩에도 둔다. 설치한 앱의 시작 주소가 랜딩이다.
    setupInstallGuide(windowObject);
    registerServiceWorker(windowObject);
    if (!root.dataset.city) return;

    const config = readConfig(documentObject);
    windowObject.deliciousmapMetricsSummary = (name) =>
      summarizeMetrics(windowObject.deliciousmapMetrics || [], name);
    setupSourceDialog(documentObject);

    const mapApiRequest = loadNaverMaps(windowObject, config).then(
      (naverMaps) => ({ naverMaps }),
      (error) => ({ error }),
    );
    const markerStartedAt = windowObject.performance.now();
    const markerPayload = await fetchJson(windowObject, root.dataset.markersUrl);
    if (!Array.isArray(markerPayload.markers)) throw new Error("invalid marker data");
    recordMetric(windowObject, "marker-data", markerStartedAt);
    // 한 번 순위를 매겨 두면 검색·필터 결과도 그 순서를 그대로 따른다.
    const allMarkers = rankMarkers(markerPayload.markers);
    const totalCount = documentObject.querySelector("[data-total-count]");
    const viewportCount = documentObject.querySelector("[data-viewport-count]");
    const search = documentObject.querySelector('[name="query"]');
    const sheet = setupListSheet(windowObject, documentObject);
    let filtered = allMarkers;
    let mapState;
    let mapUnusable = false;
    let selectedMarker;
    let selectionSheetState;

    function selectMarkerFromPage(marker, event) {
      if (selectedMarker === undefined) selectionSheetState = sheet.state();
      selectedMarker = marker;
      mapState?.setMarkerSelection(marker);
      // 상세가 보이도록 시트를 먼저 올린다. 지도는 올린 시트가 가린 만큼을 비켜 식당을 보인다.
      sheet.raise("half");
      void selectMarker(windowObject, documentObject, config, mapState, marker, event);
    }

    function clearSelectionFromPage() {
      selectedMarker = undefined;
      showRestaurantList(documentObject);
      if (selectionSheetState !== undefined) sheet.restore(selectionSheetState);
      selectionSheetState = undefined;
    }

    function updateCounts(bounds) {
      // 도시 전체 결과는 지도와 무관하게 언제나 센다. 알 수 없는 현재 영역은 0으로 적지 않는다.
      totalCount.textContent = filtered.length.toLocaleString("ko-KR");
      viewportCount.textContent = bounds
        ? countMarkersInBounds(filtered, bounds).toLocaleString("ko-KR")
        : "—";
    }

    function syncMap() {
      updateCounts(viewportBounds(mapState));
      if (!mapState) return;
      const visible = new Set(filtered.map((marker) => marker.business_id));
      try {
        for (const item of mapState.overlays) {
          item.overlay.setMap(visible.has(item.data.business_id) ? mapState.map : null);
        }
      } catch (error) {
        windowObject.console.error(error);
      }
    }

    function applyFilters() {
      // 검색·필터 결과와 집계는 지도가 없어도 도시 전체를 대상으로 먼저 반영한다.
      filtered = filterMarkers(allMarkers, search.value, selectedBands);
      renderRestaurantList(documentObject, filtered, selectMarkerFromPage);
      // 조건을 바꾸면 보고 있던 상세 대신 바뀐 목록을 보인다.
      showRestaurantList(documentObject);
      syncMap();
    }

    function reportUnusableMap(error) {
      // 지도를 쓸 수 없다는 사실을 숨기지 않는다. 검색·집계·장부는 계속 제공한다.
      mapUnusable = true;
      mapState = undefined;
      const message = documentObject.createElement("p");
      message.className = "map-error";
      message.textContent =
        "네이버 지도 설정을 확인해 주세요. 검색 집계와 장부는 계속 볼 수 있습니다.";
      documentObject.getElementById("map").replaceChildren(message);
      windowObject.console.error(error);
      syncMap();
    }

    // 키가 잘못되면 SDK는 내려받아지지만 지도는 동작하지 않는다. 공식 훅으로 그 사실을 받는다.
    windowObject.navermap_authFailure = () =>
      reportUnusableMap(new Error("Naver Maps authentication failed"));

    documentObject.querySelector("[data-search-form]").addEventListener("submit", (event) => {
      event.preventDefault();
    });
    search.addEventListener("input", (event) => {
      const startedAt = interactionStartedAt(windowObject, event);
      // 접힌 시트에서 글자를 치면 결과가 보이게 올린다.
      sheet.raise("half");
      applyFilters();
      void recordMetricAfterPaint(windowObject, "filter-result", startedAt);
    });
    const selectedBands = setupVisitFilters(documentObject, (event) => {
      const startedAt = interactionStartedAt(windowObject, event);
      applyFilters();
      void recordMetricAfterPaint(windowObject, "filter-result", startedAt);
    });
    // 목록은 지도를 기다리지 않는다. 지도가 늦거나 실패해도 식당을 둘러볼 수 있다.
    applyFilters();

    const loadRecords = createRecordsLoader(async (startedAt) => {
      const status = documentObject.querySelector("[data-records-status]");
      status.textContent = "장부를 불러오고 있습니다.";
      const payload = await fetchJson(windowObject, root.dataset.recordsUrl);
      if (!Array.isArray(payload.records)) throw new Error("invalid record data");
      renderRecords(documentObject, payload.records, config.organizations);
      await recordMetricAfterPaint(windowObject, "records-first-list", startedAt);
      return payload;
    });
    for (const tab of documentObject.querySelectorAll("[data-tab]")) {
      tab.addEventListener("click", async (event) => {
        const startedAt = interactionStartedAt(windowObject, event);
        switchTab(documentObject, tab.dataset.tab);
        if (tab.dataset.tab === "map") sheet.refresh();
        if (tab.dataset.tab === "records") {
          try {
            await loadRecords(startedAt);
          } catch (error) {
            documentObject.querySelector("[data-records-status]").textContent =
              "장부를 불러오지 못했습니다. 다시 시도해 주세요.";
            windowObject.console.error(error);
          }
        }
      });
    }

    try {
      const mapApi = await mapApiRequest;
      if (mapApi.error) throw mapApi.error;
      // 인증 실패가 지도를 만들기 전에 오면 만들지 않는다. 만든 자리를 다시 덮어쓰지 않기 위해서다.
      if (mapUnusable) throw new Error("Naver Maps authentication failed");
      const created = createMap(
        windowObject,
        mapApi.naverMaps,
        config,
        allMarkers,
        updateCounts,
        selectMarkerFromPage,
        {
          bottomInset: sheet.collapsedHeight(),
          onClearSelection: clearSelectionFromPage,
        },
      );
      mapState = {
        ...created,
        naverMaps: mapApi.naverMaps,
        coveredBottom: sheet.coveredBottom,
      };
      if (selectedMarker !== undefined) created.setMarkerSelection(selectedMarker);
      await created.ready;
      // 기다리는 동안 인증이 실패했으면 안내는 이미 떠 있다.
      if (mapUnusable) return;
      // 보고 있던 상세를 닫지 않고, 지도가 생기기 전의 검색·필터를 마커에 반영한다.
      syncMap();
      await recordMetricAfterPaint(windowObject, "first-ready", 0);
    } catch (error) {
      reportUnusableMap(error);
    }
  }

  return {
    latitudeSouthOf,
    countMarkersInBounds,
    createMap,
    createRecordsLoader,
    filterMarkers,
    initialViewBounds,
    markerIcon,
    markerInBounds,
    nearestSheetState,
    rankMarkers,
    recordState,
    renderRecords,
    renderRestaurantList,
    selectMarker,
    setupInstallGuide,
    setupListSheet,
    setupVisitFilters,
    start,
    summarizeMetrics,
    viewportBounds,
    visitBand,
  };
});
