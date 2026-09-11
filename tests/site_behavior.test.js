const test = require("node:test");
const assert = require("node:assert/strict");

const {
  countMarkersInBounds,
  createRecordsLoader,
  filterMarkers,
  markerInBounds,
  renderRecords,
  renderSearchResults,
  selectMarker,
  summarizeMetrics,
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
