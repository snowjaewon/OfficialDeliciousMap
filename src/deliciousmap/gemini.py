"""지정 Gemini 모델 어댑터. 요청·응답·사용량 해석만 하고 판정·사람 확정·한도를 정하지 않는다."""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from deliciousmap.contracts import ComparisonAnswer, ModelReply, Usage
from deliciousmap.transport import MAX_RESPONSE_BYTES, HttpTransport, JsonTransport

# 프롬프트·응답 스키마가 바뀌면 올린다. 제안 캐시는 이 버전을 구별한다.
PROMPT_VERSION = "restoration-compare-1"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
KEY_HEADER = "x-goog-api-key"
KEY_VARIABLE = "GEMINI_API_KEY"
MODEL_VARIABLE = "GEMINI_MODEL"
# 적용 단가는 제공자 요금 페이지에서 확인해 적는다. 확인하지 못하면 호출하지 않는다.
INPUT_PRICE_VARIABLE = "GEMINI_INPUT_USD_PER_MTOK"
OUTPUT_PRICE_VARIABLE = "GEMINI_OUTPUT_USD_PER_MTOK"
PRICE_UNIT = Decimal(1_000_000)
# 출력 상한은 요청으로 강제해 비용 상한을 실제로 묶는다.
MAX_OUTPUT_TOKENS = 512
# 한국어는 대략 1.0~1.2 글자/토큰(#4 실측)이므로 문자 수를 입력 토큰의 상한으로 본다.
MAX_PROMPT_CHARS = 4_000
# 3.x는 thinking_budget 대신 thinkingLevel로 사고 토큰을 끈다.
THINKING_LEVEL = "minimal"
SYSTEM_INSTRUCTION = (
    "제시한 후보와 근거만으로 판단한다. 웹 탐색이나 추가 검색을 하지 않고 "
    "후보에 없는 상호를 만들지 않는다. 좌표를 고르지 않는다. "
    "동일 업소로 볼 근거가 부족하면 supported를 false로 답한다."
)
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "supported": {"type": "BOOLEAN"},
        "candidate_source_id": {"type": "STRING"},
        "restored_merchant": {"type": "STRING"},
        "rationale": {"type": "STRING"},
    },
    "required": ["supported", "candidate_source_id", "restored_merchant", "rationale"],
    "propertyOrdering": ["supported", "candidate_source_id", "restored_merchant", "rationale"],
}


@dataclass(frozen=True)
class Pricing:
    """1M 토큰당 USD. 제공자의 과금 항목 정의를 따르고 합계를 다시 더하지 않는다."""

    input_usd: Decimal
    output_usd: Decimal


class GeminiComparator:
    prompt_version = PROMPT_VERSION
    max_prompt_chars = MAX_PROMPT_CHARS

    def __init__(self, key: str, model: str, pricing: Pricing, transport: JsonTransport) -> None:
        # 비밀값이다. 요청 헤더 밖으로 내보내지 않는다.
        self._key = key
        self.model = model
        self.pricing = pricing
        self.transport = transport

    def ceiling_usd(self, prompt: str) -> Decimal:
        """요청 하나의 비용 상한. 지시문·스키마까지 실제로 보내는 본문 전체를 입력으로 센다."""
        return self.cost_usd(
            Usage(input_tokens=len(_body(prompt)), output_tokens=MAX_OUTPUT_TOKENS)
        )

    def cost_usd(self, usage: Usage) -> Decimal:
        return (
            usage.input_tokens * self.pricing.input_usd
            + usage.output_tokens * self.pricing.output_usd
        ) / PRICE_UNIT

    def compare(self, prompt: str) -> ModelReply:
        """제공자 오류를 안전한 코드로 바꾼다. 응답 원문은 어디에도 남기지 않는다."""
        try:
            body = self.transport.post(
                f"{BASE_URL}/{self.model}:generateContent",
                _body(prompt).encode("utf-8"),
                {KEY_HEADER: self._key, "Content-Type": "application/json"},
            )
        except Exception:
            return ModelReply(status="error", error="unavailable")
        if len(body) > MAX_RESPONSE_BYTES:
            return ModelReply(status="error", error="invalid_response")
        try:
            payload = json.loads(body.decode("utf-8"))
            usage = _usage(payload)
        except (ValueError, TypeError, LookupError, UnicodeDecodeError):
            return ModelReply(status="error", error="invalid_response")
        try:
            candidate = payload["candidates"][0]
            # 잘린 응답을 근거 부족과 혼동하지 않는다.
            if candidate.get("finishReason") not in (None, "STOP"):
                return ModelReply(status="error", error="incomplete_response", usage=usage)
            text = "".join(str(part["text"]) for part in candidate["content"]["parts"])
            answer = ComparisonAnswer.model_validate_json(text)
        except (ValueError, TypeError, LookupError, UnicodeDecodeError):
            return ModelReply(status="error", error="invalid_response", usage=usage)
        return ModelReply(status="ok", answer=answer, usage=usage)


def from_environment(
    transport: JsonTransport | None = None, environ: Mapping[str, str] | None = None
) -> GeminiComparator | None:
    """키가 없으면 비교를 구성하지 않고, 단가를 확인할 수 없으면 설정 오류로 알린다."""
    values = os.environ if environ is None else environ
    key = values.get(KEY_VARIABLE, "").strip()
    if not key:
        return None
    model = values.get(MODEL_VARIABLE, "").strip()
    prices: dict[str, Decimal] = {}
    missing = [] if model else [MODEL_VARIABLE]
    for name in (INPUT_PRICE_VARIABLE, OUTPUT_PRICE_VARIABLE):
        try:
            price = Decimal(values.get(name, "").strip())
        except InvalidOperation:
            missing.append(name)
            continue
        if not price.is_finite() or price <= 0:
            missing.append(name)
            continue
        prices[name] = price
    if missing:
        raise ValueError(f"incomplete gemini configuration: {', '.join(missing)}")
    return GeminiComparator(
        key,
        model,
        Pricing(prices[INPUT_PRICE_VARIABLE], prices[OUTPUT_PRICE_VARIABLE]),
        transport or HttpTransport(),
    )


def _body(prompt: str) -> str:
    """후보 비교에 필요한 것만 싣는다. 도구·검색 연동은 구성하지 않는다."""
    request = {
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "thinkingConfig": {"thinkingLevel": THINKING_LEVEL},
        },
    }
    return json.dumps(request, ensure_ascii=False)


def _usage(payload: object) -> Usage | None:
    """제공자가 알린 항목만 읽는다. totalTokenCount는 합계이므로 다시 더하지 않는다."""
    if not isinstance(payload, dict):
        raise TypeError("model response must be an object")
    metadata = payload.get("usageMetadata")
    if not isinstance(metadata, dict):
        return None
    try:
        prompt_tokens = int(metadata["promptTokenCount"])
        # 사고 토큰은 출력 단가로 과금된다.
        output_tokens = int(metadata.get("candidatesTokenCount", 0)) + int(
            metadata.get("thoughtsTokenCount", 0)
        )
    except (ValueError, TypeError, LookupError):
        return None
    return Usage(input_tokens=prompt_tokens, output_tokens=output_tokens)
