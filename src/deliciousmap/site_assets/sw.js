const SHELL_CACHE_NAME = "deliciousmap-shell-v2";
const DATA_CACHE_NAME = "deliciousmap-data-v1";
// 설치한 앱의 아이콘도 셸이다. 오프라인에서도 홈 화면·작업 표시줄 아이콘이 깨지지 않는다.
// 배포 검사(publish.py)가 이 배열을 JSON으로 읽으므로 안에 주석·끝 쉼표를 두지 않는다.
const SHELL = [
  "./",
  "./assets/app.js",
  "./assets/styles.css",
  "./manifest.webmanifest",
  "./assets/icon-192.png",
  "./assets/icon-512.png",
  "./assets/icon-maskable-512.png",
  "./assets/apple-touch-icon.png"
];
// 사이트를 하위 경로에 배포해도 맞도록 워커 스크립트 위치를 기준으로 푼다.
const SHELL_PATHS = new Set(SHELL.slice(1).map((asset) => new URL(asset, self.location.href).pathname));

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE_NAME).then(async (cache) => {
      await cache.addAll(SHELL);
      await cacheRegisteringPages(cache);
    }),
  );
});

// 첫 방문 도시 화면은 워커가 제어하기 전에 받았으므로 설치 때 담아 첫 재방문도 캐시로 연다.
// 담지 못해도 설치는 계속한다. 그 화면은 다음 탐색의 응답으로 캐시된다.
async function cacheRegisteringPages(cache) {
  const pages = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  await cache.addAll(pages.map((page) => page.url)).catch(() => {});
}

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
