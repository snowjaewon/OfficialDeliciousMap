const test = require("node:test");
const assert = require("node:assert/strict");

const {
  centerAbove,
  countMarkersInBounds,
  createMap,
  createRecordsLoader,
  filterMarkers,
  initialViewBounds,
  markerIcon,
  markerInBounds,
  nearestSheetState,
  rankMarkers,
  renderRecords,
  renderRestaurantList,
  selectMarker,
  summarizeMetrics,
  viewportBounds,
  visitBand,
} = require("../src/deliciousmap/site_assets/app.js");

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.hidden = false;
    this.listeners = {};
    this.textContent = "";
    this.className = "";
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
    const event = { timeStamp: 5 };
    this.onclick?.(event);
    return this.listeners.click?.(event);
  }

  // 자식까지 포함한 글자. 화면에 보이는 문장을 순서와 무관하게 확인할 때 쓴다.
  get text() {
    return [this.textContent, ...this.children.map((child) => child.text)].join(" ");
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

    // 실제 SDK는 영역 크기로 줌을 정한다. 가짜는 좁은 영역일수록 크게 확대하는 것만 흉내 낸다.
    fitBounds(bounds, margin) {
      this.bounds = bounds;
      this.margin = margin;
      const span = bounds.getNE().lat() - bounds.getSW().lat();
      this.zoom = span < 0.05 ? 17 : 10;
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

function listDocument() {
  const detail = new FakeElement();
  detail.hidden = true;
  return new FakeDocument({
    "[data-list-view]": new FakeElement(),
    "[data-restaurant-detail]": detail,
    "[data-restaurant-list]": new FakeElement("ol"),
    "[data-restaurant-more]": new FakeElement("button"),
  });
}

function listed(documentObject) {
  return documentObject.querySelector("[data-restaurant-list]").children;
}

test("restaurants are ranked by visits, then by name", () => {
  const tied = [
    { merchant: "나중 식당", visit_count: 3, business_id: "b" },
    { merchant: "가장 많이 간 곳", visit_count: 9, business_id: "c" },
    { merchant: "가나다 식당", visit_count: 3, business_id: "a" },
  ];
  assert.deepEqual(
    rankMarkers(tied).map((marker) => marker.merchant),
    ["가장 많이 간 곳", "가나다 식당", "나중 식당"],
  );
  // 순위를 매겨도 받은 목록의 순서는 바꾸지 않는다.
  assert.equal(tied[0].merchant, "나중 식당");
});

test("the restaurant list shows fifty places at a time in the order it was given", () => {
  const documentObject = listDocument();
  const many = Array.from({ length: 51 }, (_, index) => ({
    merchant: `식당 ${index + 1}`,
    visit_count: 60 - index,
    address: `합성로 ${index + 1}`,
  }));

  renderRestaurantList(documentObject, many, () => {});
  const more = documentObject.querySelector("[data-restaurant-more]");
  assert.equal(listed(documentObject).length, 50);
  assert.equal(more.hidden, false);
  const first = listed(documentObject)[0].text;
  for (const shown of ["1", "식당 1", "합성로 1", "60회"]) assert.ok(first.includes(shown), shown);

  more.click();
  assert.equal(listed(documentObject).length, 51);
  assert.ok(listed(documentObject)[50].text.includes("51"));
  assert.equal(more.hidden, true);

  // 다시 그리면 앞선 목록과 더 보기가 누적되지 않는다.
  renderRestaurantList(documentObject, many.slice(0, 2), () => {});
  assert.equal(listed(documentObject).length, 2);
  assert.equal(more.hidden, true);
});

test("an empty result says so instead of showing a blank list", () => {
  const documentObject = listDocument();
  renderRestaurantList(documentObject, [], () => {});
  assert.equal(listed(documentObject).length, 1);
  assert.match(listed(documentObject)[0].text, /조건에 맞는 식당이 없습니다/);
});

test("a listed restaurant without a known address says the address is unknown", () => {
  const documentObject = listDocument();
  renderRestaurantList(documentObject, [{ ...markers[0], address: null, closed: true }], () => {});
  const item = listed(documentObject)[0].text;
  assert.ok(item.includes("주소 미상"));
  assert.ok(item.includes("폐업"));
});

test("a listed restaurant opens its detail and closing it returns to the list", async () => {
  const documentObject = listDocument();
  const windowObject = fakeWindow();
  const config = {
    map_bounds: { south: 37.4, west: 126.9, north: 37.6, east: 127.1 },
    organizations: { "west-gu": "서구청", city: "시청" },
  };
  const outside = {
    ...markers[1],
    business_id: "outside",
    closed: false,
    address: "부산 합성로 10",
    last_visited_on: "2026-03-15",
    total_amount_krw: "1234000",
    organizations: ["city", "west-gu"],
  };
  let selection;

  renderRestaurantList(documentObject, [outside], (marker, event) => {
    selection = selectMarker(windowObject, documentObject, config, undefined, marker, event);
  });
  listed(documentObject)[0].children[0].click();
  windowObject.frames.shift()();
  assert.equal(windowObject.deliciousmapMetrics, undefined);
  windowObject.frames.shift()();
  await selection;

  const detail = documentObject.querySelector("[data-restaurant-detail]");
  const listView = documentObject.querySelector("[data-list-view]");
  assert.equal(detail.hidden, false);
  assert.equal(listView.hidden, true);
  for (const shown of [
    "바다횟집",
    "방문 14회",
    "합계 1,234,000원",
    "부산 합성로 10",
    "최근 방문 2026-03-15",
    "시청, 서구청",
    "도시 지도 범위 밖의 식당입니다.",
  ]) {
    assert.ok(detail.text.includes(shown), shown);
  }
  assert.deepEqual(windowObject.deliciousmapMetrics, [
    { name: "marker-selection", duration_ms: 20 },
  ]);

  detail.children.find((child) => child.className === "detail-close").click();
  assert.equal(detail.hidden, true);
  assert.equal(listView.hidden, false);
});

test("marker color follows the same visit bands as the filter", () => {
  assert.deepEqual([25, 20, 19, 10, 9, 5, 4, 1].map(visitBand), [
    "20",
    "20",
    "10",
    "10",
    "5",
    "5",
    "1",
    "1",
  ]);
  const sdk = fakeNaverMaps();
  assert.match(markerIcon(sdk, { visit_count: 12, closed: false }).content, /map-marker band-10"/);
  assert.match(markerIcon(sdk, { visit_count: 3, closed: true }).content, /band-1 is-closed/);
});

test("the first view frames where the restaurants are, dropping far outliers", () => {
  const city = { south: 34.8, west: 126.6, north: 35.4, east: 127.1 };
  assert.equal(initialViewBounds([], city), undefined);

  const few = [
    { latitude: 35.15, longitude: 126.85 },
    { latitude: 35.16, longitude: 126.86 },
  ];
  assert.deepEqual(initialViewBounds(few, city), {
    south: 35.15,
    west: 126.85,
    north: 35.16,
    east: 126.86,
  });

  // 도심에 몰린 식당 사이에 멀리 떨어진 한 곳이 있으면 첫 화면은 도심을 따른다.
  const clustered = Array.from({ length: 39 }, (_, index) => ({
    latitude: 35.15 + index * 0.0005,
    longitude: 126.85 + index * 0.0005,
  }));
  const bounds = initialViewBounds([...clustered, { latitude: 34.9, longitude: 127.05 }], city);
  assert.ok(bounds.south > 35.14 && bounds.east < 126.9, JSON.stringify(bounds));

  // 도시 범위 밖의 식당은 첫 화면을 넓히지 않는다.
  const outside = [...few, { latitude: 37.5, longitude: 127.0 }];
  assert.deepEqual(initialViewBounds(outside, city), initialViewBounds(few, city));
});

test("the list sheet settles on the nearest of its three heights", () => {
  const heights = { collapsed: 160, half: 360, full: 700 };
  assert.equal(nearestSheetState(100, heights), "collapsed");
  assert.equal(nearestSheetState(300, heights), "half");
  assert.equal(nearestSheetState(600, heights), "full");
});

test("a centre south of the restaurant keeps it above the sheet that covers the map", () => {
  assert.equal(centerAbove(35.15, 16, 0), 35.15);
  const shifted = centerAbove(35.15, 16, 100);
  // 16단계에서 100화소는 수백 미터 안쪽이다.
  assert.ok(shifted < 35.15 && shifted > 35.14, String(shifted));
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
  const documentObject = new FakeDocument({ "[data-restaurant-detail]": sheet });
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
  // 주소를 모르면 모른다고 적는다. 다른 값으로 채우지 않는다.
  assert.ok(lines.includes("주소 미상"));
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
  const documentObject = new FakeDocument({ "[data-restaurant-detail]": sheet });
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

test("a selection under the mobile sheet lands the restaurant above the sheet", async () => {
  const sdk = fakeNaverMaps();
  const documentObject = new FakeDocument({ "[data-restaurant-detail]": new FakeElement() });
  const windowObject = fakeWindow();
  const map = new sdk.Map(new FakeElement(), { center: new sdk.LatLng(37.56, 126.98), zoom: 10 });
  const marker = { ...markers[0], latitude: 37.4979, longitude: 127.0276, business_id: "gangnam" };

  const selection = selectMarker(
    windowObject,
    documentObject,
    { map_bounds: SEOUL_BOUNDS },
    { map, naverMaps: sdk, coveredBottom: () => 300 },
    marker,
    {},
  );
  windowObject.frames.shift()();
  windowObject.frames.shift()();
  await selection;

  assert.equal(map.center.lat(), centerAbove(37.4979, 16, 150));
  assert.equal(map.center.lng(), 127.0276);
});

test("the city view opens on its restaurants but still zooms out to the whole city", async () => {
  const sdk = fakeNaverMaps();
  const windowObject = { document: new FakeDocument({ "#map": new FakeElement() }) };
  const viewports = [];
  const nearby = [
    { ...markers[0], latitude: 37.5, longitude: 127.0 },
    { ...markers[1], latitude: 37.51, longitude: 127.01 },
  ];

  const created = createMap(
    windowObject,
    sdk,
    { map_bounds: SEOUL_BOUNDS },
    nearby,
    (bounds) => viewports.push(bounds),
    () => {},
    { bottomInset: 120 },
  );
  sdk.Event.trigger(created.map, "init");
  await created.ready;

  // 축소 한계는 도시 전체가 보이던 수준 그대로다.
  assert.equal(created.map.options.minZoom, 10);
  assert.deepEqual(viewports, [{ south: 37.5, west: 127.0, north: 37.51, east: 127.01 }]);
  // 시트가 가린 아래쪽만큼 여백을 더 둔다.
  assert.ok(created.map.margin.bottom > created.map.margin.top);
  // 몇 곳만 모여 있어도 골목 수준까지 들어가지 않는다.
  assert.equal(created.map.getZoom(), 14);
});

test("markers with more visits are drawn above the others", () => {
  const sdk = fakeNaverMaps();
  const windowObject = { document: new FakeDocument({ "#map": new FakeElement() }) };
  const created = createMap(windowObject, sdk, { map_bounds: SEOUL_BOUNDS }, markers, () => {});
  assert.deepEqual(
    created.overlays.map((item) => item.overlay.options.zIndex),
    markers.map((marker) => marker.visit_count),
  );
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
