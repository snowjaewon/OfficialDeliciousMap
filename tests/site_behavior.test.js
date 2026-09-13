const test = require("node:test");
const assert = require("node:assert/strict");

const {
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
} = require("../src/deliciousmap/site_assets/app.js");

class FakeElement {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.hidden = false;
    this.listeners = {};
    this.textContent = "";
    this.className = "";
    this.dataset = {};
    this.attributes = {};
  }

  addEventListener(name, listener) {
    this.listeners[name] = listener;
  }

  closest(selector) {
    return selector.includes(this.tagName) ? this : null;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
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

      setIcon(icon) {
        this.options.icon = icon;
      }

      setZIndex(zIndex) {
        this.options.zIndex = zIndex;
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

// markers.json v7의 마커. 방문 요약 값은 합성값이다.
const summary = {
  address: "합성로 1",
  last_visited_on: "2026-01-02",
  total_amount_krw: "1000",
  organizations: ["test-org"],
};
const markers = [
  { ...summary, merchant: "해뜰 식당", visit_count: 23, latitude: 37.5, longitude: 127.0 },
  { ...summary, merchant: "바다횟집", visit_count: 14, latitude: 35.1, longitude: 129.1 },
  { ...summary, merchant: "한밭 빵집", visit_count: 7, latitude: 36.3, longitude: 127.4 },
  { ...summary, merchant: "골목 카페", visit_count: 2, latitude: 37.7, longitude: 127.3 },
];

const SEOUL_BOUNDS = { south: 37.41, west: 126.73, north: 37.72, east: 127.27 };

test("search and visit bands always use every marker in the selected city", () => {
  assert.deepEqual(filterMarkers(markers, "  바다  ", "all"), [markers[1]]);
  assert.deepEqual(filterMarkers(markers, "", "20"), [markers[0]]);
  assert.deepEqual(filterMarkers(markers, "", "10"), [markers[1]]);
  assert.deepEqual(filterMarkers(markers, "", "5"), [markers[2]]);
  assert.deepEqual(filterMarkers(markers, "", "1"), [markers[3]]);
});

test("several visit bands can be selected together, and an empty selection means all", () => {
  assert.deepEqual(
    filterMarkers(markers, "", new Set(["20", "5"])),
    [markers[0], markers[2]],
  );
  assert.deepEqual(filterMarkers(markers, "", new Set()), markers);
});

test("visit filter buttons toggle independently and mark the empty state as all", () => {
  const buttons = ["all", "20", "10", "5", "1"].map((band) => {
    const button = new FakeElement("button");
    button.dataset.visits = band;
    return button;
  });
  const documentObject = { querySelectorAll: () => buttons };
  const selected = setupVisitFilters(documentObject);

  assert.deepEqual(buttons.map((button) => button.attributes["aria-pressed"]), ["true", "false", "false", "false", "false"]);
  buttons[1].click();
  buttons[3].click();
  assert.deepEqual([...selected], ["20", "5"]);
  assert.deepEqual(buttons.map((button) => button.attributes["aria-pressed"]), ["false", "true", "false", "true", "false"]);
  buttons[1].click();
  buttons[3].click();
  assert.deepEqual([...selected], []);
  assert.equal(buttons[0].attributes["aria-pressed"], "true");
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

function ranks(documentObject) {
  return listed(documentObject).map(
    (item) => item.children[0].children.find((child) => child.className === "item-rank").textContent,
  );
}

test("restaurants with the same visits share a rank instead of being ordered by name", () => {
  const documentObject = listDocument();
  const tied = [9, 9, 9, 4].map((visit_count, index) => ({
    ...summary,
    merchant: `식당 ${index}`,
    visit_count,
  }));
  renderRestaurantList(documentObject, tied, () => {});
  assert.deepEqual(ranks(documentObject), ["1", "1", "1", "4"]);

  // 묶음 경계에서 이어지는 동률도 같은 순위다.
  const across = Array.from({ length: 52 }, (_, index) => ({
    ...summary,
    merchant: `식당 ${index}`,
    visit_count: index < 49 ? 100 - index : 3,
  }));
  renderRestaurantList(documentObject, across, () => {});
  documentObject.querySelector("[data-restaurant-more]").click();
  assert.deepEqual(ranks(documentObject).slice(48), ["49", "50", "50", "50"]);
});

test("a search or band keeps the ranked order of the whole city", () => {
  const ranked = rankMarkers(markers);
  assert.deepEqual(
    filterMarkers(ranked, "", "all").map((marker) => marker.visit_count),
    [23, 14, 7, 2],
  );
  assert.deepEqual(
    filterMarkers(ranked, "집", "all").map((marker) => marker.merchant),
    ["바다횟집", "한밭 빵집"],
  );
});

test("an empty result says so instead of showing a blank list", () => {
  const documentObject = listDocument();
  renderRestaurantList(documentObject, [], () => {});
  assert.equal(listed(documentObject).length, 1);
  assert.match(listed(documentObject)[0].text, /조건에 맞는 식당이 없습니다/);
});

test("a closed restaurant stays in the list and says it is closed", () => {
  const documentObject = listDocument();
  renderRestaurantList(documentObject, [{ ...markers[0], closed: true }], () => {});
  assert.ok(listed(documentObject)[0].text.includes("폐업"));
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
  const listView = documentObject.querySelector("[data-list-view]");
  listView.scrollTop = 480;
  listed(documentObject)[0].children[0].click();
  windowObject.frames.shift()();
  assert.equal(windowObject.deliciousmapMetrics, undefined);
  windowObject.frames.shift()();
  await selection;

  const detail = documentObject.querySelector("[data-restaurant-detail]");
  assert.equal(detail.hidden, false);
  assert.equal(listView.hidden, true);
  // 숨긴 목록은 브라우저가 스크롤 위치를 잃는다.
  listView.scrollTop = 0;
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
  // 닫으면 보던 자리로 돌아간다.
  assert.equal(listView.scrollTop, 480);

  // 목록을 새로 그리면 새 목록의 처음부터 보인다.
  renderRestaurantList(documentObject, [outside], () => {});
  assert.equal(listView.scrollTop, 0);
});

test("pressing a map marker opens the same detail as the list", () => {
  const sdk = fakeNaverMaps();
  const windowObject = { document: new FakeDocument({ "#map": new FakeElement() }) };
  const selected = [];
  const created = createMap(windowObject, sdk, { map_bounds: SEOUL_BOUNDS }, markers, () => {}, (
    marker,
  ) => selected.push(marker));

  const [first] = created.overlays;
  sdk.Event.trigger(first.overlay, "click");
  assert.deepEqual(selected, [markers[0]]);
});

test("selecting a map marker highlights it, and an empty map click clears the selection", () => {
  const sdk = fakeNaverMaps();
  const windowObject = { document: new FakeDocument({ "#map": new FakeElement() }) };
  const selected = [];
  const cleared = [];
  const created = createMap(
    windowObject,
    sdk,
    { map_bounds: SEOUL_BOUNDS },
    markers,
    () => {},
    (marker) => selected.push(marker),
    { onClearSelection: () => cleared.push(true) },
  );

  sdk.Event.trigger(created.overlays[0].overlay, "click");
  assert.deepEqual(selected, [markers[0]]);
  assert.match(created.overlays[0].overlay.options.icon.content, /is-selected/);
  assert.doesNotMatch(created.overlays[1].overlay.options.icon.content, /is-selected/);

  sdk.Event.trigger(created.map, "click");
  assert.deepEqual(cleared, [true]);
  assert.doesNotMatch(created.overlays[0].overlay.options.icon.content, /is-selected/);
});

test("selecting a lower-visit marker raises it above overlapping markers", () => {
  const sdk = fakeNaverMaps();
  const windowObject = { document: new FakeDocument({ "#map": new FakeElement() }) };
  const created = createMap(windowObject, sdk, { map_bounds: SEOUL_BOUNDS }, markers, () => {}, () => {});

  sdk.Event.trigger(created.overlays[1].overlay, "click");
  assert.equal(created.overlays[1].overlay.options.zIndex, 24);
  assert.equal(created.overlays[0].overlay.options.zIndex, markers[0].visit_count);
});

test("the map does not create a plus-minus zoom control", () => {
  const sdk = fakeNaverMaps();
  const windowObject = { document: new FakeDocument({ "#map": new FakeElement() }) };
  const created = createMap(windowObject, sdk, { map_bounds: SEOUL_BOUNDS }, markers, () => {});
  assert.equal(created.map.options.zoomControl, false);
  assert.equal(created.map.options.zoomControlOptions, undefined);
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

// 좁은 화면의 목록 시트. 손잡이가 보이면(display) 시트이고, 높이는 offsetHeight로 잰다.
function sheetFixture({ narrow = true } = {}) {
  const panel = new FakeElement("aside");
  panel.offsetHeight = 700;
  panel.dataset = {};
  panel.style = { values: {}, setProperty(name, value) { this.values[name] = value; } };
  const classes = new Set();
  panel.classList = { add: (name) => classes.add(name), remove: (name) => classes.delete(name) };
  const handle = new FakeElement("button");
  handle.offsetHeight = 20;
  handle.display = narrow ? "block" : "none";
  handle.setPointerCapture = () => {};
  const header = new FakeElement("form");
  header.offsetHeight = 140;
  const windowObject = {
    getComputedStyle: (element) => ({ display: element.display ?? "block" }),
    addEventListener() {},
  };
  const documentObject = new FakeDocument({
    "[data-list-panel]": panel,
    "[data-sheet-handle]": handle,
    "[data-search-form]": header,
  });
  const sheet = setupListSheet(windowObject, documentObject);
  const press = (y) => handle.listeners.pointerdown({ clientY: y, pointerId: 1 });
  const move = (y) => handle.listeners.pointermove({ clientY: y });
  const release = () => handle.listeners.pointerup({});
  const pressHeader = (y, target = header) =>
    header.listeners.pointerdown({ clientY: y, pointerId: 1, target });
  const moveHeader = (y) => header.listeners.pointermove({ clientY: y, target: header });
  const releaseHeader = () => header.listeners.pointerup({ target: header });
  return {
    sheet,
    panel,
    handle,
    header,
    press,
    move,
    release,
    pressHeader,
    moveHeader,
    releaseHeader,
  };
}

test("the list sheet opens collapsed and a tap raises it one step at a time", () => {
  const { panel, handle } = sheetFixture();
  assert.equal(panel.style.values["--sheet-visible"], "160px");
  handle.click();
  assert.equal(panel.dataset.sheet, "half");
  assert.equal(panel.style.values["--sheet-visible"], "350px");
  handle.click();
  handle.click();
  assert.equal(panel.dataset.sheet, "collapsed");
});

test("a shaky tap on the sheet handle is still a tap, and a drag settles nearby", () => {
  const { panel, handle, press, move, release } = sheetFixture();
  press(600);
  move(603);
  release();
  handle.click();
  assert.equal(panel.dataset.sheet, "half");

  // 끌어 올리면 가까운 높이에 멈추고, 뒤따르는 click은 높이를 또 바꾸지 않는다.
  press(600);
  move(300);
  release();
  handle.click();
  assert.equal(panel.dataset.sheet, "full");

  // 끌어 내려 중간에 멈춘 뒤 click이 오지 않았어도, 다음 누르기는 한 단계 올린다.
  press(600);
  move(900);
  release();
  assert.equal(panel.dataset.sheet, "half");
  press(600);
  release();
  handle.click();
  assert.equal(panel.dataset.sheet, "full");
});

test("the empty space in the sheet header drags without remeasuring during movement", () => {
  const { sheet, panel, header, pressHeader, moveHeader, releaseHeader } = sheetFixture();
  let reads = 0;
  Object.defineProperty(panel, "offsetHeight", {
    configurable: true,
    get() {
      reads += 1;
      return 700;
    },
  });
  sheet.refresh();
  const afterRefresh = reads;

  pressHeader(600);
  const afterPress = reads;
  assert.equal(afterPress, afterRefresh + 1);
  moveHeader(0);
  moveHeader(10);
  assert.equal(reads, afterPress);
  releaseHeader();
  assert.equal(reads, afterPress);
  assert.equal(panel.dataset.sheet, "full");
  assert.equal(header.listeners.pointerdown !== undefined, true);
});

test("pressing a search control inside the sheet header does not start a drag", () => {
  const { sheet, panel, header, pressHeader, moveHeader, releaseHeader } = sheetFixture();
  const input = new FakeElement("input");
  pressHeader(600, input);
  moveHeader(0);
  releaseHeader();
  assert.equal(panel.dataset.sheet, "collapsed");
  assert.equal(sheet.state(), "collapsed");
});

test("a hidden map keeps the sheet where it was instead of shrinking it to nothing", () => {
  const { sheet, panel, handle } = sheetFixture();
  handle.click();
  panel.offsetHeight = 0;
  sheet.refresh();
  assert.equal(panel.style.values["--sheet-visible"], "350px");
  panel.offsetHeight = 800;
  sheet.refresh();
  assert.equal(panel.style.values["--sheet-visible"], "400px");
});

test("a wide screen has no sheet and nothing covers the map", () => {
  const { sheet, panel, handle } = sheetFixture({ narrow: false });
  handle.click();
  sheet.raise("full");
  assert.equal(panel.dataset.sheet, undefined);
  assert.equal(sheet.coveredBottom(), 0);
  assert.equal(sheet.collapsedHeight(), 0);
});

test("a centre south of the restaurant keeps it above the sheet that covers the map", () => {
  assert.equal(latitudeSouthOf(35.15, 16, 0), 35.15);
  const shifted = latitudeSouthOf(35.15, 16, 100);
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
  assert.ok(lines.includes("합성로 1"));
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

test("a record whose original omitted the day shows that original notation", () => {
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
      amount_krw: 50000,
      classification: "pending",
      geocode_reason: null,
      map_status: "pending",
      merchant: "개인(성명 비공개)",
      organization: "합성 기관",
      purpose: "직원 부의금 지급",
      spent_on: "2026.03.",
    },
    {
      amount_krw: 1000,
      business_id: "b1",
      classification: "restaurant",
      geocode_reason: "matched",
      map_status: "mapped",
      merchant: "합성 식당",
      organization: "합성 기관",
      purpose: "간담회",
      spent_on: "2026-01-05",
    },
  ]);

  const summaries = list.children.map((card) => card.children[1].textContent);
  // 일이 빈 집행일은 원본이 적은 그대로 보이고, 일이 있는 레코드의 표시는 그대로다.
  assert.equal(summaries[0], "2026.03. · 합성 기관 · 50,000원");
  assert.equal(summaries[1], "2026-01-05 · 합성 기관 · 1,000원");
});

test("a marker whose latest visit has no day shows that original notation", async () => {
  const sheet = new FakeElement();
  const documentObject = new FakeDocument({ "[data-restaurant-detail]": sheet });
  const windowObject = fakeWindow();
  const config = { map_bounds: { south: 34, west: 126, north: 38, east: 130 } };
  const marker = { ...markers[1], business_id: "inside", last_visited_on: "2026.03." };

  const selection = selectMarker(windowObject, documentObject, config, undefined, marker, {});
  windowObject.frames.shift()();
  windowObject.frames.shift()();
  await selection;

  const lines = sheet.children.map((child) => child.textContent);
  assert.ok(lines.includes("최근 방문 2026.03."));
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

  assert.equal(map.center.lat(), latitudeSouthOf(37.4979, 16, 150));
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

const ANDROID_CHROME =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36";

// 설치 안내가 있는 화면. 브라우저 이벤트·표시 방식·저장소를 테스트가 정한다.
function installPage({ userAgent = ANDROID_CHROME, storage = new Map() } = {}) {
  const guide = new FakeElement("aside");
  guide.hidden = true;
  const message = new FakeElement("p");
  const accept = new FakeElement("button");
  accept.hidden = true;
  const dismiss = new FakeElement("button");
  const listeners = {};
  const windowObject = {
    document: new FakeDocument({
      "[data-install-guide]": guide,
      "[data-install-message]": message,
      "[data-install-accept]": accept,
      "[data-install-dismiss]": dismiss,
    }),
    navigator: { userAgent, maxTouchPoints: 0 },
    matchMedia: () => ({ matches: false }),
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, String(value)),
    },
    addEventListener(name, listener) {
      (listeners[name] ||= []).push(listener);
    },
  };
  const dispatch = (name, event = {}) => {
    for (const listener of listeners[name] || []) listener(event);
  };
  return { window: windowObject, guide, message, accept, dismiss, dispatch, storage };
}

// Chrome의 beforeinstallprompt. 사용자가 설치 창에서 고른 결과를 정해 둔다.
function installOffer(outcome) {
  return {
    defaultPrevented: false,
    prompted: 0,
    preventDefault() {
      this.defaultPrevented = true;
    },
    async prompt() {
      this.prompted += 1;
    },
    userChoice: Promise.resolve({ outcome }),
  };
}

test("Android Chrome's install offer becomes an install button that opens the install dialog", async () => {
  const page = installPage();
  setupInstallGuide(page.window);
  assert.equal(page.guide.hidden, true);

  const offer = installOffer("accepted");
  page.dispatch("beforeinstallprompt", offer);
  // 브라우저의 기본 안내 대신 이 화면의 버튼으로 설치한다.
  assert.equal(offer.defaultPrevented, true);
  assert.equal(page.guide.hidden, false);
  assert.equal(page.accept.hidden, false);
  assert.match(page.message.textContent, /설치/);

  await page.accept.click();
  assert.equal(offer.prompted, 1);
  assert.equal(page.guide.hidden, true);
});

test("a closed install guide stays closed on later visits", () => {
  const storage = new Map();
  const first = installPage({ storage });
  setupInstallGuide(first.window);
  first.dispatch("beforeinstallprompt", installOffer("accepted"));
  first.dismiss.click();
  assert.equal(first.guide.hidden, true);

  const later = installPage({ storage });
  setupInstallGuide(later.window);
  const offer = installOffer("accepted");
  later.dispatch("beforeinstallprompt", offer);
  assert.equal(later.guide.hidden, true);
  // 닫은 사람에게는 브라우저의 기본 설치 안내도 띄우지 않는다.
  assert.equal(offer.defaultPrevented, true);
});

test("declining the install dialog counts as closing the guide", async () => {
  const storage = new Map();
  const first = installPage({ storage });
  setupInstallGuide(first.window);
  first.dispatch("beforeinstallprompt", installOffer("dismissed"));
  await first.accept.click();

  const later = installPage({ storage });
  setupInstallGuide(later.window);
  later.dispatch("beforeinstallprompt", installOffer("accepted"));
  assert.equal(later.guide.hidden, true);
});

const IPHONE_SAFARI =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1";

test("iPhone Safari shows how to add the site to the home screen once", () => {
  const storage = new Map();
  const page = installPage({ userAgent: IPHONE_SAFARI, storage });
  setupInstallGuide(page.window);

  // Safari에는 설치 제안 이벤트가 없어 사용자가 공유 메뉴에서 직접 추가한다.
  assert.equal(page.guide.hidden, false);
  assert.equal(page.accept.hidden, true);
  assert.match(page.message.textContent, /공유/);
  assert.match(page.message.textContent, /홈 화면에 추가/);

  // 닫지 않고 다른 화면으로 옮겨도 다시 띄우지 않는다.
  const later = installPage({ userAgent: IPHONE_SAFARI, storage });
  setupInstallGuide(later.window);
  assert.equal(later.guide.hidden, true);

  // 처음 본 화면에서는 닫을 때까지 남는다.
  assert.equal(page.guide.hidden, false);
  page.dismiss.click();
  assert.equal(page.guide.hidden, true);
});

test("an iPad asking for the desktop site is still treated as Safari on iOS", () => {
  const page = installPage({
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15",
  });
  page.window.navigator.maxTouchPoints = 5;
  setupInstallGuide(page.window);
  assert.equal(page.guide.hidden, false);

  // 터치가 없는 Mac의 Safari는 홈 화면이 없다.
  const mac = installPage({ userAgent: page.window.navigator.userAgent });
  setupInstallGuide(mac.window);
  assert.equal(mac.guide.hidden, true);
});

test("iOS browsers other than Safari do not get the Safari instructions", () => {
  for (const userAgent of [
    // iOS Chrome
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/128.0.6613.98 Mobile/15E148 Safari/604.1",
    // 카카오톡 인앱 브라우저
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 KAKAOTALK 25.7.0",
    // 네이버 앱
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/605.1 NAVER(inapp; search; 2000; 12.10.2)",
  ]) {
    const page = installPage({ userAgent });
    setupInstallGuide(page.window);
    assert.equal(page.guide.hidden, true, userAgent);
  }
});

test("an app already opened from the home screen never shows the install guide", () => {
  const fromHomeScreen = installPage({ userAgent: IPHONE_SAFARI });
  fromHomeScreen.window.navigator.standalone = true;
  setupInstallGuide(fromHomeScreen.window);
  assert.equal(fromHomeScreen.guide.hidden, true);

  const installed = installPage();
  installed.window.matchMedia = (query) => ({ matches: query === "(display-mode: standalone)" });
  setupInstallGuide(installed.window);
  installed.dispatch("beforeinstallprompt", installOffer("accepted"));
  assert.equal(installed.guide.hidden, true);
});

test("a browser that refuses storage still shows and closes the guide on this page", () => {
  const page = installPage({ userAgent: IPHONE_SAFARI });
  page.window.localStorage = {
    getItem() {
      throw new Error("SecurityError");
    },
    setItem() {
      throw new Error("QuotaExceededError");
    },
  };
  setupInstallGuide(page.window);
  assert.equal(page.guide.hidden, false);

  page.dismiss.click();
  assert.equal(page.guide.hidden, true);
});

test("installing from the browser menu hides the install button", () => {
  const page = installPage();
  setupInstallGuide(page.window);
  page.dispatch("beforeinstallprompt", installOffer("accepted"));
  assert.equal(page.guide.hidden, false);

  page.dispatch("appinstalled");
  assert.equal(page.guide.hidden, true);
});

test("the landing page shows the install guide and registers the service worker", async () => {
  const page = installPage({ userAgent: IPHONE_SAFARI });
  const registered = [];
  page.window.navigator.serviceWorker = {
    register: async (url, options) => registered.push([String(url), options.scope]),
  };
  page.window.location = { href: "https://map.example/" };
  // 랜딩에는 도시가 없다. 지도·목록은 만들지 않는다.
  page.window.document.documentElement = { dataset: {} };
  const config = new FakeElement("script");
  config.textContent = JSON.stringify({ site_root: "./" });
  page.window.document.elements["#site-config"] = config;

  await start(page.window);

  assert.equal(page.guide.hidden, false);
  assert.deepEqual(registered, [["https://map.example/sw.js", "./"]]);
});

test("the ledger says how many places the original left unnamed", () => {
  const list = new FakeElement();
  const status = new FakeElement();
  const more = new FakeElement();
  const documentObject = new FakeDocument({
    "[data-records-list]": list,
    "[data-records-more]": more,
    "[data-records-status]": status,
  });
  const base = {
    amount_krw: 1000,
    map_status: "geocode_failed",
    geocode_reason: "no_candidates",
    organization: "합성 기관",
    purpose: "간담회",
    spent_on: "2026-01-01",
  };
  const records = [
    { ...base, merchant: "합성카페 외 1", unnamed_companions: 1 },
    // 원본이 수를 적지 않았다. 0곳으로 적으면 없는 사실을 지어낸다.
    { ...base, merchant: "합성낙지 외", unnamed_companions: null },
    { ...base, merchant: "같은 식당", unnamed_companions: 0 },
  ];

  renderRecords(documentObject, records);
  const notes = list.children.map((card) =>
    card.children.map((child) => child.textContent).filter((text) => text.includes("동행 업소")),
  );
  assert.deepEqual(notes, [["이름 없는 동행 업소 1곳"], ["이름 없는 동행 업소 수 미상"], []]);
});
