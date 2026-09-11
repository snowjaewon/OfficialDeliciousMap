"""지정 건의 후보 비교와 제안 보존. 복원명·좌표를 확정하거나 예산을 직접 계산하지 않는다."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from deliciousmap.budget import Budget, BudgetUnavailable
from deliciousmap.contracts import (
    CandidateLookup,
    ComparisonRequest,
    EvidenceScope,
    GeocodeResult,
    LlmPurpose,
    ModelReply,
    PlaceCandidate,
    Record,
    RestorationProposal,
    Usage,
)
from deliciousmap.identity import digest, normalized
from deliciousmap.storage import ArtifactStore, attempt

POLICY_VERSION = "comparison-1"
PURPOSE: LlmPurpose = "restoration_comparison"
# 상호를 확정하지 못한 판정만 복원 비교의 대상이다. 주소·지점·좌표·조회 문제는 상호 문제가 아니다.
NAME_UNCONFIRMED = frozenset({"unconfirmed_name", "no_match"})


class ComparisonModel(Protocol):
    """추린 입력 하나를 비교한 답변만 공급한다. 인증·요청 구성·사용량 해석은 구현 안에 둔다."""

    model: str
    prompt_version: str
    max_prompt_chars: int

    def ceiling_usd(self, prompt: str) -> Decimal: ...
    def cost_usd(self, usage: Usage) -> Decimal: ...
    def compare(self, prompt: str) -> ModelReply: ...


@dataclass(frozen=True)
class Subject:
    """비교 대상 하나를 가리키는 고정 정보. 어떤 답변이 와도 이 범위를 벗어나지 않는다."""

    scope: EvidenceScope
    merchant: str
    model: str
    prompt_version: str
    request_key: str

    def withheld(self, reason: str) -> RestorationProposal:
        return self._decided(status="withheld", reason=reason)

    def proposed(self, candidate: PlaceCandidate, rationale: str) -> RestorationProposal:
        return self._decided(
            status="proposed",
            reason="candidate_supported",
            proposed_merchant=candidate.merchant,
            candidate_source=candidate.source,
            rationale=rationale,
        )

    def _decided(self, **decision: object) -> RestorationProposal:
        return RestorationProposal.model_validate(
            {
                "scope": self.scope,
                "merchant": self.merchant,
                "model": self.model,
                "prompt_version": self.prompt_version,
                "request_key": self.request_key,
                **decision,
            }
        )


def request_key(model: ComparisonModel, designation: ComparisonRequest, prompt: str) -> str:
    """모델·프롬프트·지정·후보·근거가 다르면 다른 요청이다."""
    return digest(
        {
            "policy": POLICY_VERSION,
            "model": model.model,
            "prompt_version": model.prompt_version,
            "designation": designation.model_dump(mode="json"),
            "prompt": prompt,
        }
    )


def build_prompt(record: Record, lookup: CandidateLookup) -> str:
    """코드로 추린 후보 상호·주소·출처와 필요한 근거만 적는다.

    원본 전체·HTML·레코드의 다른 열은 넣지 않는다.
    """
    lines = [f"원본 표기: {record.merchant}", "근거:"]
    for fact in lookup.facts:
        lines.append(
            f"- 상호={fact.merchant}"
            f" 지점={fact.branch if fact.branch is not None else '미확인'}"
            f" 주소={fact.address or '없음'}"
            f" 출처={fact.source}"
        )
    lines.append("후보:")
    for candidate in lookup.candidates:
        lines.append(
            f"- id={candidate.source.source_id}"
            f" 상호={candidate.merchant}"
            f" 지점={candidate.branch if candidate.branch is not None else '미확인'}"
            f" 주소={candidate.address or '없음'}"
            f" 출처={candidate.source.provider} {candidate.source.reference}"
        )
    return "\n".join(lines)


def comparable(result: GeocodeResult) -> bool:
    """자료 대조와 사람 검토로도 상호를 확정하지 못한 건만 비교 대상이다."""
    return (
        result.status == "failed"
        and result.reason in NAME_UNCONFIRMED
        and result.restoration is None
        and result.confirmation is None
    )


def resolve(
    store: ArtifactStore,
    budget: Budget,
    model: ComparisonModel,
    records: tuple[Record, ...],
    lookups: tuple[CandidateLookup, ...],
    results: tuple[GeocodeResult, ...],
    designations: tuple[ComparisonRequest, ...],
    *,
    retry_failed: bool = False,
) -> tuple[RestorationProposal, ...]:
    """담당자가 지정한 건만 비교하고 결과를 제안으로 남긴다. 판정은 바꾸지 않는다."""
    if not designations:
        return ()
    by_record = {record.record_id: record for record in records}
    prepared = {lookup.scope.record_id: lookup for lookup in lookups}
    decided = {result.record_id: result for result in results}
    proposals = []
    for designation in designations:
        record_id = designation.scope.record_id
        record = by_record.get(record_id)
        result = decided.get(record_id)
        if record is None or result is None:
            continue
        lookup = prepared[record_id]
        prompt = build_prompt(record, lookup)
        key = request_key(model, designation, prompt)
        previous = store.cached_proposal(key)
        if previous is not None:
            proposal = RestorationProposal.model_validate(previous.value)
            if proposal.status == "proposed" or not retry_failed:
                proposals.append(proposal)
                continue
        subject = Subject(
            scope=designation.scope,
            merchant=record.merchant,
            model=model.model,
            prompt_version=model.prompt_version,
            request_key=key,
        )
        proposal = _compare(budget, model, subject, lookup, result, prompt, attempt(previous))
        store.remember_proposal(key, proposal, previous)
        proposals.append(proposal)
    return tuple(proposals)


def _compare(
    budget: Budget,
    model: ComparisonModel,
    subject: Subject,
    lookup: CandidateLookup,
    result: GeocodeResult,
    prompt: str,
    attempt_number: int,
) -> RestorationProposal:
    """과금이 일어나는 요청은 모두 공통 예산 모듈을 거친다."""
    if not comparable(result):
        return subject.withheld("not_unresolved")
    if not lookup.candidates:
        return subject.withheld("no_candidates")
    if len(prompt) > model.max_prompt_chars:
        return subject.withheld("oversized_request")
    try:
        reply = budget.spend(
            f"{subject.request_key}-{attempt_number}",
            PURPOSE,
            model.model,
            model.ceiling_usd(prompt),
            _reservation_evidence(subject),
            lambda: model.compare(prompt),
            model.cost_usd,
        )
    except BudgetUnavailable as exc:
        return subject.withheld(exc.reason)
    if reply.status == "error" and reply.error is not None:
        return subject.withheld(reply.error)
    return _grounded(subject, lookup, reply)


def _grounded(subject: Subject, lookup: CandidateLookup, reply: ModelReply) -> RestorationProposal:
    """제시한 후보를 가리키고 사유를 남긴 답변만 제안이 된다."""
    answer = reply.answer
    if answer is None or not answer.supported:
        return subject.withheld("no_supported_candidate")
    chosen = next(
        (
            candidate
            for candidate in lookup.candidates
            if candidate.source.source_id == answer.candidate_source_id
            and normalized(candidate.merchant) == normalized(answer.restored_merchant)
        ),
        None,
    )
    if chosen is None or not answer.rationale.strip():
        return subject.withheld("ungrounded_response")
    return subject.proposed(chosen, answer.rationale.strip()[:500])


def _reservation_evidence(subject: Subject) -> str:
    """상호·주소·응답 원문 없이 어떤 레코드의 비교인지만 남긴다."""
    return f"restoration comparison for record {subject.scope.record_id}"
