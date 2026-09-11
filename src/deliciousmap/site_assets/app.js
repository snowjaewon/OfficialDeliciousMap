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
    return markers.filter(
      (marker) =>
        marker.latitude >= bounds.south &&
        marker.latitude <= bounds.north &&
        marker.longitude >= bounds.west &&
        marker.longitude <= bounds.east,
    ).length;
  }

  function createLedgerLoader(fetchLedger) {
    let request;
    return function loadLedger() {
      if (!request) {
        request = Promise.resolve()
          .then(fetchLedger)
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

  function renderLedger(documentObject, records) {
    const list = documentObject.querySelector("[data-ledger-list]");
    const status = documentObject.querySelector("[data-ledger-status]");
    const more = documentObject.querySelector("[data-ledger-more]");
    const batchSize = 100;
    let shown = 0;

    function appendBatch() {
      const fragment = documentObject.createDocumentFragment();
      for (const record of records.slice(shown, shown + batchSize)) {
        const article = documentObject.createElement("article");
        article.className = "ledger-record";
        const heading = documentObject.createElement("h3");
        heading.textContent = record.merchant;
        const summary = documentObject.createElement("p");
        const amount = new Intl.NumberFormat("ko-KR").format(Number(record.amount_krw));
        summary.textContent = `${record.spent_on} · ${record.organization} · ${amount}원`;
        const purpose = documentObject.createElement("p");
        purpose.textContent = record.purpose || "목적 미기재";
        const state = documentObject.createElement("span");
        state.className = `record-state state-${record.map_status}`;
        state.textContent = {
          mapped: "지도 표시",
          geocode_failed: "지오코딩 실패",
          non_restaurant: "비식당",
          pending: "판단 보류",
        }[record.map_status];
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

  function markerIcon(naverMaps, marker) {
    const className = marker.closed ? "map-marker is-closed" : "map-marker";
    return {
      content: `<button class="${className}" type="button" aria-label="식당 마커"><span>${marker.visit_count}</span></button>`,
      anchor: new naverMaps.Point(22, 22),
    };
  }

  function renderRestaurant(documentObject, marker) {
    const sheet = documentObject.querySelector("[data-restaurant-sheet]");
    const heading = documentObject.createElement("h2");
    heading.textContent = marker.merchant;
    const visits = documentObject.createElement("p");
    visits.textContent = `방문 ${marker.visit_count.toLocaleString("ko-KR")}회`;
    const closure = documentObject.createElement("p");
    closure.className = marker.closed ? "closed-state" : "open-state";
    closure.textContent = marker.closed ? "폐업 확인" : "폐업 확인 없음";
    const link = documentObject.createElement("a");
    link.href = `https://map.naver.com/p/search/${encodeURIComponent(marker.merchant)}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "네이버 지도에서 확인";
    sheet.replaceChildren(heading, visits, closure, link);
    sheet.hidden = false;
  }

  function createMap(windowObject, naverMaps, config, markers, onViewportChange) {
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
      naverMaps.Event.addListener(overlay, "click", () => {
        const startedAt = windowObject.performance.now();
        renderRestaurant(documentObject, data);
        recordMetric(windowObject, "marker-selection", startedAt);
      });
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

    function updateCounts(bounds) {
      totalCount.textContent = filtered.length.toLocaleString("ko-KR");
      viewportCount.textContent = bounds
        ? countMarkersInBounds(filtered, bounds).toLocaleString("ko-KR")
        : "0";
    }

    function applyFilters() {
      const startedAt = windowObject.performance.now();
      filtered = filterMarkers(allMarkers, search.value, visitBand);
      const visible = new Set(filtered.map((marker) => marker.business_id));
      if (mapState) {
        for (const item of mapState.overlays) {
          item.overlay.setMap(visible.has(item.data.business_id) ? mapState.map : null);
        }
        updateCounts(naverBoundsToPlain(mapState.map.getBounds()));
      } else {
        updateCounts();
      }
      recordMetric(windowObject, "filter-result", startedAt);
    }

    search.addEventListener("input", applyFilters);
    for (const button of documentObject.querySelectorAll("[data-visits]")) {
      button.addEventListener("click", () => {
        visitBand = button.dataset.visits;
        for (const peer of documentObject.querySelectorAll("[data-visits]")) {
          peer.setAttribute("aria-pressed", String(peer === button));
        }
        applyFilters();
      });
    }
    updateCounts();

    const loadLedger = createLedgerLoader(async () => {
      const startedAt = windowObject.performance.now();
      const status = documentObject.querySelector("[data-ledger-status]");
      status.textContent = "장부를 불러오고 있습니다.";
      const payload = await fetchJson(windowObject, root.dataset.ledgerUrl);
      if (!Array.isArray(payload.records)) throw new Error("invalid ledger data");
      renderLedger(documentObject, payload.records);
      recordMetric(windowObject, "ledger-first-list", startedAt);
      return payload;
    });
    for (const tab of documentObject.querySelectorAll("[data-tab]")) {
      tab.addEventListener("click", async () => {
        switchTab(documentObject, tab.dataset.tab);
        if (tab.dataset.tab === "ledger") {
          try {
            await loadLedger();
          } catch (error) {
            documentObject.querySelector("[data-ledger-status]").textContent =
              "장부를 불러오지 못했습니다. 다시 시도해 주세요.";
            windowObject.console.error(error);
          }
        }
      });
    }

    try {
      const mapApi = await mapApiRequest;
      if (mapApi.error) throw mapApi.error;
      mapState = createMap(windowObject, mapApi.naverMaps, config, allMarkers, updateCounts);
      await mapState.ready;
      applyFilters();
      recordMetric(windowObject, "first-ready", 0);
    } catch (error) {
      const mapElement = documentObject.getElementById("map");
      const message = documentObject.createElement("p");
      message.className = "map-error";
      message.textContent =
        "네이버 지도 설정을 확인해 주세요. 검색 집계와 장부는 계속 볼 수 있습니다.";
      mapElement.replaceChildren(message);
      windowObject.console.error(error);
    }
  }

  return { countMarkersInBounds, createLedgerLoader, filterMarkers, start };
});
