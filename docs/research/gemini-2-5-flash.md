# Gemini 2.5 Flash API 사실 조사

- 티켓: [#4 Gemini 2.5 Flash API 사실 조사](https://github.com/snowjaewon/OfficialDeliciousMap/issues/4) (맵 #1의 자식)
- 조사일: 2026-09-09
- 목적: 파이프라인 안의 ②헤더 매핑 · ③비식당 판별을 Gemini 2.5 Flash로 돌릴 때 필요한 API 사실과 비용·시간 추정치. 프로토타입 티켓(#10)이 이 결과를 쓴다.
- 출처 원칙: ai.google.dev 공식 문서, docs.cloud.google.com(Vertex) 공식 문서, `google-genai` SDK(설치본 2.22.0 소스 + PyPI), Google AI Studio 콘솔의 실측값만. 2차 블로그는 쓰지 않았다.

## 0. 먼저 알아야 할 두 가지

1. **문서가 3.x 세대로 넘어가 있다.** 2026-09 현재 ai.google.dev 가이드 페이지(구조화 출력·thinking·caching·batch·tokens)는 예시를 `gemini-3.8-flash` + 새 Interactions API(`client.interactions.create`)로 쓴다. 2.5 Flash는 여전히 GA이고 `generateContent`(`client.models.generate_content`)로 호출한다. 2.5 전용 수치(thinking_budget 범위 등)는 Vertex 문서와 SDK 소스에서 확인했다.
2. **Vertex AI 모델 페이지에 2.5 Flash / 2.5 Flash-Lite 모두 "Retirement date: October 20, 2026"이 적혀 있다.** ([2.5 Flash](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash), [2.5 Flash-Lite](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash-lite)) 반면 Gemini API(ai.google.dev)의 [Deprecations](https://ai.google.dev/gemini-api/docs/deprecations) 페이지는 두 GA 모델에 "No shutdown date announced"라고 되어 있다. 수집은 9/20 이전 개발자 PC에서 끝나므로 이번 제출에는 영향이 없지만, **10/20 이후 재수집은 모델 교체가 필요할 수 있다.** 모델 ID는 설정값으로 빼 둔다.

## 1. 사실 표

| 항목 | 값 | 출처 |
|---|---|---|
| 모델 ID | `gemini-2.5-flash` (GA, 2025-06-17), `gemini-2.5-flash-lite` (GA, 2025-07-22). 프리뷰(`-preview-09-2025`)는 이미 종료 | [models/gemini-2.5-flash](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash), [models/gemini-2.5-flash-lite](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite), [deprecations](https://ai.google.dev/gemini-api/docs/deprecations) |
| 컨텍스트 | 입력 1,048,576 / 출력 65,536 토큰 (두 모델 동일). 지식 컷오프 2025-01 | 위 모델 페이지 |
| 지원 기능 | Structured outputs, Caching, Batch API, Thinking, Function calling 등 (두 모델 동일) | 위 모델 페이지 |
| **구조화 출력** | `response_mime_type="application/json"` + `response_schema`(OpenAPI 3.0 부분집합; pydantic 모델을 그대로 넘길 수 있음) 또는 `response_json_schema`(표준 JSON Schema). SDK 주석: "If response_schema doesn't process your schema correctly, try using response_json_schema instead." SDK는 JSON Schema를 직접 넘기는 쪽을 권장 | [SDK 레퍼런스](https://googleapis.github.io/python-genai/genai.html) `GenerateContentConfig.response_schema`, 설치본 `google/genai/types.py` |
| 구조화 출력 제약 | 지원 키워드: `type`(string/number/integer/boolean/object/array/null), `title`, `description`, `properties`, `required`, `additionalProperties`, `enum`, `format`(date-time/date/time), `minimum`/`maximum`, `items`/`prefixItems`/`minItems`/`maxItems`. 문서의 Limitations: "Not all JSON Schema features are supported." / "Very large or deeply nested schemas may be rejected." 구체적 크기 상한은 문서에 없음. 스키마 준수 ≠ 의미 정확 → 앱 쪽 검증 필수 | [structured-output](https://ai.google.dev/gemini-api/docs/structured-output) |
| **요금 — 2.5 Flash (유료)** | 입력 $0.30 / 1M (text·image·video), 출력 $2.50 / 1M (**thinking 토큰 포함**). 캐시 읽기 $0.03 / 1M, 캐시 저장 $1.00 / 1M tokens·hour. Batch: 입력 $0.15, 출력 $1.25 | [pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| **요금 — 2.5 Flash-Lite (유료)** | 입력 $0.10 / 1M, 출력 $0.40 / 1M (thinking 포함). 캐시 $0.01 / 1M, 저장 $1.00 / 1M·h. Batch: 입력 $0.05, 출력 $0.20 | 같은 페이지 |
| 무료 티어 요금 | 두 모델 모두 입력·출력 "Free of charge". 단, **무료 티어 입력은 "Used to improve our products: Yes"**, 유료는 No. 캐시·Batch는 무료 티어 "Not available" | 같은 페이지 |
| **Thinking 끄기** | 2.5 세대는 `thinking_config=types.ThinkingConfig(thinking_budget=N)`. SDK 주석: "0 is DISABLED. -1 is AUTOMATIC." 미설정 시 자동(최대 8,192). 범위: 2.5 Flash 1–24,576 / Flash-Lite 512–24,576 / 둘 다 기본 Auto(≤8,192). Vertex 문서: "If you set thinking_budget to 0 when using Gemini 2.5 Flash and Gemini 2.5 Flash-Lite, no thought content is returned with the response." 3.x용 `thinking_level`을 2.5에 쓰면 에러. Gemini API 표에는 2.5 Flash 기본 thinking **On**, Flash-Lite 기본 **Off** | 설치본 `types.py` `ThinkingConfig`, [Vertex thinking](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/thinking), [Gemini API thinking](https://ai.google.dev/gemini-api/docs/thinking), [REST ThinkingConfig](https://ai.google.dev/api/generate-content) |
| Thinking 과금 | 출력 단가로 과금(위 "including thinking tokens"). `usage_metadata.thoughts_token_count`로 확인. 끄면 그 비용이 0 | pricing, Vertex thinking 예시(`ThoughtsTokenCount`) |
| **레이트 리밋 — 무료** | 2.5 Flash: **5 RPM / 250K TPM / 20 RPD**. 2.5 Flash-Lite: **10 RPM / 250K TPM / 20 RPD** (2026-09-09, AI Studio 무료 티어 프로젝트에서 실측 표시값) | [AI Studio Rate Limit](https://aistudio.google.com/rate-limit) — 문서는 "View your active rate limits in AI Studio"로 안내하고 표를 싣지 않는다 |
| **레이트 리밋 — Tier 1** | 2.5 Flash: **1,000 RPM / 1M TPM / 10,000 RPD**. 2.5 Flash-Lite: **4,000 RPM / 4M TPM / RPD Unlimited** (같은 화면의 "Compare tiers: Tier 1") | 같은 화면 |
| 티어 조건 | Tier 1 = 결제 계정 연결(즉시), 스펜드 캡 $250. Tier 2 = $100 결제 + 3일. 스펜드 기반 한도 Tier 1 $10 / 10분. 한도는 프로젝트 단위, RPD는 태평양시 자정 리셋. "Specified rate limits are not guaranteed" | [rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits) |
| **Batch API** | 있음. "50% of the standard interactive API cost". 목표 처리 24시간("in majority of cases, it is much quicker"). 입력: 인라인(<20MB) 또는 JSONL 파일(≤2GB, `client.files.upload`). 요청별 `config`(구조화 출력 포함) 허용. 결과 6주 보관. Tier 1 큐 상한: 2.5 Flash **3,000,000** 토큰, Flash-Lite **10,000,000** 토큰(활성 배치 합산) | [batch-mode](https://ai.google.dev/gemini-api/docs/batch-mode), rate-limits "Batch enqueued tokens" |
| **컨텍스트 캐싱** | 암시적 캐시는 2.5 이상 기본 켜짐, 최소 **2,048 토큰**(2.5 Flash; Vertex는 "Gemini 2 family models: 2,048"로 Flash-Lite 포함). 명시적 캐시 기본 TTL 60분, 최소 1분, 저장 $1/1M·h. 헤더 매핑 프롬프트(~1.5k)는 최소치 미만이라 캐시 대상이 아님 | [caching](https://ai.google.dev/gemini-api/docs/caching), [Vertex context-cache-overview](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview) |
| **한국어 토큰 비율** | 문서 기준은 영어 "about 4 characters per token". **실측(아래 §2): 한국어 표 텍스트는 약 1.0–1.2 글자/토큰**, 즉 영어 대비 글자당 3배 가까이 토큰이 든다 | [tokens](https://ai.google.dev/gemini-api/docs/tokens) + §2 실측 |
| SDK | `pip install google-genai` (PyPI 2.22.0, 2026-09-02, Python ≥3.10). 구 `google-generativeai`는 쓰지 않는다 | [PyPI](https://pypi.org/project/google-genai/) |
| 키 발급 | **Google AI Studio** → [aistudio.google.com/apikey](https://aistudio.google.com/apikey). 새 키는 서비스 계정에 묶인 "auth key". **Vertex 경로**(`enterprise=True, project=, location=` 또는 `GOOGLE_GENAI_USE_ENTERPRISE=true` + `GOOGLE_CLOUD_PROJECT/LOCATION`; 구 `vertexai=True`도 인자로 남아 있음)는 GCP 프로젝트·ADC가 필요해 이 프로젝트엔 과함 | [api-key](https://ai.google.dev/gemini-api/docs/api-key), SDK `Client.__init__` |
| 키 보관 | SDK가 읽는 env: `GEMINI_API_KEY`, `GOOGLE_API_KEY`(둘 다 있으면 GOOGLE_API_KEY 우선, 경고 로그). 문서: "Never check API keys into source control", "Read keys from environment variables rather than configuration files", 프로덕션은 Secret Manager, 결제 알림 설정, 유출 시 새 키 발급→교체→구 키 비활성→로그 감사. **"Unrestricted standard keys will be rejected starting September 2026"** → 키 제한(IP/사이트) 설정 필요 | api-key 페이지, 설치본 `_api_client.get_env_api_key` |

## 2. 한국어 토큰 비율 실측

- 이 PC에는 Gemini 키가 없어 `client.models.count_tokens`는 못 돌렸다. AI Studio Playground는 무료 계정에서 2.5 Flash가 잠겨 있다("Upgrade to unlock Gemini 2.5 Flash").
- 대신 **Vertex 로컬 토크나이저**(`google-cloud-aiplatform[tokenization]`, `vertexai.preview.tokenization.get_tokenizer_for_model`)로 쟀다. 이 패키지는 `gemini-1.5-flash`까지만 지원해(2.5는 `ValueError: not supported`) **1.5 토크나이저 값이다. 2.5의 정확한 값은 프로토타입 첫 호출의 `usage_metadata.prompt_token_count`로 다시 잰다.**

| 샘플 | 글자 수 | 토큰 | 글자/토큰 |
|---|---|---|---|
| 헤더 행 `연번\t일자\t집행목적\t집행장소\t집행대상\t집행금액(원)\t결제방법\t비고` | 36 | 36 | 1.00 |
| 데이터 행 1줄 (`1\t2026-01-05\t간부 업무협의 오찬\t강남면옥\t직원 5명\t85,000\t카드`) | 45 | 43 | 1.05 |
| 업추비 표 10행 (헤더+10 데이터행, 탭 구분) | 542 | 511 | 1.06 |
| 상호 100개 콤마 목록 | 898 | 799 | 1.12 |
| 실제 상호 14개 (강남면옥, 을지로골뱅이, …) | 90 | 76 | 1.18 |
| 같은 헤더의 영문판 (`No\tDate\tPurpose\tPlace\t…`) | 56 | 19 | 2.95 |

결론: 한국어 업추비 표는 **거의 1글자 = 1토큰**. 티켓의 가정(헤더 매핑 1.5k 입력 ≈ 헤더+상위 행 1,400자 안팎, 상호 100개 배치 3k 입력 ≈ 상호 100개 900토큰 + 지시문·스키마 2k)은 이 비율과 맞는다.

## 3. 최소 호출 예시 (`google-genai`)

```python
import os
from pydantic import BaseModel
from google import genai
from google.genai import types

client = genai.Client()  # GEMINI_API_KEY 또는 GOOGLE_API_KEY를 env에서 읽음

class HeaderMap(BaseModel):
    date_col: int | None
    place_col: int | None
    amount_col: int | None
    amount_unit: str  # "원" | "천원"

resp = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=header_and_top_rows_text,
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=HeaderMap,                       # 또는 response_json_schema=HeaderMap.model_json_schema()
        thinking_config=types.ThinkingConfig(thinking_budget=0),  # 0 = DISABLED
        temperature=0,
    ),
)
mapped = HeaderMap.model_validate_json(resp.text)  # resp.parsed 도 있음
print(resp.usage_metadata.prompt_token_count,
      resp.usage_metadata.candidates_token_count,
      resp.usage_metadata.thoughts_token_count)  # thinking 껐으면 None/0
```

Batch(JSONL 한 줄 = `{"key": "...", "request": {"contents": [...], "generationConfig": {...}}}`) → `client.files.upload(file=...)` → `client.batches.create(model=..., src=uploaded.name)` → `client.batches.get(name=...)` 폴링(`JOB_STATE_SUCCEEDED`까지). ([batch-mode](https://ai.google.dev/gemini-api/docs/batch-mode))

## 4. 비용·시간 추정

가정: 유료 Tier 1, thinking **끔**(`thinking_budget=0`), 표의 유료 단가. thinking을 켜면 기본 Auto가 호출당 수백~수천 토큰을 출력 단가로 더 쓴다(아래 "thinking 켤 때" 행은 호출당 1,000 thinking 토큰 가정).

### (a) 헤더 매핑 — 15,000파일을 헤더 시그니처로 중복 제거 → 300–800 호출, 호출당 1.5k 입력 / 150 출력

| | 300 호출 | 800 호출 |
|---|---|---|
| 토큰 | 입력 0.45M / 출력 0.045M | 입력 1.2M / 출력 0.12M |
| 2.5 Flash | $0.135 + $0.11 = **$0.25** | $0.36 + $0.30 = **$0.66** |
| 2.5 Flash-Lite | **$0.06** | **$0.17** |
| Flash, thinking 켤 때(+1k/호출) | +$0.75 → $1.00 | +$2.00 → $2.66 |
| 시간 (Tier 1, Flash) | 1M TPM·1,000 RPM은 여유. 동시 10개 × 호출당 2–4초 → **2–5분** | |
| 시간 (무료 티어) | **20 RPD**에 막힘 → 800호출 = 40일. 사실상 불가 | |

### (b) 비식당 판별 — 고유 상호 2만 개를 100개씩 → ~200 호출, 호출당 3k 입력 / 1k 출력

| | 값 |
|---|---|
| 토큰 | 입력 0.6M / 출력 0.2M |
| 2.5 Flash | $0.18 + $0.50 = **$0.68** |
| 2.5 Flash-Lite | $0.06 + $0.08 = **$0.14** |
| Flash, thinking 켤 때(+1k/호출) | +$0.50 → $1.18 |
| 시간 (Tier 1) | 출력 1k 토큰이라 호출당 5–10초. 동시 10개 → **2–4분**. 배치로 보내면 24h 목표지만 비용 절반($0.34) |
| 시간 (무료 티어) | 20 RPD → 10일. 불가 |

**(a)+(b) 합계: Flash 약 $1–1.5, Flash-Lite 약 $0.3. thinking을 켜도 Flash $4 이내.**

### 최악 — 15,000파일을 낱개로 전체 표까지 보냄 (2.5k 입력 / 800 출력)

| | 값 |
|---|---|
| 토큰 | 입력 37.5M / 출력 12M |
| 2.5 Flash 실시간 | $11.25 + $30.00 = **$41.25** |
| 2.5 Flash Batch (50%) | **$20.63** |
| 2.5 Flash-Lite 실시간 / Batch | **$8.55** / **$4.28** |
| Flash, thinking 켤 때(+1k/호출 = +15M 출력) | +$37.5 → 약 $79 |
| 시간 (Tier 1, Flash 실시간) | **RPD 10,000 < 15,000 → 최소 2일**(태평양시 자정 리셋). TPM 1M 기준 입력만 38분 |
| 시간 (Tier 1, Flash-Lite 실시간) | RPD 무제한, 4M TPM → 동시 20개 × 5초 → **약 1시간** |
| 시간 (Batch) | Tier 1 큐 상한 Flash 3M 토큰 → 약 13회 분할 제출; Flash-Lite 10M → 4–5회. 각 24h 목표 |

### 함의

- 헤더 매핑 + 배치 분류 설계면 **비용은 $1–2 수준으로 무시할 만하다.** 결정 변수는 비용이 아니라 **레이트 리밋과 thinking 설정**이다.
- **무료 티어(20 RPD)로는 프로토타입조차 하루 20호출**이라, 결제 계정을 연결해 Tier 1로 올려야 한다(즉시 승격, 스펜드 캡 $250). 무료 티어는 입력이 제품 개선에 쓰인다는 점도 있다(공개 데이터라 문제는 없음).
- **분류 작업은 `thinking_budget=0` + `temperature=0`으로 시작**하고, 품질이 모자라면 예산을 올린다. 기본값(Auto ≤8,192)을 그대로 두면 출력 과금이 최대 수십 배로 뛴다.
- 전량 추출 폴백(최악 케이스)을 열어 두면 Flash에서는 RPD 때문에 2일이 걸린다. 폴백은 Flash-Lite 또는 Batch로 보내는 게 맞다.
- 캐싱은 프롬프트가 2,048 토큰 미만이면 아예 대상이 아니다. 지시문+스키마를 앞에 고정해 두면 암시적 캐시 혜택은 자동으로 붙는다.
- 10/20 Vertex 종료 공지를 감안해 모델 ID는 `.env`/설정으로 빼고, 산출물(레코드)에 모델 ID·프롬프트 버전을 남긴다.

## 5. 확인하지 못한 것

- 2.5 Flash 실제 토크나이저의 한국어 비율(1.5 토크나이저 값으로 대신함). 프로토타입 첫 호출에서 `usage_metadata`로 확정.
- Tier 2/3 한도(Tier 1까지만 확인). 이번 규모엔 Tier 1이면 충분.
- `propertyOrdering` 등 2.5 시절 구조화 출력 세부 제약은 현재 문서에서 사라져 확인 불가. 스키마는 평평하게, enum 위주로.
