"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const WORKER_FILE = path.join(__dirname, "../src/deliciousmap/site_assets/sw.js");
const ORIGIN = "https://map.example";

function fakeResponse(body, { ok = true } = {}) {
  return {
    body,
    ok,
    clone() {
      return fakeResponse(body, { ok });
    },
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, reject, resolve };
}

function request(url, mode = "same-origin") {
  return { method: "GET", mode, url: new URL(url, ORIGIN).href };
}

function isDataUrl(url) {
  const pathname = new URL(url, ORIGIN).pathname;
  return pathname.endsWith("/markers.json") || pathname.endsWith("/records.json");
}

function workerHarness({ entries = {}, fetchImpl, windows = [] }) {
  const listeners = {};
  const deleted = [];
  const precached = [];
  const opened = [];
  let claimed = false;
  const stored = new Map([
    ["deliciousmap-shell-v1", new Map()],
    ["deliciousmap-shell-v2", new Map()],
    ["deliciousmap-data-v1", new Map()],
  ]);
  for (const [url, response] of Object.entries(entries)) {
    const cacheName = isDataUrl(url) ? "deliciousmap-data-v1" : "deliciousmap-shell-v2";
    stored.get(cacheName).set(new URL(url, ORIGIN).href, response);
  }
  const key = (value) => (typeof value === "string" ? new URL(value, ORIGIN).href : value.url);
  const cacheFor = (name) => ({
    // 실제 addAll처럼 모두 받아야 저장하고, 하나라도 실패하면 거부한다.
    addAll: async (urls) => {
      precached.push(...urls);
      const responses = await Promise.all(urls.map((url) => fetchImpl(request(url))));
      if (responses.some((response) => !response.ok)) throw new TypeError("bad response");
      urls.forEach((url, index) => stored.get(name).set(key(url), responses[index]));
    },
    match: async (value) => stored.get(name).get(key(value)),
    put: async (value, response) => stored.get(name).set(key(value), response),
  });
  const context = vm.createContext({
    URL,
    caches: {
      delete: async (name) => {
        deleted.push(name);
        stored.delete(name);
        return true;
      },
      keys: async () => [...stored.keys()],
      match: async (value) => {
        for (const cache of stored.values()) {
          const response = cache.get(key(value));
          if (response) return response;
        }
        return undefined;
      },
      open: async (name) => {
        opened.push(name);
        if (!stored.has(name)) stored.set(name, new Map());
        return cacheFor(name);
      },
    },
    fetch: fetchImpl,
    self: {
      addEventListener(name, listener) {
        listeners[name] = listener;
      },
      clients: {
        claim: async () => {
          claimed = true;
        },
        // 첫 방문 페이지는 워커가 설치될 때 아직 제어되지 않은 창이다.
        matchAll: async ({ includeUncontrolled, type } = {}) =>
          includeUncontrolled && type === "window" ? windows.map((url) => ({ url: new URL(url, ORIGIN).href })) : [],
      },
      location: { origin: ORIGIN },
    },
  });
  vm.runInContext(fs.readFileSync(WORKER_FILE, "utf8"), context, { filename: WORKER_FILE });

  return {
    dispatchFetch(value) {
      const lifetime = [];
      let response;
      listeners.fetch({
        request: value,
        respondWith(promise) {
          response = Promise.resolve(promise);
        },
        waitUntil(promise) {
          lifetime.push(Promise.resolve(promise));
        },
      });
      const complete = response ? response.then(() => Promise.all(lifetime)) : Promise.resolve();
      return { complete, response };
    },
    dispatchLifecycle(name) {
      const lifetime = [];
      listeners[name]({
        waitUntil(promise) {
          lifetime.push(Promise.resolve(promise));
        },
      });
      return Promise.all(lifetime);
    },
    deleted,
    opened,
    precached,
    get claimed() {
      return claimed;
    },
    stored,
  };
}

test("cached city shell responds before its background refresh finishes", async () => {
  const oldShell = fakeResponse("old shell");
  const freshShell = fakeResponse("fresh shell");
  const network = deferred();
  let refreshFinished = false;
  network.promise.then(() => {
    refreshFinished = true;
  });
  const harness = workerHarness({
    entries: { "/gwangju/": oldShell },
    fetchImpl: () => network.promise,
  });

  const event = harness.dispatchFetch(request("/gwangju/", "navigate"));
  const firstSettled = await event.response;

  assert.equal(firstSettled, oldShell);
  assert.equal(refreshFinished, false);
  assert.deepEqual(harness.opened, ["deliciousmap-shell-v2"]);
  network.resolve(freshShell);
  await event.complete;
  assert.equal(harness.stored.get("deliciousmap-shell-v2").get(`${ORIGIN}/gwangju/`).body, "fresh shell");
});

test("markers stay network-first while a successful response refreshes the offline fallback", async () => {
  const networkResponses = [fakeResponse("fresh markers"), new Error("offline")];
  const harness = workerHarness({
    entries: { "/gwangju/markers.json": fakeResponse("old markers") },
    fetchImpl: async () => {
      const response = networkResponses.shift();
      if (response instanceof Error) throw response;
      return response;
    },
  });

  const first = await harness.dispatchFetch(request("/gwangju/markers.json")).response;
  const second = await harness.dispatchFetch(request("/gwangju/markers.json")).response;

  assert.equal(first.body, "fresh markers");
  assert.equal(second.body, "fresh markers");
  assert.deepEqual(harness.opened, ["deliciousmap-data-v1", "deliciousmap-data-v1"]);
});

test("records use the same network-first data policy", async () => {
  const networkResponses = [fakeResponse("fresh records"), new Error("offline")];
  const harness = workerHarness({
    entries: { "/gwangju/records.json": fakeResponse("old records") },
    fetchImpl: async () => {
      const response = networkResponses.shift();
      if (response instanceof Error) throw response;
      return response;
    },
  });

  const first = await harness.dispatchFetch(request("/gwangju/records.json")).response;
  const second = await harness.dispatchFetch(request("/gwangju/records.json")).response;

  assert.equal(first.body, "fresh records");
  assert.equal(second.body, "fresh records");
  assert.deepEqual(harness.opened, ["deliciousmap-data-v1", "deliciousmap-data-v1"]);
});

test("an HTTP data error uses the last successful marker response when available", async () => {
  const harness = workerHarness({
    entries: { "/gwangju/markers.json": fakeResponse("cached markers") },
    fetchImpl: async () => fakeResponse("server error", { ok: false }),
  });

  const response = await harness.dispatchFetch(request("/gwangju/markers.json")).response;

  assert.equal(response.body, "cached markers");
  assert.deepEqual(harness.opened, ["deliciousmap-data-v1"]);
});

test("unrelated same-origin resources remain outside the worker cache policy", async () => {
  let requests = 0;
  const harness = workerHarness({
    fetchImpl: async () => {
      requests += 1;
      return fakeResponse("favicon");
    },
  });

  const event = harness.dispatchFetch(request("/favicon.ico"));

  assert.equal(event.response, undefined);
  assert.equal(requests, 0);
  assert.deepEqual(harness.opened, []);
});

test("activate removes old shell versions and claims open pages", async () => {
  const harness = workerHarness({
    entries: { "/gwangju/markers.json": fakeResponse("cached markers") },
    fetchImpl: async () => {
      throw new Error("offline");
    },
  });

  await harness.dispatchLifecycle("activate");

  assert.deepEqual(harness.deleted, ["deliciousmap-shell-v1"]);
  assert.deepEqual(harness.opened, []);
  assert.equal(harness.claimed, true);

  const fallback = await harness.dispatchFetch(request("/gwangju/markers.json")).response;
  assert.equal(fallback.body, "cached markers");
  assert.deepEqual(harness.opened, ["deliciousmap-data-v1"]);
});

test("install precaches the current shell", async () => {
  const harness = workerHarness({ fetchImpl: async () => fakeResponse("ok") });

  await harness.dispatchLifecycle("install");

  assert.deepEqual(harness.opened, ["deliciousmap-shell-v2"]);
  assert.deepEqual(harness.precached, [
    "./",
    "./assets/app.js",
    "./assets/styles.css",
    "./manifest.webmanifest",
  ]);
});

test("install caches the city page that registered the worker so the first revisit opens from cache", async () => {
  let installed = false;
  const harness = workerHarness({
    windows: ["/gwangju/"],
    fetchImpl: async (value) => fakeResponse(installed ? "network shell" : `installed ${value.url}`),
  });

  await harness.dispatchLifecycle("install");
  installed = true;
  const response = await harness.dispatchFetch(request("/gwangju/", "navigate")).response;

  assert.equal(response.body, `installed ${ORIGIN}/gwangju/`);
});

test("install still succeeds with the shell when the registering page cannot be fetched", async () => {
  const harness = workerHarness({
    windows: ["/gwangju/"],
    fetchImpl: async (value) => fakeResponse("shell", { ok: !value.url.endsWith("/gwangju/") }),
  });

  await harness.dispatchLifecycle("install");

  assert.equal(harness.stored.get("deliciousmap-shell-v2").get(`${ORIGIN}/assets/app.js`).body, "shell");
  assert.equal(harness.stored.get("deliciousmap-shell-v2").has(`${ORIGIN}/gwangju/`), false);
});
