const SHELL_CACHE_NAME = "deliciousmap-shell-v2";
const DATA_CACHE_NAME = "deliciousmap-data-v1";
const SHELL = ["./", "./assets/app.js", "./assets/styles.css", "./manifest.webmanifest"];
const SHELL_PATHS = new Set(SHELL.slice(1).map((asset) => new URL(asset, self.location.origin).pathname));

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE_NAME)
      .then((cache) => cache.addAll(SHELL)),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith("deliciousmap-shell-") && key !== SHELL_CACHE_NAME)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (isShellRequest(event.request, url)) {
    event.respondWith(cachedShell(event));
    return;
  }
  if (!isDataRequest(url)) return;
  event.respondWith(freshData(event.request));
});

function isShellRequest(request, url) {
  return request.mode === "navigate" || SHELL_PATHS.has(url.pathname);
}

function isDataRequest(url) {
  return url.pathname.endsWith("/markers.json") || url.pathname.endsWith("/records.json");
}

async function cachedShell(event) {
  const cache = await caches.open(SHELL_CACHE_NAME);
  const cached = await cache.match(event.request);
  const refresh = fetchAndCache(cache, event.request);
  if (cached) {
    event.waitUntil(refresh.catch(() => {}));
    return cached;
  }
  return refresh;
}

async function freshData(request) {
  const cache = await caches.open(DATA_CACHE_NAME);
  try {
    const response = await fetchAndCache(cache, request);
    if (response.ok) return response;
    return (await cache.match(request)) || response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw error;
  }
}

async function fetchAndCache(cache, request) {
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}
