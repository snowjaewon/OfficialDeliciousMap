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

  function normalizeSearch(value) {
    return String(value).normalize("NFKC").trim().toLocaleLowerCase("ko-KR");
  }

  function filterMarkers(markers, query, visitBand) {
    const normalizedQuery = normalizeSearch(query);
    const matchesVisits = VISIT_BANDS[visitBand];
    if (!matchesVisits) throw new Error("unknown visit band");
    return markers.filter(
      (marker) =>
        matchesVisits(marker.visit_count) &&
        normalizeSearch(marker.merchant).includes(normalizedQuery),
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

  function renderRecords(documentObject, records) {
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
        summary.textContent = `${record.spent_on} · ${record.organization} · ${amount}원`;
        const purpose = documentObject.createElement("p");
        purpose.textContent = record.purpose || "목적 미기재";
        const state = documentObject.createElement("span");
        state.className = `record-state state-${record.map_status}`;
        state.textContent = recordState(record);
        article.append(heading, summary, purpose, state);
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

  function renderSearchResults(documentObject, markers, query, onSelect) {
    const results = documentObject.querySelector("[data-search-results]");
    if (!normalizeSearch(query)) {
      results.replaceChildren();
      results.hidden = true;
      return;
    }

    const fragment = documentObject.createDocumentFragment();
    if (markers.length === 0) {
      const empty = documentObject.createElement("p");
      empty.textContent = "검색 결과가 없습니다.";
      fragment.append(empty);
    }
    for (const marker of markers.slice(0, 20)) {
      const button = documentObject.createElement("button");
      button.type = "button";
      button.className = "search-result";
      button.textContent = `${marker.merchant} · 방문 ${marker.visit_count.toLocaleString("ko-KR")}회`;
      button.addEventListener("click", (event) => onSelect(marker, event));
      fragment.append(button);
    }
    results.replaceChildren(fragment);
    results.hidden = false;
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
    const className = marker.closed ? "map-marker is-closed" : "map-marker";
    return {
      content: `<button class="${className}" type="button" aria-label="식당 마커"><span>${marker.visit_count}</span></button>`,
      anchor: new naverMaps.Point(22, 22),
    };
  }

  function renderRestaurant(documentObject, marker, withinCity) {
    const sheet = documentObject.querySelector("[data-restaurant-sheet]");
    const heading = documentObject.createElement("h2");
    heading.textContent = marker.merchant;
    const visits = documentObject.createElement("p");
    visits.textContent = `방문 ${marker.visit_count.toLocaleString("ko-KR")}회`;
    const closure = documentObject.createElement("p");
    closure.className = marker.closed ? "closed-state" : "open-state";
    closure.textContent = marker.closed ? "폐업 확인" : "폐업 확인 없음";
    const origin = documentObject.createElement("p");
    origin.className = "coordinate-source";
    origin.textContent = `좌표 출처: ${COORDINATE_SOURCES[marker.coordinate_source] ?? "미상"}`;
    const link = documentObject.createElement("a");
    link.href = `https://map.naver.com/p/search/${encodeURIComponent(marker.merchant)}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "네이버 지도에서 확인";
    const children = [heading, visits, closure, origin, link];
    if (!withinCity) {
      const boundaryNotice = documentObject.createElement("p");
      boundaryNotice.className = "outside-city";
      boundaryNotice.textContent = "도시 지도 범위 밖의 식당입니다.";
      children.splice(3, 0, boundaryNotice);
    }
    sheet.replaceChildren(...children);
    sheet.hidden = false;
  }

  function selectMarker(windowObject, documentObject, config, mapState, marker, event) {
    const startedAt = interactionStartedAt(windowObject, event);
    const withinCity = markerInBounds(marker, config.map_bounds);
    renderRestaurant(documentObject, marker, withinCity);
    if (mapState && withinCity) {
      try {
        mapState.map.panTo(new mapState.naverMaps.LatLng(marker.latitude, marker.longitude));
        mapState.map.setZoom(Math.max(mapState.map.getZoom(), 16));
      } catch (error) {
        // 지도를 움직이지 못해도 선택한 식당의 상세는 그대로 보여 준다.
        windowObject.console.error(error);
      }
    }
    return recordMetricAfterPaint(windowObject, "marker-selection", startedAt);
  }

  function createMap(windowObject, naverMaps, config, markers, onViewportChange, onSelect) {
    const documentObject = windowObject.document;
    const { south, west, north, east } = config.map_bounds;
    const cityBounds = new naverMaps.LatLngBounds(
      new naverMaps.LatLng(south, west),
      new naverMaps.LatLng(north, east),
    );
    const mapElement = documentObject.getElementById("map");
    mapElement.replaceChildren();
    const map = new naverMaps.Map(mapElement, {
      bounds: cityBounds,
      maxBounds: cityBounds,
      zoomControl: true,
      zoomControlOptions: { position: naverMaps.Position.TOP_RIGHT },
    });

    let initialZoomLocked = false;
    let markReady;
    const ready = new Promise((resolve) => {
      markReady = resolve;
    });
    const overlays = markers.map((data) => {
      const overlay = new naverMaps.Marker({
        map,
        position: new naverMaps.LatLng(data.latitude, data.longitude),
        icon: markerIcon(naverMaps, data),
        title: data.merchant,
      });
      naverMaps.Event.addListener(overlay, "click", (event) => onSelect(data, event));
      return { data, overlay };
    });

    naverMaps.Event.addListener(map, "idle", () => {
      if (!initialZoomLocked) {
        initialZoomLocked = true;
        map.setOptions({ minZoom: map.getZoom(), maxBounds: cityBounds });
      }
      onViewportChange(naverBoundsToPlain(map.getBounds()));
      markReady();
    });
    map.fitBounds(cityBounds);
    return { map, overlays, ready };
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
    if (!root.dataset.city) return;

    const config = readConfig(documentObject);
    windowObject.deliciousmapMetricsSummary = (name) =>
      summarizeMetrics(windowObject.deliciousmapMetrics || [], name);
    setupSourceDialog(documentObject);
    registerServiceWorker(windowObject);

    const mapApiRequest = loadNaverMaps(windowObject, config).then(
      (naverMaps) => ({ naverMaps }),
      (error) => ({ error }),
    );
    const markerStartedAt = windowObject.performance.now();
    const markerPayload = await fetchJson(windowObject, root.dataset.markersUrl);
    if (!Array.isArray(markerPayload.markers)) throw new Error("invalid marker data");
    recordMetric(windowObject, "marker-data", markerStartedAt);
    const allMarkers = markerPayload.markers;
    const totalCount = documentObject.querySelector("[data-total-count]");
    const viewportCount = documentObject.querySelector("[data-viewport-count]");
    const search = documentObject.querySelector('[name="query"]');
    let visitBand = "all";
    let filtered = allMarkers;
    let mapState;

    function selectMarkerFromPage(marker, event) {
      void selectMarker(windowObject, documentObject, config, mapState, marker, event);
    }

    function updateCounts(bounds) {
      // 도시 전체 결과는 지도와 무관하게 언제나 센다. 알 수 없는 현재 영역은 0으로 적지 않는다.
      totalCount.textContent = filtered.length.toLocaleString("ko-KR");
      viewportCount.textContent = bounds
        ? countMarkersInBounds(filtered, bounds).toLocaleString("ko-KR")
        : "—";
    }

    function applyFilters() {
      // 검색·필터 결과와 집계는 지도가 없어도 도시 전체를 대상으로 먼저 반영한다.
      filtered = filterMarkers(allMarkers, search.value, visitBand);
      renderSearchResults(documentObject, filtered, search.value, selectMarkerFromPage);
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

    function reportUnusableMap(error) {
      // 지도를 쓸 수 없다는 사실을 숨기지 않는다. 검색·집계·장부는 계속 제공한다.
      mapState = undefined;
      const message = documentObject.createElement("p");
      message.className = "map-error";
      message.textContent =
        "네이버 지도 설정을 확인해 주세요. 검색 집계와 장부는 계속 볼 수 있습니다.";
      documentObject.getElementById("map").replaceChildren(message);
      windowObject.console.error(error);
      applyFilters();
    }

    // 키가 잘못되면 SDK는 내려받아지지만 지도는 동작하지 않는다. 공식 훅으로 그 사실을 받는다.
    windowObject.navermap_authFailure = () =>
      reportUnusableMap(new Error("Naver Maps authentication failed"));

    documentObject.querySelector("[data-search-form]").addEventListener("submit", (event) => {
      event.preventDefault();
    });
    search.addEventListener("input", (event) => {
      const startedAt = interactionStartedAt(windowObject, event);
      applyFilters();
      void recordMetricAfterPaint(windowObject, "filter-result", startedAt);
    });
    for (const button of documentObject.querySelectorAll("[data-visits]")) {
      button.addEventListener("click", (event) => {
        const startedAt = interactionStartedAt(windowObject, event);
        visitBand = button.dataset.visits;
        for (const peer of documentObject.querySelectorAll("[data-visits]")) {
          peer.setAttribute("aria-pressed", String(peer === button));
        }
        applyFilters();
        void recordMetricAfterPaint(windowObject, "filter-result", startedAt);
      });
    }
    updateCounts();

    const loadRecords = createRecordsLoader(async (startedAt) => {
      const status = documentObject.querySelector("[data-records-status]");
      status.textContent = "장부를 불러오고 있습니다.";
      const payload = await fetchJson(windowObject, root.dataset.recordsUrl);
      if (!Array.isArray(payload.records)) throw new Error("invalid record data");
      renderRecords(documentObject, payload.records);
      await recordMetricAfterPaint(windowObject, "records-first-list", startedAt);
      return payload;
    });
    for (const tab of documentObject.querySelectorAll("[data-tab]")) {
      tab.addEventListener("click", async (event) => {
        const startedAt = interactionStartedAt(windowObject, event);
        switchTab(documentObject, tab.dataset.tab);
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
      mapState = {
        ...createMap(
          windowObject,
          mapApi.naverMaps,
          config,
          allMarkers,
          updateCounts,
          selectMarkerFromPage,
        ),
        naverMaps: mapApi.naverMaps,
      };
      await mapState.ready;
      applyFilters();
      await recordMetricAfterPaint(windowObject, "first-ready", 0);
    } catch (error) {
      reportUnusableMap(error);
    }
  }

  return {
    countMarkersInBounds,
    createRecordsLoader,
    filterMarkers,
    markerInBounds,
    recordState,
    renderRecords,
    renderSearchResults,
    selectMarker,
    start,
    summarizeMetrics,
    viewportBounds,
  };
});
