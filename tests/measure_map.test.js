const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const {
  ENVIRONMENTS,
  createStaticServer,
  frameStats,
  judgeTrace,
  judge,
  markdownTable,
  summarizeTrace,
} = require("../scripts/measure_map.js");

function runs(values) {
  return values.map((duration_ms) => ({ duration_ms }));
}

test("20회 중 느린 순 두 번째 값이 목표 이내면 합격이다", () => {
  const values = [...Array(18).fill(100), 3900, 5200];

  assert.deepEqual(judge(runs(values), 4000, 20), {
    runs: 20,
    second_slowest_ms: 3900,
    maximum_ms: 5200,
    target_ms: 4000,
    verdict: "pass",
  });
});

test("느린 순 두 번째 값이 목표를 넘으면 불합격이다", () => {
  const values = [...Array(18).fill(100), 4100, 4200];

  assert.equal(judge(runs(values), 4000, 20).verdict, "fail");
});

test("정해진 횟수를 채우지 못한 측정은 합격이 아니라 미측정이다", () => {
  const summary = judge(runs(Array(19).fill(10)), 4000, 20);

  assert.equal(summary.verdict, "unmeasured");
  assert.equal(summary.runs, 19);
});

test("모의 모바일은 결정한 네트워크·CPU 조건을 CDP 단위로 건다", () => {
  const mobile = ENVIRONMENTS.mobile;

  // 10Mbps = 1,250,000 B/s, 1Mbps = 125,000 B/s.
  assert.deepEqual(mobile.network, {
    offline: false,
    latency: 100,
    downloadThroughput: 1250000,
    uploadThroughput: 125000,
  });
  assert.equal(mobile.cpu_slowdown, 4);
  assert.equal(mobile.device.mobile, true);
});

test("데스크톱은 네트워크·CPU를 제한하지 않는다", () => {
  assert.equal(ENVIRONMENTS.desktop.network, null);
  assert.equal(ENVIRONMENTS.desktop.cpu_slowdown, 1);
  assert.equal(ENVIRONMENTS.desktop.device.mobile, false);
});

test("프레임 간격에서 60Hz 기준으로 놓친 프레임과 가장 긴 프레임을 센다", () => {
  // 간격 16.7 · 16.7 · 50 · 16.7ms. 50ms 한 번은 60Hz에서 두 프레임을 놓친 것이다.
  const timestamps = [1000, 1016.7, 1033.4, 1083.4, 1100.1];

  assert.deepEqual(frameStats(timestamps), {
    frames: 4,
    median_frame_ms: 16.7,
    longest_frame_ms: 50,
    dropped_frames: 2,
  });
});

test("헤드리스에는 화면 주사율이 없으므로 간격 중앙값으로 실제 갱신 주기를 남긴다", () => {
  // 간격 8.3 · 8.3 · 8.4 · 25ms. 120Hz로 돌던 중 한 번 끊긴 기록이다.
  const timestamps = [0, 8.3, 16.6, 25, 50];

  assert.equal(frameStats(timestamps).median_frame_ms, 8.4);
});

async function withSite(files, check) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "measure-site-"));
  const root = path.join(base, "dist");
  fs.mkdirSync(root);
  fs.writeFileSync(path.join(base, "secret.txt"), "루트 밖");
  for (const [name, content] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(root, name)), { recursive: true });
    fs.writeFileSync(path.join(root, name), content);
  }
  const server = createStaticServer(root);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    await check(`http://127.0.0.1:${server.address().port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    fs.rmSync(base, { recursive: true, force: true });
  }
}

test("정적 서버는 디렉터리 주소에 index.html을 내주고 매번 재검증하게 한다", async () => {
  await withSite({ "gwangju/index.html": "<p>광주</p>" }, async (origin) => {
    const response = await fetch(`${origin}/gwangju/`);

    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type"), /^text\/html; charset=utf-8/);
    assert.equal(response.headers.get("cache-control"), "public, max-age=0, must-revalidate");
    assert.equal(await response.text(), "<p>광주</p>");
  });
});

test("정적 서버는 같은 ETag의 재요청에 본문 없이 304로 답한다", async () => {
  await withSite({ "gwangju/records.json": '{"records":[]}' }, async (origin) => {
    const first = await fetch(`${origin}/gwangju/records.json`);
    const etag = first.headers.get("etag");

    const again = await fetch(`${origin}/gwangju/records.json`, {
      headers: { "if-none-match": etag },
    });

    assert.ok(etag);
    assert.match(first.headers.get("content-type"), /^application\/json/);
    assert.equal(again.status, 304);
    assert.equal(await again.text(), "");
  });
});

test("정적 서버는 압축을 받는 브라우저에 gzip으로 보낸다", async () => {
  const records = JSON.stringify({ records: Array(200).fill({ merchant: "광주식당" }) });
  await withSite({ "gwangju/records.json": records }, async (origin) => {
    const compressed = await fetch(`${origin}/gwangju/records.json`, {
      headers: { "accept-encoding": "gzip" },
    });
    const plain = await fetch(`${origin}/gwangju/records.json`, {
      headers: { "accept-encoding": "identity" },
    });

    assert.equal(compressed.headers.get("content-encoding"), "gzip");
    assert.ok(Number(compressed.headers.get("content-length")) < Buffer.byteLength(records));
    assert.equal(await compressed.text(), records);
    assert.equal(plain.headers.get("content-encoding"), null);
    assert.equal(await plain.text(), records);
  });
});

test("정적 서버는 없는 파일과 루트 밖 경로를 404로 거부한다", async () => {
  await withSite({ "index.html": "ok" }, async (origin) => {
    const missing = await fetch(`${origin}/seoul/markers.json`);
    // fetch는 %2e%2e를 정규화하므로 구분자를 인코딩해 서버에 ..가 그대로 닿게 한다.
    const outside = await fetch(`${origin}/..%2fsecret.txt`);

    assert.equal(missing.status, 404);
    assert.equal(outside.status, 404);
  });
});

test("결과 표는 환경·시나리오별 두 번째로 느린 값과 최대값, 판정을 적는다", () => {
  const table = markdownTable([
    {
      environment: "mobile",
      scenario: "first-visit",
      summary: {
        runs: 20,
        second_slowest_ms: 3120.4,
        maximum_ms: 3890,
        target_ms: 4000,
        verdict: "pass",
      },
    },
    {
      environment: "desktop",
      scenario: "records-first-list",
      summary: {
        runs: 3,
        second_slowest_ms: 40,
        maximum_ms: 41,
        target_ms: 2000,
        verdict: "unmeasured",
      },
    },
  ]);

  assert.equal(
    table,
    [
      "| 환경 | 시나리오 | 목표 | 횟수 | 느린 순 2번째 | 최대 | 판정 |",
      "| --- | --- | ---: | ---: | ---: | ---: | --- |",
      "| 모의 모바일 | 첫 방문 | 4,000ms | 20 | 3,120.4ms | 3,890ms | 충족 |",
      "| 데스크톱 | 장부 첫 목록 | 2,000ms | 3 | 40ms | 41ms | 미측정 |",
    ].join("\n"),
  );
});

test("실패한 시도는 값이 없으므로 횟수에 넣지 않는다", () => {
  const attempts = [...runs(Array(19).fill(10)), { error: "timeout" }];

  const summary = judge(attempts, 4000, 20);

  assert.equal(summary.runs, 19);
  assert.equal(summary.verdict, "unmeasured");
});

test("성능 기록은 프레임 지연·끊김·멈춤과 긴 작업을 요약한다", () => {
  const summary = summarizeTrace({
    traceEvents: [
      { name: "FramePresented", ph: "I", ts: 0 },
      { name: "FramePresented", ph: "I", ts: 16667 },
      { name: "FramePresented", ph: "I", ts: 66667 },
      {
        name: "LongAnimationFrame",
        ph: "X",
        ts: 20000,
        dur: 120000,
        args: { data: { url: "https://oapi.map.naver.com/openapi/v3/maps.js" } },
      },
      {
        name: "RunTask",
        ph: "X",
        ts: 20000,
        dur: 120000,
        args: { data: { url: "https://oapi.map.naver.com/openapi/v3/maps.js" } },
      },
    ],
  });

  assert.deepEqual(summary, {
    frames: 2,
    frame_budget_ms: 16.7,
    delayed_frames: 2,
    dropped_frames: 0,
    stutter_count: 1,
    freeze_count: 1,
    longest_frame_ms: 50,
    long_animation_frames: 1,
    longest_long_animation_frame_ms: 120,
    long_tasks: 1,
    longest_long_task_ms: 120,
    source: {
      application: { count: 0, total_ms: 0, maximum_ms: null },
      naver_sdk: { count: 1, total_ms: 120, maximum_ms: 120 },
      other: { count: 0, total_ms: 0, maximum_ms: null },
      dominant: "naver_sdk",
    },
    verdict: "fail",
  });
});

test("성능 기록에 프레임 증거가 없으면 합격이 아니라 미측정이다", () => {
  const summary = summarizeTrace({ traceEvents: [] });

  assert.equal(summary.verdict, "unmeasured");
  assert.equal(summary.frames, 0);
});

test("PipelineReporter의 실제 표시·드롭 상태를 프레임 증거로 사용한다", () => {
  const summary = summarizeTrace({
    traceEvents: [
      {
        name: "PipelineReporter",
        ph: "b",
        ts: 0,
        args: { frame_reporter: { state: "STATE_PRESENTED_ALL" } },
      },
      {
        name: "PipelineReporter",
        ph: "b",
        ts: 16667,
        args: { frame_reporter: { state: "STATE_DROPPED" } },
      },
      {
        name: "PipelineReporter",
        ph: "b",
        ts: 66667,
        args: { frame_reporter: { state: "STATE_PRESENTED_ALL" } },
      },
    ],
  });

  assert.equal(summary.frames, 1);
  assert.equal(summary.dropped_frames, 1);
  assert.equal(summary.delayed_frames, 3);
  assert.equal(summary.verdict, "fail");
});

test("성능 기록 요약은 조작 시작·끝 marker 밖의 프레임을 제외한다", () => {
  const summary = summarizeTrace(
    {
      traceEvents: [
        { name: "start", ph: "I", ts: 100000 },
        { name: "FramePresented", ph: "I", ts: 110000 },
        { name: "FramePresented", ph: "I", ts: 126000 },
        { name: "FramePresented", ph: "I", ts: 176000 },
        { name: "FramePresented", ph: "I", ts: 500000 },
        { name: "end", ph: "I", ts: 200000 },
      ],
    },
    { startMarker: "start", endMarker: "end" },
  );

  assert.equal(summary.frames, 2);
  assert.equal(summary.longest_frame_ms, 50);
});

test("긴 작업의 URL로 네이버 SDK와 애플리케이션 원인을 분리한다", () => {
  const summary = summarizeTrace({
    traceEvents: [
      { name: "FramePresented", ph: "I", ts: 0 },
      { name: "FramePresented", ph: "I", ts: 16667 },
      {
        name: "RunTask",
        ph: "X",
        ts: 20000,
        dur: 60000,
        args: { data: { url: "http://127.0.0.1:8765/gwangju/app.js" } },
      },
      {
        name: "RunTask",
        ph: "X",
        ts: 90000,
        dur: 70000,
        args: { data: { url: "https://map.naver.com/sdk.js" } },
      },
    ],
  });

  assert.deepEqual(summary.source, {
    application: { count: 1, total_ms: 60, maximum_ms: 60 },
    naver_sdk: { count: 1, total_ms: 70, maximum_ms: 70 },
    other: { count: 0, total_ms: 0, maximum_ms: null },
    dominant: "naver_sdk",
  });
});

test("상위 AnimationFrame에 URL이 없어도 겹친 스크립트로 원인을 귀속한다", () => {
  const summary = summarizeTrace({
    traceEvents: [
      { name: "FramePresented", ph: "I", ts: 0 },
      { name: "FramePresented", ph: "I", ts: 16667 },
      { name: "AnimationFrame", ph: "X", ts: 20000, dur: 60000, args: {} },
      {
        name: "FunctionCall",
        ph: "X",
        ts: 25000,
        dur: 50000,
        args: { data: { url: "https://oapi.map.naver.com/openapi/v3/maps.js" } },
      },
    ],
  });

  assert.equal(summary.long_animation_frames, 1);
  assert.equal(summary.source.naver_sdk.count, 1);
  assert.equal(summary.source.dominant, "naver_sdk");
});

test("100ms 긴 작업은 짧은 Long Animation Frame이 함께 있어도 멈춤으로 판정한다", () => {
  const summary = summarizeTrace({
    traceEvents: [
      { name: "FramePresented", ph: "I", ts: 0 },
      { name: "FramePresented", ph: "I", ts: 16667 },
      { name: "AnimationFrame", ph: "X", ts: 20000, dur: 60000, args: {} },
      { name: "RunTask", ph: "X", ts: 25000, dur: 120000, args: {} },
    ],
  });

  assert.equal(summary.long_animation_frames, 1);
  assert.equal(summary.freeze_count, 1);
  assert.equal(summary.verdict, "fail");
});

test("긴 프레임보다 짧은 AnimationFrame 안의 긴 작업도 원인으로 남긴다", () => {
  const summary = summarizeTrace({
    traceEvents: [
      { name: "FramePresented", ph: "I", ts: 0 },
      { name: "FramePresented", ph: "I", ts: 16667 },
      { name: "AnimationFrame", ph: "X", ts: 20000, dur: 40000, args: {} },
      {
        name: "RunTask",
        ph: "X",
        ts: 25000,
        dur: 120000,
        args: { data: { url: "http://127.0.0.1:8765/gwangju/app.js" } },
      },
    ],
  });

  assert.equal(summary.long_animation_frames, 0);
  assert.equal(summary.source.application.count, 1);
  assert.equal(summary.source.dominant, "application");
  assert.equal(summary.freeze_count, 1);
});

test("20회 trace 중 하나라도 끊기면 성능 판정은 미달이다", () => {
  const attempts = [
    ...Array(19).fill({ verdict: "pass", longest_frame_ms: 16.7 }),
    { verdict: "fail", longest_frame_ms: 50 },
  ];

  assert.deepEqual(judgeTrace(attempts, 20), {
    runs: 20,
    passing_runs: 19,
    stutter_runs: 1,
    freeze_runs: 0,
    longest_frame_ms: 50,
    verdict: "fail",
  });
});

test("20회 trace를 채우지 못하면 성능 판정은 미측정이다", () => {
  const summary = judgeTrace([{ verdict: "pass", longest_frame_ms: 16.7 }], 20);

  assert.equal(summary.verdict, "unmeasured");
  assert.equal(summary.runs, 1);
});
