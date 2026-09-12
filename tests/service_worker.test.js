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

function workerHarness({ entries = {}, fetchImpl }) {
  const listeners = {};
  const deleted = [];
  const precached = [];
  const opened = [];
  let claimed = false;
  const stored = new Map(
    Object.entries(entries).map(([url, response]) => [new URL(url, ORIGIN).href, response]),
  );
  const key = (value) => (typeof value === "string" ? new URL(value, ORIGIN).href : value.url);
  const cache = {
    addAll: async (urls) => {
      precached.push(...urls);
    },
    match: async (value) => stored.get(key(value)),
    put: async (value, response) => stored.set(key(value), response),
  };
  const context = vm.createContext({
    URL,
    caches: {
      delete: async (name) => {
        deleted.push(name);
        return true;
      },
      keys: async () => ["deliciousmap-shell-v1", "deliciousmap-data-v1"],
      match: cache.match,
      open: async (name) => {
        opened.push(name);
        return cache;
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
      return { complete: Promise.all(lifetime), response };
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
  const harness = workerHarness({
    entries: { "/gwangju/": oldShell },
    fetchImpl: () => network.promise,
  });

  const event = harness.dispatchFetch(request("/gwangju/", "navigate"));
  const firstSettled = await Promise.race([
    event.response,
    new Promise((resolve) => setTimeout(() => resolve("still waiting"), 10)),
  ]);

  assert.equal(firstSettled, oldShell);
  assert.deepEqual(harness.opened, ["deliciousmap-shell-v2"]);
  network.resolve(freshShell);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(harness.stored.get(`${ORIGIN}/gwangju/`).body, "fresh shell");
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
  const harness = workerHarness({ fetchImpl: async () => fakeResponse("ok") });

  await harness.dispatchLifecycle("activate");

  assert.deepEqual(harness.deleted, ["deliciousmap-shell-v1"]);
  assert.deepEqual(harness.opened, []);
  assert.equal(harness.claimed, true);
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
