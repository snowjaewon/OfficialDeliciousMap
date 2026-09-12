const test = require("node:test");
const assert = require("node:assert/strict");

const {
  countMarkersInBounds,
  createMap,
  createRecordsLoader,
  filterMarkers,
  markerInBounds,
  renderRecords,
  renderSearchResults,
  selectMarker,
  summarizeMetrics,
  viewportBounds,
} = require("../src/deliciousmap/site_assets/app.js");

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.hidden = false;
    this.listeners = {};
    this.textContent = "";
  }

  addEventListener(name, listener) {
    this.listeners[name] = listener;
  }

  append(...nodes) {
    for (const node of nodes) {
      this.children.push(...(node.isFragment ? node.children : [node]));
    }
  }

  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }

  click() {
    return this.listeners.click?.({ timeStamp: 5 });
  }
}

class FakeDocument {
  constructor(elements) {
    this.elements = elements;
  }

  createDocumentFragment() {
    const fragment = new FakeElement();
    fragment.isFragment = true;
    return fragment;
  }

  createElement(tagName) {
    return new FakeElement(tagName);
  }

  querySelector(selector) {
    return this.elements[selector];
  }

  getElementById(id) {
    return this.elements[`#${id}`];
  }
}

// 네이버 지도 v3의 겉모습만 흉내 낸다. 이벤트는 테스트가 실제 SDK에서 관찰한 순서대로 직접 보낸다.
function fakeNaverMaps() {
  class LatLng {
    constructor(latitude, longitude) {
      this.latitude = latitude;
      this.longitude = longitude;
    }

    lat() {
      return this.latitude;
    }

    lng() {
      return this.longitude;
    }
  }

  class LatLngBounds {
    constructor(southWest, northEast) {
      this.southWest = southWest;
      this.northEast = northEast;
    }

    getSW() {
      return this.southWest;
    }

    getNE() {
      return this.northEast;
    }
  }

  class FakeMap {
    constructor(element, options) {
      this.element = element;
      this.options = { ...options };
      this.bounds = options.bounds;
      this.center = options.center;
      this.zoom = options.zoom ?? 10;
      this.listeners = {};
    }

    // panTo는 애니메이션으로 옮긴다. 도중에 setZoom이 오면 이동이 끊기고 원래 중심에서 확대된다.
    panTo(center) {
      this.panning = center;
    }

    setZoom(zoom) {
      this.panning = undefined;
      this.zoom = zoom;
    }

    morph(center, zoom) {
      this.center = center;
      this.zoom = zoom;
    }

    finishAnimation() {
      if (this.panning) this.center = this.panning;
      this.panning = undefined;
    }

    fitBounds(bounds) {
      this.bounds = bounds;
      this.zoom = 10;
    }

    getBounds() {
      return this.bounds;
    }

    getZoom() {
      return this.zoom;
    }

    setOptions(options) {
      Object.assign(this.options, options);
    }
  }

  return {
    LatLng,
    LatLngBounds,
    Map: FakeMap,
    Marker: class Marker {
      constructor(options) {
        this.options = options;
        this.listeners = {};
      }
    },
    Point: class Point {},
    Position: { TOP_RIGHT: "top-right" },
    Event: {
      addListener(target, name, listener) {
        (target.listeners[name] ||= []).push(listener);
      },
      trigger(target, name) {
        for (const listener of target.listeners[name] || []) listener({});
      },
    },
  };
}

function fakeWindow() {
  const frames = [];
  return {
    CustomEvent: class CustomEvent {
      constructor(name, options) {
        this.name = name;
        this.detail = options.detail;
      }
    },
    dispatchEvent() {},
    frames,
    performance: { now: () => 25, timeOrigin: 1000 },
    requestAnimationFrame(callback) {
      frames.push(callback);
    },
  };
}

const markers = [
  { merchant: "해뜰 식당", visit_count: 23, latitude: 37.5, longitude: 127.0 },
  { merchant: "바다횟집", visit_count: 14, latitude: 35.1, longitude: 129.1 },
  { merchant: "한밭 빵집", visit_count: 7, latitude: 36.3, longitude: 127.4 },
  { merchant: "골목 카페", visit_count: 2, latitude: 37.7, longitude: 127.3 },
];

const SEOUL_BOUNDS = { south: 37.41, west: 126.73, north: 37.72, east: 127.27 };

test("search and visit bands always use every marker in the selected city", () => {
  assert.deepEqual(filterMarkers(markers, "  바다  ", "all"), [markers[1]]);
  assert.deepEqual(filterMarkers(markers, "", "20"), [markers[0]]);
  assert.deepEqual(filterMarkers(markers, "", "10"), [markers[1]]);
  assert.deepEqual(filterMarkers(markers, "", "5"), [markers[2]]);
  assert.deepEqual(filterMarkers(markers, "", "1"), [markers[3]]);
});

test("the current-area count is a subset of the city-wide filtered result", () => {
  const bounds = { south: 37.4, west: 126.9, north: 37.6, east: 127.1 };
  assert.equal(countMarkersInBounds(markers, bounds), 1);
  assert.equal(countMarkersInBounds(filterMarkers(markers, "바다", "all"), bounds), 0);
  assert.equal(markerInBounds(markers[1], bounds), false);
});

test("record data is not requested until the loader is called and is reused", async () => {
  let requests = 0;
  const loadRecords = createRecordsLoader(async () => {
    requests += 1;
    return { records: [{ record_id: "r1" }] };
  });

  assert.equal(requests, 0);
  const [first, second] = await Promise.all([loadRecords(), loadRecords()]);
  assert.equal(requests, 1);
  assert.equal(first, second);
});

test("twenty-run summaries retain the second-slowest and maximum measurements", () => {
  const metrics = Array.from({ length: 20 }, (_, index) => ({
    name: "filter-result",
    duration_ms: index + 1,
  }));
  assert.deepEqual(summarizeMetrics(metrics, "filter-result"), {
    count: 20,
    maximum_ms: 20,
    second_slowest_ms: 19,
  });
});

test("a city-wide search result can reveal an out-of-bound restaurant", async () => {
  const results = new FakeElement();
  const sheet = new FakeElement();
  sheet.hidden = true;
  const documentObject = new FakeDocument({
    "[data-restaurant-sheet]": sheet,
    "[data-search-results]": results,
  });
  const windowObject = fakeWindow();
  const outside = { ...markers[1], business_id: "outside", closed: false };
  const config = { map_bounds: { south: 37.4, west: 126.9, north: 37.6, east: 127.1 } };
  let selection;

  renderSearchResults(documentObject, [outside], "바다", (marker, event) => {
    selection = selectMarker(windowObject, documentObject, config, undefined, marker, event);
  });
  results.children[0].click();
  windowObject.frames.shift()();
  assert.equal(windowObject.deliciousmapMetrics, undefined);
  windowObject.frames.shift()();
  await selection;

  assert.equal(sheet.hidden, false);
  assert.equal(sheet.children[3].textContent, "도시 지도 범위 밖의 식당입니다.");
  assert.deepEqual(windowObject.deliciousmapMetrics, [
    { name: "marker-selection", duration_ms: 20 },
  ]);
});

test("the record view renders its first hundred rows before requesting more", () => {
  const list = new FakeElement();
  const status = new FakeElement();
  const more = new FakeElement();
  const documentObject = new FakeDocument({
    "[data-records-list]": list,
    "[data-records-more]": more,
    "[data-records-status]": status,
  });
  const records = Array.from({ length: 101 }, (_, index) => ({
    amount_krw: 1000,
    map_status: "mapped",
    merchant: `식당 ${index + 1}`,
    organization: "합성 기관",
    purpose: "간담회",
    spent_on: "2026-01-01",
  }));

  renderRecords(documentObject, records);
  assert.equal(list.children.length, 100);
  assert.equal(more.hidden, false);
  more.click();
  assert.equal(list.children.length, 101);
  assert.equal(more.hidden, true);
  assert.match(status.textContent, /전체 101건 · 101건 표시/);
});

test("a selected restaurant shows where its coordinate came from", async () => {
  const sheet = new FakeElement();
  const documentObject = new FakeDocument({ "[data-restaurant-sheet]": sheet });
  const windowObject = fakeWindow();
  const config = { map_bounds: { south: 34, west: 126, north: 38, east: 130 } };
  const marker = {
    ...markers[1],
    business_id: "inside",
    closed: true,
    coordinate_source: "license",
  };

  const selection = selectMarker(windowObject, documentObject, config, undefined, marker, {});
  windowObject.frames.shift()();
  windowObject.frames.shift()();
  await selection;

  const lines = sheet.children.map((child) => child.textContent);
  assert.ok(lines.includes("폐업 확인"));
  assert.ok(lines.includes("좌표 출처: 인허가 자료"));
});

test("the record view explains why an unmapped record missed the map", () => {
  const list = new FakeElement();
  const status = new FakeElement();
  const more = new FakeElement();
  const documentObject = new FakeDocument({
    "[data-records-list]": list,
    "[data-records-more]": more,
    "[data-records-status]": status,
  });

  renderRecords(documentObject, [
    {
      amount_krw: 1000,
      classification: "restaurant",
      geocode_reason: "no_candidates",
      map_status: "geocode_failed",
      merchant: "좌표 없는 식당",
      organization: "합성 기관",
      purpose: "간담회",
      spent_on: "2026-01-01",
    },
    {
      amount_krw: 1000,
      classification: "pending",
      geocode_reason: null,
      map_status: "pending",
      merchant: "모호한 상호",
      organization: "합성 기관",
      purpose: "간담회",
      spent_on: "2026-01-01",
    },
  ]);

  const first = list.children[0].children.map((child) => child.textContent);
  assert.ok(first.includes("지오코딩 실패 · 후보 없음"));
  const second = list.children[1].children.map((child) => child.textContent);
  assert.ok(second.includes("판단 보류"));
});

test("the city view reports its area and fixes its zoom-out limit as soon as the map initializes", async () => {
  const sdk = fakeNaverMaps();
  const windowObject = { document: new FakeDocument({ "#map": new FakeElement() }) };
  const viewports = [];

  const created = createMap(windowObject, sdk, { map_bounds: SEOUL_BOUNDS }, [], (bounds) =>
    viewports.push(bounds),
  );
  // 실제 SDK는 첫 화면을 그린 뒤 init만 보내고, 사용자가 움직이기 전까지 idle을 보내지 않는다.
  sdk.Event.trigger(created.map, "init");
  await Promise.race([
    created.ready,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error("the map never became ready")), 100);
    }),
  ]);
  const cityWideZoom = created.map.getZoom();

  assert.deepEqual(viewports, [SEOUL_BOUNDS]);
  assert.equal(created.map.options.minZoom, cityWideZoom);

  // 사용자가 처음 한 동작이 축소여도 한계는 도시 전체가 보이던 수준에 머문다.
  const wider = { south: 37.2, west: 126.5, north: 37.9, east: 127.5 };
  created.map.zoom = cityWideZoom - 1;
  created.map.bounds = new sdk.LatLngBounds(
    new sdk.LatLng(wider.south, wider.west),
    new sdk.LatLng(wider.north, wider.east),
  );
  sdk.Event.trigger(created.map, "idle");

  assert.deepEqual(viewports, [SEOUL_BOUNDS, wider]);
  assert.equal(created.map.options.minZoom, cityWideZoom);
});

test("selecting a restaurant brings the map onto it at street level", async () => {
  const sdk = fakeNaverMaps();
  const sheet = new FakeElement();
  const documentObject = new FakeDocument({ "[data-restaurant-sheet]": sheet });
  const windowObject = fakeWindow();
  const config = { map_bounds: SEOUL_BOUNDS };
  const map = new sdk.Map(new FakeElement(), { center: new sdk.LatLng(37.56, 126.98), zoom: 10 });
  const marker = { ...markers[0], latitude: 37.4979, longitude: 127.0276, business_id: "gangnam" };

  const selection = selectMarker(
    windowObject,
    documentObject,
    config,
    { map, naverMaps: sdk },
    marker,
    {},
  );
  map.finishAnimation();
  windowObject.frames.shift()();
  windowObject.frames.shift()();
  await selection;

  assert.deepEqual([map.center.lat(), map.center.lng(), map.getZoom()], [37.4979, 127.0276, 16]);
});

test("city-wide counts survive a map that cannot report its viewport", () => {
  const bounds = { south: 34, west: 126, north: 38, east: 130 };
  const working = {
    map: {
      getBounds: () => ({
        getSW: () => ({ lat: () => bounds.south, lng: () => bounds.west }),
        getNE: () => ({ lat: () => bounds.north, lng: () => bounds.east }),
      }),
    },
  };
  const broken = {
    map: {
      getBounds() {
        throw new Error("authentication failed");
      },
    },
  };

  assert.deepEqual(viewportBounds(working), bounds);
  assert.equal(viewportBounds(broken), undefined);
  assert.equal(viewportBounds(undefined), undefined);
});
