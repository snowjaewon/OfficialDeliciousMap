"""classify 단계. 사람 보정 → 도시 무관 LLM 캐시 → 모델 순으로 상호마다 식당 여부를 정한다(#11).

호출 실패·예산 부족은 판단 보류로 두고 캐시에 남기지 않는다. 다음 실행이 다시 묻는다.
사람 보정은 최종 판정에만 적용하고 공통 캐시를 덮어쓰지 않는다.
"""

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from deliciousmap.budget import Budget, BudgetUnavailable
from deliciousmap.contracts import (
    CacheEntry,
    Classification,
    ClassificationReply,
    ClassificationStatus,
    ClassifyInput,
    ClassifyOutput,
    LlmPurpose,
    ManualCorrection,
    Record,
    Usage,
    Verdict,
)
from deliciousmap.identity import normalized
from deliciousmap.storage import (
    append_cache_entries,
    highest_revision,
    latest_valid,
    read_cache,
)

PURPOSE: LlmPurpose = "classification"
# 한 요청에 묻는 상호 수. 출력 상한 안에서 답을 모두 받을 수 있는 크기로 둔다.
BATCH_SIZE = 40


class Classifier(Protocol):
    model: str
    prompt_version: str
    max_prompt_chars: int

    def ceiling_usd(self, prompt: str) -> Decimal: ...
    def cost_usd(self, usage: Usage) -> Decimal: ...
    def classify(self, prompt: str) -> ClassificationReply: ...


def resolve(
    value: ClassifyInput,
    city: str,
    cache_path: Path,
    budget: Budget,
    model: Classifier | None,
) -> ClassifyOutput:
    names = _names(value)
    corrections = {
        record.record_id: _correction(record, names[record.record_id], value.manual, city)
        for record in value.records
    }
    # 캐시 키는 정규화 상호다. 모델에는 처음 나온 원래 표기를 보인다.
    display: dict[str, str] = {}
    for record in value.records:
        if corrections[record.record_id] is None:
            display.setdefault(normalized(names[record.record_id]), names[record.record_id])
    history = read_cache(cache_path)
    revisions = highest_revision(history)
    verdicts = {key: entry for key, entry in latest_valid(history).items() if key in display}
    failures: dict[str, str] = {}
    unknown = sorted(display.keys() - verdicts.keys())
    for start in range(0, len(unknown), BATCH_SIZE):
        batch = unknown[start : start + BATCH_SIZE]
        if model is None:
            failures.update(dict.fromkeys(batch, "model_not_configured"))
            continue
        answered, reason = _ask(model, budget, batch, [display[key] for key in batch])
        if reason is not None:
            failures.update(dict.fromkeys(batch, reason))
            continue
        entries = tuple(
            CacheEntry(
                key=key,
                revision=revisions.get(key, 0) + 1,
                valid=True,
                evidence=f"{model.model}/{model.prompt_version}",
                value={"status": verdict.status, "reason": verdict.reason},
            )
            for key, verdict in zip(batch, answered, strict=True)
        )
        append_cache_entries(cache_path, entries)
        verdicts.update({entry.key: entry for entry in entries})
    decisions = []
    for record in value.records:
        key = normalized(names[record.record_id])
        correction = corrections[record.record_id]
        if correction is not None:
            status: ClassificationStatus = correction.status
            evidence = f"manual: {correction.evidence}"
        elif key in verdicts:
            entry = verdicts[key]
            status = entry.value["status"]  # type: ignore[assignment]
            evidence = f"llm {entry.evidence} r{entry.revision}: {entry.value['reason'] or '-'}"
        else:
            status, evidence = "pending", f"unclassified: {failures[key]}"
        decisions.append(
            Classification(record_id=record.record_id, status=status, evidence=evidence)
        )
    return ClassifyOutput(decisions=tuple(decisions))


def _names(value: ClassifyInput) -> dict[str, str]:
    """확정 복원명이 있으면 그 이름을 판별한다. 원본 표기는 레코드에 그대로 남는다."""
    restored = {item.record_id: item.restored_merchant for item in value.restorations}
    return {
        record.record_id: restored.get(record.record_id, record.merchant)
        for record in value.records
    }


def _correction(
    record: Record, merchant: str, manual: tuple[ManualCorrection, ...], city: str
) -> ManualCorrection | None:
    """같은 도시의 같은 상호가 기본 범위다. 기관·원본을 밝힌 좁은 보정이 넓은 보정보다 앞선다."""
    matches = [
        item
        for item in manual
        if item.city == city
        and normalized(item.merchant) == normalized(merchant)
        and item.organization in (None, record.organization)
        and item.source_hash in (None, record.source_hash)
    ]
    if not matches:
        return None
    rank = max(_specificity(item) for item in matches)
    chosen = {item.status for item in matches if _specificity(item) == rank}
    if len(chosen) > 1:
        raise ValueError(f"{city}: conflicting manual corrections for record {record.record_id}")
    return next(item for item in matches if _specificity(item) == rank)


def _specificity(item: ManualCorrection) -> int:
    return (item.organization is not None) + 2 * (item.source_hash is not None)


def _ask(
    model: Classifier, budget: Budget, batch: list[str], shown: list[str]
) -> tuple[tuple[Verdict, ...], str | None]:
    prompt = build_prompt(shown)
    if len(prompt) > model.max_prompt_chars:
        return (), "oversized_request"
    try:
        reply = budget.spend(
            f"{PURPOSE}:{uuid.uuid4().hex}",
            PURPOSE,
            model.model,
            model.ceiling_usd(prompt),
            f"classification of {len(batch)} merchants",
            lambda: model.classify(prompt),
            model.cost_usd,
        )
    except BudgetUnavailable as exc:
        return (), exc.reason
    if reply.answer is None:
        return (), reply.error or "invalid_response"
    verdicts = tuple(sorted(reply.answer.verdicts, key=lambda item: item.index))
    # 요청한 번호·상호와 하나도 어긋나지 않아야 답으로 쓴다. 일부만 조용히 채택하지 않는다.
    if [(item.index, normalized(item.merchant)) for item in verdicts] != [
        (index, key) for index, key in enumerate(batch, start=1)
    ]:
        return (), "invalid_response"
    return verdicts, None


def build_prompt(names: list[str]) -> str:
    """고유 상호만 번호와 함께 싣는다. 목적·금액·기관은 판별 근거로 쓰지 않는다."""
    return "\n".join(f"{index}. {name}" for index, name in enumerate(names, start=1))
