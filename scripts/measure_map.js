"use strict";

// 이슈 #22 결정 댓글의 측정 절차를 실제 Chrome으로 반복한다. 목표·횟수의 정본은 그 댓글이다.

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const util = require("node:util");
const zlib = require("node:zlib");

const MEGABIT_BYTES = 1000 * 1000 / 8;

// 모의 모바일의 CPU 감속은 특정 기기와 같다는 뜻이 아니다. 결과에 호스트 정보를 함께 남긴다.
const ENVIRONMENTS = {
  desktop: {
    network: null,
    cpu_slowdown: 1,
    device: { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false },
  },
  mobile: {
    network: {
      offline: false,
      latency: 100,
      downloadThroughput: 10 * MEGABIT_BYTES,
      uploadThroughput: 1 * MEGABIT_BYTES,
    },
    cpu_slowdown: 4,
    device: { width: 412, height: 915, deviceScaleFactor: 2.625, mobile: true },
  },
};

const ENVIRONMENT_LABELS = { desktop: "데스크톱", mobile: "모의 모바일" };

// 시간 목표가 있는 시나리오. 피드백(50ms)과 결과 완료(200ms)는 따로 잰다.
const SCENARIOS = {
  "first-visit": { label: "첫 방문", target_ms: 4000 },
  revisit: { label: "재방문", target_ms: 2000 },
  "records-first-list": { label: "장부 첫 목록", target_ms: 2000 },
  "search-feedback": { label: "검색 입력 피드백", target_ms: 50 },
  "search-result": { label: "검색 결과", target_ms: 200 },
  "filter-feedback": { label: "필터 버튼 피드백", target_ms: 50 },
  "filter-result": { label: "필터 결과", target_ms: 200 },
  // 식당 선택은 검색 결과 목록에서 한다. 지도 위 마커를 누르는 경로는 재지 않는다.
  "selection-feedback": { label: "검색 결과 선택 피드백", target_ms: 50 },
  "selection-detail": { label: "검색 결과 선택 상세", target_ms: 200 },
};

const VERDICT_LABELS = { pass: "충족", fail: "미달", unmeasured: "미측정" };

function formatMilliseconds(value) {
  return value === null ? "—" : `${value.toLocaleString("en-US", { maximumFractionDigits: 1 })}ms`;
}

function markdownTable(rows) {
  const lines = [
    "| 환경 | 시나리오 | 목표 | 횟수 | 느린 순 2번째 | 최대 | 판정 |",
    "| --- | --- | ---: | ---: | ---: | ---: | --- |",
  ];
  for (const { environment, scenario, summary } of rows) {
    const cells = [
      ENVIRONMENT_LABELS[environment],
      SCENARIOS[scenario].label,
      formatMilliseconds(summary.target_ms),
      summary.runs,
      formatMilliseconds(summary.second_slowest_ms),
      formatMilliseconds(summary.maximum_ms),
      VERDICT_LABELS[summary.verdict],
    ];
    lines.push(`| ${cells.join(" | ")} |`);
  }
  return lines.join("\n");
}

function judge(attempts, targetMs, requiredRuns) {
  const durations = attempts
    .map((attempt) => attempt.duration_ms)
    .filter(Number.isFinite)
    .sort((left, right) => right - left);
  const secondSlowest = durations[1] ?? null;
  let verdict = "unmeasured";
  if (durations.length >= requiredRuns) verdict = secondSlowest <= targetMs ? "pass" : "fail";
  return {
    runs: durations.length,
    second_slowest_ms: secondSlowest,
    maximum_ms: durations[0] ?? null,
    target_ms: targetMs,
    verdict,
  };
}

// rAF 간격은 프레임 부드러움의 진단 값이다. 판정은 결정대로 브라우저 성능 기록으로 한다.
const FRAME_MS = 1000 / 60;
const STUTTER_FRAME_MS = FRAME_MS * 2;
const FREEZE_FRAME_MS = 100;
const LONG_TASK_MS = 50;

const TRACE_CATEGORIES = [
  "blink.user_timing",
  "cc",
  "devtools.timeline",
  "disabled-by-default-devtools.timeline",
  "disabled-by-default-devtools.timeline.frame",
  "gpu",
  "toplevel",
  "viz",
].join(",");

const FRAME_EVENT_NAMES = new Set(["FramePresented", "PresentFrame"]);

function roundMilliseconds(value) {
  return Number(value.toFixed(1));
}

function traceEventList(trace) {
  if (Array.isArray(trace)) return trace;
  if (typeof trace === "string") return traceEventList(JSON.parse(trace));
  return Array.isArray(trace?.traceEvents) ? trace.traceEvents : [];
}

function traceMarkerTimestamp(events, marker) {
  return events.find(
    (event) =>
      event.name === marker ||
      event.args?.name === marker ||
      event.args?.data?.name === marker ||
      event.args?.data?.message === marker,
  )?.ts;
}

function traceWindow(events, startMarker, endMarker) {
  if (!startMarker || !endMarker) return events;
  const start = traceMarkerTimestamp(events, startMarker);
  const end = traceMarkerTimestamp(events, endMarker);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return events;
  return events.filter((event) => !Number.isFinite(event.ts) || (event.ts >= start && event.ts <= end));
}

function eventDurationMs(event) {
  return Number.isFinite(event.dur) ? event.dur / 1000 : null;
}

function completedTraceEvents(events, names) {
  const completed = [];
  const open = new Map();
  const keyFor = (event) =>
    `${event.name}|${event.pid ?? ""}|${event.tid ?? ""}|${JSON.stringify(event.id2 ?? event.id ?? "")}`;
  for (const event of events) {
    if (!names.has(event.name)) continue;
    if (event.ph === "X" && Number.isFinite(event.dur)) {
      completed.push(event);
    } else if (event.ph === "b" || event.ph === "s") {
      const key = keyFor(event);
      (open.get(key) ?? open.set(key, []).get(key)).push(event);
    } else if (event.ph === "e" || event.ph === "f") {
      const starts = open.get(keyFor(event));
      const start = starts?.pop();
      if (start && Number.isFinite(start.ts) && Number.isFinite(event.ts)) {
        completed.push({ ...start, dur: event.ts - start.ts });
      }
    }
  }
  return completed;
}

function traceFrameTimestamps(events) {
  const presentedFrames = events
    .filter(
      (event) =>
        event.name === "PipelineReporter" &&
        event.ph === "b" &&
        event.args?.frame_reporter?.state === "STATE_PRESENTED_ALL" &&
        Number.isFinite(event.ts),
    )
    .map((event) => event.ts);
  if (presentedFrames.length > 0) {
    return [...new Set(presentedFrames)].sort((left, right) => left - right);
  }
  return [
    ...new Set(
      events
        .filter((event) => FRAME_EVENT_NAMES.has(event.name) && Number.isFinite(event.ts))
        .map((event) => event.ts),
    ),
  ].sort((left, right) => left - right);
}

function traceSourceUrl(event) {
  const encoded = JSON.stringify(event.args ?? {});
  return encoded.match(/https?:\/\/[^"\s]+/i)?.[0] ?? null;
}

function traceSource(event) {
  const url = traceSourceUrl(event);
  if (!url) return "other";
  if (/\bnaver\.com(?:[/:]|$)/i.test(url)) return "naver_sdk";
  if (/\b(?:localhost|127\.0\.0\.1)(?::|[/:]|$)/i.test(url)) return "application";
  return "other";
}

function nestedTraceSource(event, allEvents) {
  const direct = traceSource(event);
  if (direct !== "other" || !Number.isFinite(event.ts) || !Number.isFinite(event.dur)) return direct;
  const end = event.ts + event.dur;
  const nested = allEvents.filter(
    (candidate) =>
      candidate !== event &&
      Number.isFinite(candidate.ts) &&
      candidate.ts >= event.ts &&
      candidate.ts <= end &&
      traceSource(candidate) !== "other",
  );
  return nested
    .map((candidate) => traceSource(candidate))
    .sort(
      (left, right) =>
        nested.filter((candidate) => traceSource(candidate) === right).length -
        nested.filter((candidate) => traceSource(candidate) === left).length,
    )[0] ?? "other";
}

function sourceSummary(events, allEvents = events) {
  const summary = {
    application: { count: 0, total_ms: 0, maximum_ms: null },
    naver_sdk: { count: 0, total_ms: 0, maximum_ms: null },
    other: { count: 0, total_ms: 0, maximum_ms: null },
  };
  for (const event of events) {
    const duration = eventDurationMs(event);
    if (duration === null || duration < LONG_TASK_MS) continue;
    const source = nestedTraceSource(event, allEvents);
    const bucket = summary[source];
    bucket.count += 1;
    bucket.total_ms = roundMilliseconds(bucket.total_ms + duration);
    bucket.maximum_ms = Math.max(bucket.maximum_ms ?? 0, roundMilliseconds(duration));
  }
  const dominant = Object.entries(summary)
    .filter(([, bucket]) => bucket.count > 0)
    .sort(([, left], [, right]) => right.total_ms - left.total_ms)[0]?.[0] ?? null;
  return { ...summary, dominant };
}

function summarizeTrace(trace, options = {}) {
  const events = traceWindow(traceEventList(trace), options.startMarker, options.endMarker);
  const timestamps = traceFrameTimestamps(events);
  const intervals = timestamps.slice(1).map((timestamp, index) => (timestamp - timestamps[index]) / 1000);
  const intervalDroppedFrames = intervals.reduce(
    (total, interval) => total + Math.max(0, Math.round(interval / FRAME_MS) - 1),
    0,
  );
  const pipelineDroppedFrames = events.filter(
    (event) =>
      event.name === "PipelineReporter" &&
      event.ph === "b" &&
      event.args?.frame_reporter?.state === "STATE_DROPPED",
  ).length;
  const stutterCount = intervals.filter((interval) => interval >= STUTTER_FRAME_MS).length;
  const longestFrame = Math.max(0, ...intervals);
  const longAnimationEvents = completedTraceEvents(
    events,
    new Set(["AnimationFrame", "LongAnimationFrame"]),
  );
  const longAnimationFrames = longAnimationEvents
    .map(eventDurationMs)
    .filter((duration) => duration !== null && duration >= LONG_TASK_MS);
  const longTasks = events
    .filter((event) => /^(?:LongTask|RunTask|Task)$/i.test(event.name ?? ""))
    .map(eventDurationMs)
    .filter((duration) => duration !== null && duration >= LONG_TASK_MS);
  const freezeCount = [
    ...intervals.filter((interval) => interval >= FREEZE_FRAME_MS),
    ...longAnimationFrames.filter((duration) => duration >= FREEZE_FRAME_MS),
    // Long tasks are usually nested in a Long Animation Frame. Count them as
    // freeze evidence only when the trace has no higher-level animation frame.
    ...(longAnimationFrames.length === 0
      ? longTasks.filter((duration) => duration >= FREEZE_FRAME_MS)
      : []),
  ].length;
  const longestLongAnimationFrame = Math.max(0, ...longAnimationFrames);
  const longestLongTask = Math.max(0, ...longTasks);
  const measured = intervals.length > 0;
  const source = sourceSummary(
    [
      ...longAnimationEvents,
      ...events.filter((event) => /^(?:LongTask|RunTask|Task)$/i.test(event.name ?? "")),
    ],
    events,
  );
  return {
    frames: intervals.length,
    frame_budget_ms: roundMilliseconds(FRAME_MS),
    delayed_frames: Math.max(intervalDroppedFrames, pipelineDroppedFrames),
    dropped_frames: pipelineDroppedFrames,
    stutter_count: stutterCount,
    freeze_count: freezeCount,
    longest_frame_ms: measured ? roundMilliseconds(longestFrame) : null,
    long_animation_frames: longAnimationFrames.length,
    longest_long_animation_frame_ms:
      longAnimationFrames.length > 0 ? roundMilliseconds(longestLongAnimationFrame) : null,
    long_tasks: longTasks.length,
    longest_long_task_ms: longTasks.length > 0 ? roundMilliseconds(longestLongTask) : null,
    source,
    verdict: !measured ? "unmeasured" : stutterCount > 0 || freezeCount > 0 ? "fail" : "pass",
  };
}

function judgeTrace(attempts, requiredRuns) {
  const measured = attempts.filter((attempt) => ["pass", "fail"].includes(attempt.verdict));
  const stutterRuns = measured.filter(
    (attempt) => attempt.stutter_count > 0 || attempt.longest_frame_ms >= STUTTER_FRAME_MS,
  ).length;
  const freezeRuns = measured.filter(
    (attempt) => attempt.freeze_count > 0 || attempt.longest_frame_ms >= FREEZE_FRAME_MS,
  ).length;
  const longestFrame = Math.max(0, ...measured.map((attempt) => attempt.longest_frame_ms ?? 0));
  return {
    runs: measured.length,
    passing_runs: measured.filter((attempt) => attempt.verdict === "pass").length,
    stutter_runs: stutterRuns,
    freeze_runs: freezeRuns,
    longest_frame_ms: measured.length > 0 ? roundMilliseconds(longestFrame) : null,
    verdict:
      measured.length < requiredRuns ? "unmeasured" : stutterRuns > 0 || freezeRuns > 0 ? "fail" : "pass",
  };
}

function frameStats(timestamps) {
  const intervals = timestamps.slice(1).map((time, index) => time - timestamps[index]);
  const longest = Math.max(0, ...intervals);
  // 짝수 개면 위쪽 중앙값을 쓴다. 끊긴 간격이 섞여도 평소 갱신 주기를 가리킨다.
  const median = [...intervals].sort((left, right) => left - right)[Math.floor(intervals.length / 2)];
  return {
    frames: intervals.length,
    median_frame_ms: median === undefined ? null : Number(median.toFixed(1)),
    longest_frame_ms: Number(longest.toFixed(1)),
    dropped_frames: intervals.reduce(
      (total, interval) => total + Math.max(0, Math.round(interval / FRAME_MS) - 1),
      0,
    ),
  };
}

const CONTENT_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
};

function acceptsGzip(request) {
  return /\bgzip\b/.test(request.headers["accept-encoding"] ?? "");
}

// 운영 Cloudflare Pages처럼 캐시한 파일도 매번 재검증하게 하고 텍스트를 압축해 보낸다.
// Pages는 brotli를 쓸 수 있으므로 gzip 전송량은 운영보다 크거나 같다.
function createStaticServer(root) {
  const siteRoot = path.resolve(root);
  return http.createServer((request, response) => {
    const notFound = () => {
      response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      response.end("not found");
    };
    let relative;
    try {
      relative = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
    } catch (error) {
      return notFound();
    }
    let file = path.resolve(siteRoot, `.${relative}`);
    if (file !== siteRoot && !file.startsWith(`${siteRoot}${path.sep}`)) return notFound();
    if (relative.endsWith("/")) file = path.join(file, "index.html");
    let body;
    try {
      body = fs.readFileSync(file);
    } catch (error) {
      return notFound();
    }
    // 압축 여부와 무관하게 같은 내용이므로 약한 ETag를 쓴다.
    const etag = `W/"${crypto.createHash("sha256").update(body).digest("hex").slice(0, 32)}"`;
    const contentType = CONTENT_TYPES[path.extname(file)];
    const headers = {
      "cache-control": "public, max-age=0, must-revalidate",
      "content-type": contentType ?? "application/octet-stream",
      etag,
      vary: "accept-encoding",
    };
    if (request.headers["if-none-match"] === etag) {
      response.writeHead(304, headers);
      return response.end();
    }
    if (contentType && acceptsGzip(request)) {
      body = zlib.gzipSync(body);
      headers["content-encoding"] = "gzip";
    }
    response.writeHead(200, { ...headers, "content-length": body.length });
    return response.end(request.method === "HEAD" ? undefined : body);
  });
}

// ---- 여기부터 실제 Chrome을 CDP로 움직인다. 단위 테스트가 아니라 실제 실행으로 확인한다. ----

const REQUIRED_RUNS = 20;
// 페이지 조건 대기와 CDP 응답 대기 모두 이 시간을 넘기면 그 회차를 실패로 적는다.
const RUN_TIMEOUT_MS = 60000;
const SETTLE_MS = 1000;
// 지도 클라이언트 키의 허용 주소가 이 포트다(#50).
const SITE_PORT = 8765;
const DEFAULT_CHROME = {
  win32: "C:/Program Files/Google/Chrome/Application/chrome.exe",
  linux: "google-chrome",
};

// 페이지가 만들어지기 전에 넣는다. Event Timing은 입력부터 다음 화면 반영까지의 시간을 준다.
const PAGE_PROBE = `(() => {
  window.__measureEvents = [];
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      window.__measureEvents.push({
        name: entry.name,
        startTime: entry.startTime,
        duration: entry.duration,
        interactionId: entry.interactionId,
      });
    }
  }).observe({ type: "event", durationThreshold: 16, buffered: true });
  window.__measureFrames = {
    times: [],
    running: false,
    start() {
      this.times = [];
      this.running = true;
      const tick = (time) => {
        if (!this.running) return;
        this.times.push(time);
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    },
    stop() {
      this.running = false;
      return this.times;
    },
  };
})();`;

// Event Timing은 16ms 미만 입력을 보고하지 않는다. 그런 입력은 16ms 이하로 적는다.
const EVENT_TIMING_FLOOR_MS = 16;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 0;
    this.pending = new Map();
    this.listeners = new Set();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      const waiter = message.id && this.pending.get(message.id);
      if (waiter) {
        this.settle(message.id);
        if (message.error) waiter.reject(new Error(`${waiter.method}: ${message.error.message}`));
        else waiter.resolve(message.result);
        return;
      }
      for (const listener of this.listeners) listener(message);
    });
    // Chrome이 죽으면 기다리던 요청이 영원히 남지 않게 모두 실패시킨다.
    socket.addEventListener("close", () => {
      for (const [id, waiter] of this.pending) {
        this.settle(id);
        waiter.reject(new Error(`${waiter.method}: CDP connection closed`));
      }
    });
  }

  settle(id) {
    clearTimeout(this.pending.get(id).timer);
    this.pending.delete(id);
  }

  static async connect(url) {
    const socket = new WebSocket(url);
    await new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve, { once: true });
      socket.addEventListener("error", () => reject(new Error("CDP connection failed")), {
        once: true,
      });
    });
    return new Cdp(socket);
  }

  send(method, params = {}, sessionId = undefined) {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      // 페이지 스크립트의 약속이 끝나지 않아도 응답 대기는 제한 시간에서 끊는다.
      const timer = setTimeout(() => {
        this.settle(id);
        reject(new Error(`${method}: no response in ${RUN_TIMEOUT_MS}ms`));
      }, RUN_TIMEOUT_MS);
      this.pending.set(id, { method, resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params, sessionId }));
    });
  }

  on(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  waitForEvent(method, sessionId = undefined) {
    return new Promise((resolve, reject) => {
      const unsubscribe = this.on((message) => {
        if (message.method !== method || message.sessionId !== sessionId) return;
        clearTimeout(timer);
        unsubscribe();
        resolve(message.params);
      });
      const timer = setTimeout(() => {
        unsubscribe();
        reject(new Error(`${method}: no event in ${RUN_TIMEOUT_MS}ms`));
      }, RUN_TIMEOUT_MS);
    });
  }

  close() {
    this.socket.close();
  }
}

async function readTrace(cdp, sessionId, stream) {
  const chunks = [];
  try {
    for (;;) {
      const result = await cdp.send("IO.read", { handle: stream }, sessionId);
      chunks.push(result.base64Encoded ? Buffer.from(result.data, "base64") : result.data);
      if (result.eof) break;
    }
    return chunks.join("");
  } finally {
    await cdp.send("IO.close", { handle: stream }, sessionId).catch(() => {});
  }
}

async function launchChrome(chromePath, headed) {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "deliciousmap-measure-"));
  // 정리 실패가 측정 실패를 가리지 않게 경고만 남긴다.
  const removeProfile = () => {
    try {
      fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    } catch (error) {
      process.stderr.write(`measure: temporary Chrome profile left at ${profile}\n`);
    }
  };
  const args = [
    "--remote-debugging-port=0",
    `--user-data-dir=${profile}`,
    "--no-first-run",
    "--no-default-browser-check",
    // 창이 가려져도 rAF·타이머가 멈추지 않게 한다(#50의 관찰).
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "about:blank",
  ];
  if (!headed) args.unshift("--headless=new");
  const child = childProcess.spawn(chromePath, args, { stdio: "ignore" });
  const exited = new Promise((resolve) => child.once("exit", resolve));
  const kill = async () => {
    if (child.exitCode === null) child.kill();
    await Promise.race([exited, sleep(2000)]);
    removeProfile();
  };
  child.once("error", () => {});
  const portFile = path.join(profile, "DevToolsActivePort");
  try {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (child.exitCode !== null) break;
      if (fs.existsSync(portFile)) {
        const [port, browserPath] = fs.readFileSync(portFile, "utf8").split("\n");
        if (browserPath) {
          const cdp = await Cdp.connect(`ws://127.0.0.1:${port}${browserPath.trim()}`);
          const stop = async () => {
            cdp.close();
            await kill();
          };
          return { cdp, stop };
        }
      }
      await sleep(100);
    }
  } catch (error) {
    await kill();
    throw error;
  }
  await kill();
  throw new Error(`Chrome did not start: ${chromePath}`);
}

// 브라우저 전체에 자동 연결을 걸어 서비스 워커에도 같은 네트워크 조건을 준다.
// 재방문 요청은 서비스 워커가 대신 받으므로 페이지에만 걸면 제한이 빠진다.
async function attachAutomatically(cdp, environmentFor) {
  // createTarget 응답보다 연결 이벤트가 먼저 올 수 있어 어느 쪽이 먼저든 같은 약속을 쓴다.
  const pages = new Map();
  const pageSession = (targetId) => {
    if (!pages.has(targetId)) {
      const settled = {};
      settled.promise = new Promise((resolve, reject) => {
        settled.resolve = resolve;
        settled.reject = reject;
      });
      pages.set(targetId, settled);
    }
    return pages.get(targetId);
  };
  cdp.on(async (message) => {
    if (message.method !== "Target.attachedToTarget") return;
    const { sessionId, targetInfo, waitingForDebugger } = message.params;
    const environment = environmentFor(targetInfo.browserContextId);
    const measuredPage = environment && targetInfo.type === "page";
    try {
      if (environment && ["page", "service_worker"].includes(targetInfo.type)) {
        await cdp.send("Network.enable", {}, sessionId);
        if (environment.network) {
          await cdp.send("Network.emulateNetworkConditions", environment.network, sessionId);
        }
      }
      if (measuredPage) await preparePage(cdp, sessionId, environment);
      if (waitingForDebugger) await cdp.send("Runtime.runIfWaitingForDebugger", {}, sessionId);
      if (measuredPage) pageSession(targetInfo.targetId).resolve(sessionId);
    } catch (error) {
      // 조건을 걸지 못한 페이지로 재면 조건 밖 값이 섞이므로 그 회차를 실패로 넘긴다.
      if (measuredPage) pageSession(targetInfo.targetId).reject(error);
      else process.stderr.write(`measure: ${targetInfo.type} setup failed: ${error.message}\n`);
    }
  });
  await cdp.send("Target.setAutoAttach", {
    autoAttach: true,
    waitForDebuggerOnStart: true,
    flatten: true,
  });
  return async function sessionFor(targetId) {
    const sessionId = await pageSession(targetId).promise;
    pages.delete(targetId);
    return sessionId;
  };
}

async function preparePage(cdp, sessionId, environment) {
  await cdp.send("Page.enable", {}, sessionId);
  await cdp.send("Runtime.enable", {}, sessionId);
  await cdp.send("Performance.enable", {}, sessionId);
  await cdp.send(
    "Emulation.setDeviceMetricsOverride",
    { ...environment.device, screenWidth: environment.device.width },
    sessionId,
  );
  await cdp.send(
    "Emulation.setTouchEmulationEnabled",
    { enabled: environment.device.mobile },
    sessionId,
  );
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: environment.cpu_slowdown }, sessionId);
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: PAGE_PROBE }, sessionId);
}

class Page {
  constructor(cdp, sessionId, targetId) {
    this.cdp = cdp;
    this.sessionId = sessionId;
    this.targetId = targetId;
    this.transferred = 0;
    this.unsubscribe = cdp.on((message) => {
      if (message.sessionId === sessionId && message.method === "Network.loadingFinished") {
        this.transferred += message.params.encodedDataLength;
      }
    });
  }

  static async open(browser, browserContextId) {
    const { targetId } = await browser.cdp.send("Target.createTarget", {
      url: "about:blank",
      browserContextId,
    });
    return new Page(browser.cdp, await browser.sessionFor(targetId), targetId);
  }

  async evaluate(expression) {
    const { result, exceptionDetails } = await this.cdp.send(
      "Runtime.evaluate",
      { expression, awaitPromise: true, returnByValue: true },
      this.sessionId,
    );
    if (exceptionDetails) throw new Error(`page script failed: ${exceptionDetails.text}`);
    return result.value;
  }

  async waitFor(expression, label, timeoutMs = RUN_TIMEOUT_MS) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const value = await this.evaluate(expression).catch(() => undefined);
      if (value) return value;
      await sleep(50);
    }
    throw new Error(`timed out waiting for ${label}`);
  }

  metricCount(name) {
    return this.evaluate(
      `(window.deliciousmapMetrics || []).filter((entry) => entry.name === ${JSON.stringify(name)}).length`,
    );
  }

  // 앱이 남긴 계측 하나를 기다려 돌려준다. 조작 전 개수보다 늘어난 항목이 이번 조작의 값이다.
  async metricAfter(name, before) {
    return this.waitFor(
      `(() => {
        const entries = (window.deliciousmapMetrics || []).filter((entry) => entry.name === ${JSON.stringify(name)});
        return entries.length > ${before} ? entries[entries.length - 1] : null;
      })()`,
      name,
    );
  }

  async navigate(url) {
    this.transferred = 0;
    await this.cdp.send("Page.navigate", { url }, this.sessionId);
    const ready = await this.waitFor(
      `(() => {
        if (document.querySelector(".map-error")) return { error: "map unusable" };
        return (window.deliciousmapMetrics || []).find((entry) => entry.name === "first-ready") || null;
      })()`,
      "first-ready",
    );
    if (ready.error) throw new Error(ready.error);
    return { duration_ms: ready.duration_ms, transferred_bytes: this.transferred };
  }

  async center(selector) {
    const point = await this.evaluate(`(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
    })()`);
    if (!point) throw new Error(`missing element: ${selector}`);
    return point;
  }

  async mouse(type, point, extra = {}) {
    await this.cdp.send(
      "Input.dispatchMouseEvent",
      { type, x: point.x, y: point.y, button: "left", clickCount: 1, ...extra },
      this.sessionId,
    );
  }

  async click(selector) {
    const point = await this.center(selector);
    await this.mouse("mouseMoved", point, { button: "none" });
    await this.mouse("mousePressed", point);
    await this.mouse("mouseReleased", point);
  }

  async type(text) {
    for (const character of text) {
      await this.cdp.send(
        "Input.dispatchKeyEvent",
        { type: "keyDown", text: character, unmodifiedText: character },
        this.sessionId,
      );
      await this.cdp.send("Input.dispatchKeyEvent", { type: "keyUp" }, this.sessionId);
    }
  }

  // 조작 시작 뒤 Event Timing에 잡힌 가장 긴 입력 처리 시간이 화면 피드백 시간이다.
  async feedbackSince(startedAt) {
    // 관찰 콜백은 화면 반영 뒤에 온다. 느린 환경에서도 두 프레임과 여유 시간을 기다린 뒤 읽는다.
    await this.evaluate(
      "new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(done, 0))))",
    );
    await sleep(200);
    const durations = await this.evaluate(
      `window.__measureEvents
        .filter((entry) => entry.interactionId > 0 && entry.startTime >= ${startedAt})
        .map((entry) => entry.duration)`,
    );
    if (durations.length === 0) return { duration_ms: EVENT_TIMING_FLOOR_MS, below_floor: true };
    return { duration_ms: Math.max(...durations) };
  }

  async measureInteraction(metricName, action) {
    const before = await this.metricCount(metricName);
    const startedAt = await this.evaluate("performance.now()");
    await action();
    const metric = await this.metricAfter(metricName, before);
    const feedback = await this.feedbackSince(startedAt);
    return { result: { duration_ms: metric.duration_ms }, feedback };
  }

  // 재지 않는 조작도 반영이 끝날 때까지 기다려 다음 측정에 섞이지 않게 한다.
  async settle(metricName, action) {
    const before = await this.metricCount(metricName);
    await action();
    await this.metricAfter(metricName, before);
  }

  setQuery(value) {
    return this.settle("filter-result", () =>
      this.evaluate(`(() => {
        const input = document.querySelector('[name="query"]');
        input.value = ${JSON.stringify(value)};
        input.dispatchEvent(new Event("input"));
      })()`),
    );
  }

  async wheel(selector, deltaY, times, gapMs) {
    const point = await this.center(selector);
    for (let step = 0; step < times; step += 1) {
      await this.mouse("mouseWheel", point, { button: "none", deltaX: 0, deltaY });
      await sleep(gapMs);
    }
  }

  async framesDuring(gesture) {
    await this.evaluate("window.__measureFrames.start()");
    await gesture();
    await sleep(500);
    return frameStats(await this.evaluate("window.__measureFrames.stop()"));
  }

  async traceDuring(gesture, traceFile) {
    await this.cdp.send(
      "Tracing.start",
      { categories: TRACE_CATEGORIES, options: "record-until-full", transferMode: "ReturnAsStream" },
      this.sessionId,
    );
    const tracingComplete = this.cdp.waitForEvent("Tracing.tracingComplete", this.sessionId);
    const marker = `deliciousmap-trace-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const startMarker = `${marker}-start`;
    const endMarker = `${marker}-end`;
    await this.evaluate(`console.timeStamp(${JSON.stringify(startMarker)})`);
    await this.evaluate("window.__measureFrames.start()");
    let traceText;
    let timestamps = [];
    try {
      await gesture();
      await sleep(500);
      await this.evaluate(`console.timeStamp(${JSON.stringify(endMarker)})`);
    } finally {
      timestamps = await this.evaluate("window.__measureFrames.stop()").catch(() => []);
      await this.cdp.send("Tracing.end", {}, this.sessionId);
      const { stream } = await tracingComplete;
      traceText = await readTrace(this.cdp, this.sessionId, stream);
    }
    fs.mkdirSync(path.dirname(traceFile), { recursive: true });
    fs.writeFileSync(traceFile, zlib.gzipSync(traceText));
    return {
      frames: frameStats(timestamps),
      trace: summarizeTrace(traceText, { startMarker, endMarker }),
    };
  }

  async heapUsedBytes() {
    const { metrics } = await this.cdp.send("Performance.getMetrics", {}, this.sessionId);
    return metrics.find((metric) => metric.name === "JSHeapUsedSize")?.value ?? null;
  }

  async close() {
    this.unsubscribe();
    await this.cdp.send("Target.closeTarget", { targetId: this.targetId }).catch(() => {});
  }
}

async function dragMap(page) {
  const start = await page.center("#map");
  await page.mouse("mouseMoved", start, { button: "none" });
  await page.mouse("mousePressed", start);
  for (let step = 1; step <= 30; step += 1) {
    await page.mouse("mouseMoved", { x: start.x - step * 6, y: start.y - step * 3 });
    await sleep(16);
  }
  await page.mouse("mouseReleased", { x: start.x - 180, y: start.y - 90 });
}

// 캐시 없는 새 컨텍스트에서 한 번 방문하며 첫 방문·장부·검색·필터·선택·프레임을 잰다.
// 중간 단계가 실패해도 그 전에 잰 값은 run에 남는다.
async function measureColdRun(context, url, query, run, traceDirectory, environmentName, runIndex) {
  const page = await Page.open(context.browser, context.browserContextId);
  try {
    run["first-visit"] = await page.navigate(url);
    // 첫 준비 직후 이어지는 타일 내려받기와 조작 시간이 겹치지 않게 잠시 기다린다.
    await sleep(SETTLE_MS);

    // 입력창을 누르는 포커스 조작은 글자 입력 피드백에 섞지 않는다.
    await page.click('[name="query"]');
    await sleep(200);
    const search = await page.measureInteraction("filter-result", () => page.type(query));
    run["search-result"] = search.result;
    run["search-feedback"] = search.feedback;

    const selection = await page.measureInteraction("marker-selection", () =>
      page.click(".search-result"),
    );
    run["selection-detail"] = selection.result;
    run["selection-feedback"] = selection.feedback;
    await page.setQuery("");

    const filter = await page.measureInteraction("filter-result", () =>
      page.click('[data-visits="1"]'),
    );
    run["filter-result"] = filter.result;
    run["filter-feedback"] = filter.feedback;
    await page.settle("filter-result", () => page.click('[data-visits="all"]'));

    run.frames = {};
    run.traces = {};
    const measureGesture = (name, gesture) =>
      page.traceDuring(
        gesture,
        path.join(traceDirectory, environmentName, `cold-${runIndex}`, `${name}.json.gz`),
      );
    const zoom = await measureGesture("zoom", () => page.wheel("#map", -240, 3, 150));
    run.frames.zoom = zoom.frames;
    run.traces.zoom = zoom.trace;
    const drag = await measureGesture("drag", () => dragMap(page));
    run.frames.drag = drag.frames;
    run.traces.drag = drag.trace;

    const records = await page.measureInteraction("records-first-list", () =>
      page.click('[data-tab="records"]'),
    );
    run["records-first-list"] = records.result;
    const scroll = await measureGesture("scroll", () =>
      page.wheel("[data-records-list]", 200, 20, 16),
    );
    run.frames.scroll = scroll.frames;
    run.traces.scroll = scroll.trace;
    run.heap_used_bytes = await page.heapUsedBytes();
  } finally {
    await page.close();
  }
}

// cdp 연결, 컨텍스트별 측정 환경, 페이지 세션 대기를 한 묶음으로 넘긴다.
async function withContext(browser, environment, work) {
  const { browserContextId } = await browser.cdp.send("Target.createBrowserContext", {
    disposeOnDetach: true,
  });
  browser.contexts.set(browserContextId, environment);
  try {
    return await work({ browser, browserContextId });
  } finally {
    browser.contexts.delete(browserContextId);
    await browser.cdp.send("Target.disposeBrowserContext", { browserContextId }).catch(() => {});
  }
}

function recordAttempt(attempts, name, value) {
  (attempts[name] ??= []).push(value);
}

async function measureEnvironment(browser, environment, target, log, traceDirectory, environmentName) {
  const { url, query, runs } = target;
  const attempts = {};
  // 실패한 회차의 단계와 사유. 값을 얻지 못한 시나리오는 횟수가 모자라 미측정이 된다.
  const failures = [];
  const frames = { zoom: [], drag: [], scroll: [] };
  const traces = { zoom: [], drag: [], scroll: [] };
  const diagnostics = { first_visit_transferred_bytes: [], heap_used_bytes: [] };

  for (let index = 0; index < runs; index += 1) {
    const run = {};
    try {
      // 첫 방문은 매번 새 컨텍스트라 HTTP 캐시와 서비스 워커가 모두 비어 있다.
      await withContext(browser, environment, (context) =>
        measureColdRun(context, url, query, run, traceDirectory, environmentName, index + 1),
      );
      log(`cold ${index + 1}/${runs}: first-visit ${run["first-visit"].duration_ms}ms`);
    } catch (error) {
      failures.push({ phase: "cold", run: index + 1, error: error.message });
      log(`cold ${index + 1}/${runs}: ${error.message}`);
    }
    for (const name of Object.keys(SCENARIOS)) if (run[name]) recordAttempt(attempts, name, run[name]);
    for (const gesture of Object.keys(frames)) {
      if (run.frames?.[gesture]) frames[gesture].push(run.frames[gesture]);
      if (run.traces?.[gesture]) traces[gesture].push(run.traces[gesture]);
    }
    if (run["first-visit"]) {
      diagnostics.first_visit_transferred_bytes.push(run["first-visit"].transferred_bytes);
    }
    if (run.heap_used_bytes !== undefined) diagnostics.heap_used_bytes.push(run.heap_used_bytes);
  }

  // 재방문은 한 컨텍스트에서 캐시와 서비스 워커를 채운 뒤 매번 새 탭으로 연다.
  await withContext(browser, environment, async (context) => {
    let warm;
    try {
      warm = await Page.open(browser, context.browserContextId);
      await warm.navigate(url);
      await warm.waitFor(
        "navigator.serviceWorker.ready.then((registration) => Boolean(registration.active))",
        "service worker",
      );
    } catch (error) {
      failures.push({ phase: "warm-up", run: 0, error: error.message });
      log(`warm-up: ${error.message}`);
      return;
    } finally {
      await warm?.close();
    }
    for (let index = 0; index < runs; index += 1) {
      let page;
      try {
        page = await Page.open(browser, context.browserContextId);
        const visit = await page.navigate(url);
        const controlled = await page.evaluate("Boolean(navigator.serviceWorker.controller)");
        recordAttempt(attempts, "revisit", { ...visit, service_worker: controlled });
        log(`warm ${index + 1}/${runs}: revisit ${visit.duration_ms}ms`);
      } catch (error) {
        failures.push({ phase: "revisit", run: index + 1, error: error.message });
        log(`warm ${index + 1}/${runs}: ${error.message}`);
      } finally {
        await page?.close();
      }
    }
  });

  const summaries = {};
  for (const [name, scenario] of Object.entries(SCENARIOS)) {
    summaries[name] = judge(attempts[name] ?? [], scenario.target_ms, REQUIRED_RUNS);
  }
  const tracing = {
    source: "CDP Tracing",
    criteria: {
      frame_budget_ms: roundMilliseconds(FRAME_MS),
      stutter_frame_ms: roundMilliseconds(STUTTER_FRAME_MS),
      freeze_frame_ms: FREEZE_FRAME_MS,
      long_task_ms: LONG_TASK_MS,
      verdict: "pass only when all measured attempts have no stutter or freeze; fewer than 20 is unmeasured",
    },
    gestures: Object.fromEntries(
      Object.entries(traces).map(([gesture, attemptsForGesture]) => [
        gesture,
        { attempts: attemptsForGesture, summary: judgeTrace(attemptsForGesture, REQUIRED_RUNS) },
      ]),
    ),
  };
  return { attempts, failures, summaries, frames, tracing, diagnostics };
}

function describeFile(file) {
  const body = fs.readFileSync(file);
  const payload = JSON.parse(body.toString("utf8"));
  return {
    bytes: body.length,
    sha256: crypto.createHash("sha256").update(body).digest("hex"),
    count: (payload.markers ?? payload.records).length,
    schema_version: payload.schema_version,
  };
}

function git(args) {
  return childProcess.execFileSync("git", args, { encoding: "utf8" }).trim();
}

// 검색어는 실제 마커의 상호 첫 글자로 정해 결과가 비지 않게 한다.
function chooseQuery(markers) {
  const [busiest] = [...markers].sort((left, right) => right.visit_count - left.visit_count);
  if (!busiest) throw new Error("no markers to search: measure a city with markers");
  return Array.from(busiest.merchant.normalize("NFKC").trim())[0];
}

function traceDirectory(requested) {
  const directory = path.resolve(
    requested ?? fs.mkdtempSync(path.join(os.tmpdir(), "deliciousmap-traces-")),
  );
  const repository = path.resolve(process.cwd());
  const relative = path.relative(repository, directory);
  if (relative === "" || (relative !== ".." && !relative.startsWith(`..${path.sep}`))) {
    throw new Error(`trace directory must be outside the repository: ${directory}`);
  }
  fs.mkdirSync(directory, { recursive: true });
  return directory;
}

async function main(argv) {
  const { values } = util.parseArgs({
    args: argv,
    options: {
      city: { type: "string" },
      site: { type: "string", default: "dist" },
      runs: { type: "string", default: String(REQUIRED_RUNS) },
      environments: { type: "string", default: "desktop,mobile" },
      chrome: { type: "string" },
      out: { type: "string" },
      "trace-dir": { type: "string" },
      headed: { type: "boolean", default: false },
    },
  });
  if (!values.city) throw new Error("--city is required");
  const environmentNames = values.environments.split(",");
  for (const name of environmentNames) {
    if (!ENVIRONMENTS[name]) throw new Error(`unknown environment: ${name}`);
  }
  const runs = Number(values.runs);
  if (!Number.isInteger(runs) || runs < 1) throw new Error(`--runs must be a positive integer`);
  const site = path.resolve(values.site);
  const cityDirectory = path.join(site, values.city);
  const markersFile = path.join(cityDirectory, "markers.json");
  if (!fs.existsSync(markersFile)) throw new Error(`build the city first: ${markersFile}`);
  const markers = JSON.parse(fs.readFileSync(markersFile, "utf8")).markers;
  const query = chooseQuery(markers);
  const chromePath = values.chrome ?? process.env.CHROME_PATH ?? DEFAULT_CHROME[process.platform];
  const tracesPath = traceDirectory(values["trace-dir"]);

  const server = createStaticServer(site);
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(SITE_PORT, "127.0.0.1", resolve);
  });
  const log = (line) => process.stderr.write(`${line}\n`);
  log(`trace files: ${tracesPath}`);
  let stop;
  try {
    const launched = await launchChrome(chromePath, values.headed);
    stop = launched.stop;
    const { cdp } = launched;
    const contexts = new Map();
    const sessionFor = await attachAutomatically(cdp, (id) => contexts.get(id));
    const browser = { cdp, contexts, sessionFor };
    const version = await cdp.send("Browser.getVersion");
    const { gpu } = await cdp.send("SystemInfo.getInfo");
    const target = { url: `http://127.0.0.1:${SITE_PORT}/${values.city}/`, query, runs };
    const result = {
      measured_at: new Date().toISOString(),
      code_commit: git(["rev-parse", "HEAD"]),
      worktree_clean: git(["status", "--porcelain"]) === "",
      city: values.city,
      files: {
        "markers.json": describeFile(markersFile),
        "records.json": describeFile(path.join(cityDirectory, "records.json")),
      },
      host: {
        platform: `${os.type()} ${os.release()}`,
        cpu: os.cpus()[0]?.model,
        logical_cpus: os.cpus().length,
        memory_bytes: os.totalmem(),
        node: process.version,
        browser: version.product,
        gpu_renderer: gpu.auxAttributes?.glRenderer ?? null,
        gpu_compositing: gpu.featureStatus?.gpu_compositing ?? null,
        headless: !values.headed,
        // 헤드리스에는 화면 주사율이 없다. 프레임 값의 median_frame_ms가 실제 갱신 주기다.
        refresh_rate: values.headed ? "display" : "none (headless)",
      },
      conditions: {
        required_runs: REQUIRED_RUNS,
        runs,
        query,
        settle_ms: SETTLE_MS,
        input: "CDP mouse and key events; touch emulation only on mobile",
        selection: "first search result, not a map marker tap",
        server: "cache-control: public, max-age=0, must-revalidate + weak ETag + gzip",
        performance_recording: {
          source: "CDP Tracing",
          trace_files: "stored outside the repository; only summaries are written to the result JSON",
          frame_budget_ms: roundMilliseconds(FRAME_MS),
          stutter_frame_ms: roundMilliseconds(STUTTER_FRAME_MS),
          freeze_frame_ms: FREEZE_FRAME_MS,
          long_task_ms: LONG_TASK_MS,
        },
        environments: Object.fromEntries(environmentNames.map((name) => [name, ENVIRONMENTS[name]])),
      },
      environments: {},
    };
    for (const name of environmentNames) {
      log(`== ${name}`);
      result.environments[name] = await measureEnvironment(
        browser,
        ENVIRONMENTS[name],
        target,
        log,
        tracesPath,
        name,
      );
    }
    const rows = environmentNames.flatMap((environment) =>
      Object.keys(SCENARIOS).map((scenario) => ({
        environment,
        scenario,
        summary: result.environments[environment].summaries[scenario],
      })),
    );
    const json = `${JSON.stringify(result, null, 2)}\n`;
    if (values.out) fs.writeFileSync(values.out, json);
    process.stdout.write(`${markdownTable(rows)}\n`);
  } finally {
    await stop?.();
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}

if (require.main === module) {
  main(process.argv.slice(2)).catch((error) => {
    process.stderr.write(`measure: ${error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = {
  ENVIRONMENTS,
  SCENARIOS,
  createStaticServer,
  frameStats,
  judge,
  judgeTrace,
  markdownTable,
  summarizeTrace,
};
