"""Gemini 모델 어댑터. 요청·응답·사용량 해석만 하고 판정·사람 확정·한도를 정하지 않는다.

용도(후보 비교·헤더 매핑·비식당 판별)마다 지시문·응답 스키마·출력 상한이 다르고 요청 방식은 같다.
"""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, get_args

from pydantic import ValidationError

from deliciousmap.contracts import (
    ClassificationAnswer,
    ClassificationReply,
    ClassificationStatus,
    ColumnRole,
    ComparisonAnswer,
    HeaderMapAnswer,
    HeaderMapReply,
    ModelReply,
    ReplyError,
    Usage,
)
from deliciousmap.transport import MAX_RESPONSE_BYTES, HttpTransport, JsonTransport

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
KEY_HEADER = "x-goog-api-key"
KEY_VARIABLE = "GEMINI_API_KEY"
MODEL_VARIABLE = "GEMINI_MODEL"
# 적용 단가는 제공자 요금 페이지에서 확인해 적는다. 확인하지 못하면 호출하지 않는다.
INPUT_PRICE_VARIABLE = "GEMINI_INPUT_USD_PER_MTOK"
OUTPUT_PRICE_VARIABLE = "GEMINI_OUTPUT_USD_PER_MTOK"
PRICE_UNIT = Decimal(1_000_000)
# 3.x는 thinking_budget 대신 thinkingLevel로 사고 토큰을 끈다.
THINKING_LEVEL = "minimal"

# 프롬프트·응답 스키마가 바뀌면 올린다. 제안 캐시는 이 버전을 구별한다.
PROMPT_VERSION = "restoration-compare-1"
# 출력 상한은 요청으로 강제해 비용 상한을 실제로 묶는다.
MAX_OUTPUT_TOKENS = 512
# 한국어는 대략 1.0~1.2 글자/토큰(#4 실측)이므로 문자 수를 입력 토큰의 상한으로 본다.
MAX_PROMPT_CHARS = 4_000
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

HEADER_SYSTEM_INSTRUCTION = """너는 한국 지방자치단체 업무추진비 집행내역 표의 헤더 매핑기다.
입력은 원본 시트에서 비어 있지 않은 상위 행을 옮긴 격자다.
R 뒤의 숫자는 원본 행 번호, [ ] 안은 열 번호다.
행 추출은 코드가 한다. 너는 다음만 판정한다. 모든 행 번호는 입력에 적힌 원본 행 번호로 답한다.
1. layout: table(열이 고정된 표), key_value(항목명-값 쌍이 한 건을 이루는 카드형), none(표 없음).
2. header_rows: 열 이름이 적힌 행 번호. 제목·기관명·단위 표기 행은 헤더가 아니다.
   두 줄 헤더면 둘 다. 없으면 빈 배열.
3. data_start_row: 실제 집행 1건이 처음 나오는 행. 위쪽의 계·합계 요약 행은 건너뛴다.
4. columns: 아래 역할에 해당하는 열만 넣는다. 한 역할에 열 하나.
   spent_on: 집행(사용·결제·승인)일. 날짜와 시각이 한 칸이면 spent_on.
   month / day: 날짜가 월과 일 두 칸으로 갈라진 경우에만. time: 시각만 있는 칸.
   department: 부서명. 사용자·집행자·직위·사람 이름 열은 department가 아니며 넣지 않는다.
   merchant: 상호(식당·가맹점·거래처·사용처·업소명). 주소만 있는 칸은 넣지 않는다.
   purpose: 집행목적·내역·적요. amount_krw: 집행 금액(인원수·건수와 혼동하지 말 것).
   인원·결제방법·비목·주소·연번 열은 넣지 않는다. 헤더 글자와 데이터 값의 모양을 함께 본다.
5. amount_unit: won / thousand_won / unknown. 천원 표기가 있으면 thousand_won, 원 표기면 won.
   표기가 없으면 값의 크기로 판단한다.
6. year_hint: 날짜 칸에 연도가 없을 때 제목에서 읽은 연도. 없으면 null.
이전 판정의 코드 검증 실패가 적혀 있으면 그 행과 항목을 다시 살펴 판정을 고친다."""
HEADER_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "layout": {"type": "STRING", "enum": ["table", "key_value", "none"]},
        "header_rows": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "data_start_row": {"type": "INTEGER", "nullable": True},
        "columns": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "column": {"type": "INTEGER"},
                    "role": {"type": "STRING", "enum": list(get_args(ColumnRole))},
                },
                "required": ["column", "role"],
            },
        },
        "amount_unit": {"type": "STRING", "enum": ["won", "thousand_won", "unknown"]},
        "year_hint": {"type": "INTEGER", "nullable": True},
    },
    "required": ["layout", "header_rows", "data_start_row", "columns", "amount_unit", "year_hint"],
    "propertyOrdering": [
        "layout",
        "header_rows",
        "data_start_row",
        "columns",
        "amount_unit",
        "year_hint",
    ],
}

CLASSIFY_SYSTEM_INSTRUCTION = """번호가 붙은 상호마다 식당 여부를 판정한다.
restaurant: 일반 음식점·카페·제과점. 카페·제과점에서 다과를 산 경우도 식당이다.
non_restaurant: 온라인 유통·결제 채널, 마트·편의점 등 물품 판매처, 주유·꽃·택시 관련 업소,
기관 내부 식당·매점, 그 밖에 음식점이 아닌 업소.
pending: 상호만으로 식당 여부를 확정할 수 없을 때. 추측으로 식당이나 비식당을 고르지 않는다.
웹 탐색이나 검색을 하지 않는다. 상호 표기를 고치지 않고 받은 그대로 merchant에 적는다.
reason에는 업종이나 판단 근거를 20자 이내로 적는다. 모든 번호에 빠짐없이 한 번씩 답한다."""
CLASSIFY_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "verdicts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "index": {"type": "INTEGER"},
                    "merchant": {"type": "STRING"},
                    "status": {"type": "STRING", "enum": list(get_args(ClassificationStatus))},
                    "reason": {"type": "STRING"},
                },
                "required": ["index", "merchant", "status", "reason"],
                "propertyOrdering": ["index", "merchant", "status", "reason"],
            },
        }
    },
    "required": ["verdicts"],
}


@dataclass(frozen=True)
class Pricing:
    """1M 토큰당 USD. 제공자의 과금 항목 정의를 따르고 합계를 다시 더하지 않는다."""

    input_usd: Decimal
    output_usd: Decimal


@dataclass(frozen=True)
class Settings:
    # 비밀값이다. 요청 헤더 밖으로 내보내지 않는다.
    key: str = field(repr=False)
    model: str
    pricing: Pricing


@dataclass(frozen=True)
class _Generated:
    """응답 한 건의 해석. 원문은 남기지 않고 구조화 출력의 본문만 넘긴다."""

    text: str | None
    error: ReplyError | None
    usage: Usage | None


class _GeminiModel:
    """공통 요청·응답 해석. 용도별 지시문·스키마·출력 상한은 하위 클래스가 정한다."""

    prompt_version: str
    max_prompt_chars: int
    max_output_tokens: int
    system_instruction: str
    response_schema: dict[str, Any]

    def __init__(self, settings: Settings, transport: JsonTransport) -> None:
        self._key = settings.key
        self.model = settings.model
        self.pricing = settings.pricing
        self.transport = transport

    def ceiling_usd(self, prompt: str) -> Decimal:
        """요청 하나의 비용 상한. 지시문·스키마까지 실제로 보내는 본문 전체를 입력으로 센다."""
        return self.cost_usd(
            Usage(input_tokens=len(self._body(prompt)), output_tokens=self.max_output_tokens)
        )

    def cost_usd(self, usage: Usage) -> Decimal:
        return (
            usage.input_tokens * self.pricing.input_usd
            + usage.output_tokens * self.pricing.output_usd
        ) / PRICE_UNIT

    def _generate(self, prompt: str) -> _Generated:
        """제공자 오류를 안전한 코드로 바꾼다. 응답 원문은 어디에도 남기지 않는다."""
        try:
            body = self.transport.post(
                f"{BASE_URL}/{self.model}:generateContent",
                self._body(prompt).encode("utf-8"),
                {KEY_HEADER: self._key, "Content-Type": "application/json"},
            )
        except Exception:
            return _Generated(None, "unavailable", None)
        if len(body) > MAX_RESPONSE_BYTES:
            return _Generated(None, "invalid_response", None)
        try:
            payload = json.loads(body.decode("utf-8"))
            usage = _usage(payload)
        except (ValueError, TypeError, LookupError, UnicodeDecodeError):
            return _Generated(None, "invalid_response", None)
        try:
            candidate = payload["candidates"][0]
            # 잘린 응답을 근거 부족과 혼동하지 않는다.
            if candidate.get("finishReason") not in (None, "STOP"):
                return _Generated(None, "incomplete_response", usage)
            text = "".join(str(part["text"]) for part in candidate["content"]["parts"])
        except (ValueError, TypeError, LookupError):
            return _Generated(None, "invalid_response", usage)
        return _Generated(text, None, usage)

    def _body(self, prompt: str) -> str:
        """용도에 필요한 것만 싣는다. 도구·검색 연동은 구성하지 않는다."""
        request = {
            "systemInstruction": {"parts": [{"text": self.system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
                "responseSchema": self.response_schema,
                "thinkingConfig": {"thinkingLevel": THINKING_LEVEL},
            },
        }
        return json.dumps(request, ensure_ascii=False)


class GeminiComparator(_GeminiModel):
    prompt_version = PROMPT_VERSION
    max_prompt_chars = MAX_PROMPT_CHARS
    max_output_tokens = MAX_OUTPUT_TOKENS
    system_instruction = SYSTEM_INSTRUCTION
    response_schema = RESPONSE_SCHEMA

    def compare(self, prompt: str) -> ModelReply:
        generated = self._generate(prompt)
        if generated.text is None:
            return ModelReply(status="error", error=generated.error, usage=generated.usage)
        try:
            answer = ComparisonAnswer.model_validate_json(generated.text)
        except ValidationError:
            return ModelReply(status="error", error="invalid_response", usage=generated.usage)
        return ModelReply(status="ok", answer=answer, usage=generated.usage)


class GeminiHeaderMapper(_GeminiModel):
    prompt_version = "header-map-1"
    # 상위 12행 × 셀 40자 안팎. 이보다 크면 입력을 자르지 않고 미해결로 둔다.
    max_prompt_chars = 8_000
    max_output_tokens = 1_024
    system_instruction = HEADER_SYSTEM_INSTRUCTION
    response_schema = HEADER_RESPONSE_SCHEMA

    def map(self, prompt: str) -> HeaderMapReply:
        generated = self._generate(prompt)
        if generated.text is None:
            return HeaderMapReply(status="error", error=generated.error, usage=generated.usage)
        try:
            answer = HeaderMapAnswer.model_validate_json(generated.text)
        except ValidationError:
            return HeaderMapReply(status="error", error="invalid_response", usage=generated.usage)
        return HeaderMapReply(status="ok", answer=answer, usage=generated.usage)


class GeminiClassifier(_GeminiModel):
    prompt_version = "classify-1"
    max_prompt_chars = 4_000
    # 상호 40개의 판정·짧은 근거가 들어가는 크기.
    max_output_tokens = 4_096
    system_instruction = CLASSIFY_SYSTEM_INSTRUCTION
    response_schema = CLASSIFY_RESPONSE_SCHEMA

    def classify(self, prompt: str) -> ClassificationReply:
        generated = self._generate(prompt)
        if generated.text is None:
            return ClassificationReply(status="error", error=generated.error, usage=generated.usage)
        try:
            answer = ClassificationAnswer.model_validate_json(generated.text)
        except ValidationError:
            return ClassificationReply(
                status="error", error="invalid_response", usage=generated.usage
            )
        return ClassificationReply(status="ok", answer=answer, usage=generated.usage)


def settings_from_environment(environ: Mapping[str, str] | None = None) -> Settings | None:
    """키가 없으면 모델을 구성하지 않고, 단가를 확인할 수 없으면 설정 오류로 알린다."""
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
    return Settings(
        key, model, Pricing(prices[INPUT_PRICE_VARIABLE], prices[OUTPUT_PRICE_VARIABLE])
    )


@dataclass(frozen=True)
class Models:
    """구성된 용도별 모델. 셋은 같은 키·모델·단가를 쓴다."""

    comparator: GeminiComparator
    header_mapper: GeminiHeaderMapper
    classifier: GeminiClassifier


def models_from_environment(
    transport: JsonTransport | None = None, environ: Mapping[str, str] | None = None
) -> Models | None:
    settings = settings_from_environment(environ)
    if settings is None:
        return None
    client = transport or HttpTransport()
    return Models(
        GeminiComparator(settings, client),
        GeminiHeaderMapper(settings, client),
        GeminiClassifier(settings, client),
    )


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
