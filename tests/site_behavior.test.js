const test = require("node:test");
const assert = require("node:assert/strict");

const {
  countMarkersInBounds,
  createLedgerLoader,
  filterMarkers,
} = require("../src/deliciousmap/site_assets/app.js");

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
});

test("ledger data is not requested until the loader is called and is reused", async () => {
  let requests = 0;
  const loadLedger = createLedgerLoader(async () => {
    requests += 1;
    return { records: [{ record_id: "r1" }] };
  });

  assert.equal(requests, 0);
  const [first, second] = await Promise.all([loadLedger(), loadLedger()]);
  assert.equal(requests, 1);
  assert.equal(first, second);
});
