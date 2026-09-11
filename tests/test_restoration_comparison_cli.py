"""담당자가 지정한 미해결 복원 건의 LLM 후보 비교를 공개 CLI와 저장된 산출물로 관찰한다."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from deliciousmap.cli import main
from deliciousmap.identity import digest
from deliciousmap.naver import INTERPRETATION_VERSION
from deliciousmap.pipeline import ExecutionContext
from deliciousmap.storage import write_text
from tests.fakes import (
    FakeJsonTransport,
    FakeTransport,
    gemini_answer,
    gemini_body,
    naver_body,
    naver_item,
)
from tests.test_geocoding_cli import payload, prepare, save_input
from tests.test_restoration_cli import (
    FULL_NAME,
    classify_records,
    restore_entry,
    save_restorations,
    truncated_lookup,
)

API_KEY = "합성-제미나이-키"
MODEL = "gemini-3.6-flash"
INPUT_PRICE = "1.50"
OUTPUT_PRICE = "7.50"


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """개발자 PC의 .env 처럼 모델 키와 확인한 단가가 준비된 상태."""
    monkeypatch.setenv("GEMINI_API_KEY", API_KEY)
    monkeypatch.setenv("GEMINI_MODEL", MODEL)
    monkeypatch.setenv("GEMINI_INPUT_USD_PER_MTOK", INPUT_PRICE)
    monkeypatch.setenv("GEMINI_OUTPUT_USD_PER_MTOK", OUTPUT_PRICE)


def run_cli(
    context: ExecutionContext,
    stage: str,
    *extra: str,
    transport: FakeJsonTransport | None = None,
    naver: FakeTransport | None = None,
) -> int:
    return main(
        [
            stage,
            "--city",
            context.target.city.slug,
            "--raw-root",
            str(context.paths.raw_root),
            "--data-root",
            str(context.paths.data_root),
            "--output-root",
            str(context.paths.output_root),
            *extra,
        ],
        cities=(context.target.city,),
        naver_transport=naver,
        model_transport=transport,
    )


def designate(context: ExecutionContext, *record_ids: str) -> None:
    """담당자가 후보 비교를 명시적으로 지정한 미해결 건."""
    write_text(
        context.paths.manual(context.target, "compare"),
        "".join(
            json.dumps(
                {
                    "schema_version": 1,
                    "scope": {
                        "city": context.target.city.slug,
                        "organization": "test-org",
                        "record_id": record_id,
                        "source_hash": "a" * 64,
                    },
                    "evidence": "자료 대조와 사람 검토로 해결하지 못해 후보 비교를 지정",
                },
                ensure_ascii=False,
            )
            + "\n"
            for record_id in record_ids
        ),
    )


def record_spending(context: ExecutionContext, amount: str) -> None:
    """제공자의 사용량 기록으로 확인한 기존 누적액. 없으면 잔액을 가정하지 않는다."""
    write_text(
        context.paths.shared("llm-budget"),
        json.dumps(
            {
                "schema_version": 1,
                "entry_id": "prior-usage-2026-09-10",
                "kind": "prior_usage",
                "purpose": "prior_usage",
                "model": None,
                "amount_usd": amount,
                "evidence": "제공자 사용량 기록으로 확인한 두 개발자의 기존 사용액",
            },
            ensure_ascii=False,
        )
        + "\n",
    )


def ledger(context: ExecutionContext) -> list[dict]:
    path = context.paths.shared("llm-budget")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def proposals(context: ExecutionContext) -> list[dict]:
    path = context.paths.city_dir(context.target) / "restore-proposal-v1.jsonl"
    if not path.exists():
        return []
    return [json.loads(line)["value"] for line in path.read_text(encoding="utf-8").splitlines()]


def results(context: ExecutionContext) -> dict[str, dict]:
    return {item["record_id"]: item for item in payload(context, "geocode")["results"]}


def ready(tmp_path: Path, *, spending: str = "2.50") -> ExecutionContext:
    """자료 대조로 상호를 확정하지 못한 레코드 하나와 확인된 기존 사용액."""
    context = prepare(tmp_path)
    save_input(context, truncated_lookup())
    designate(context, "r1")
    record_spending(context, spending)
    return context


def test_designated_case_keeps_the_model_answer_as_a_proposal_until_a_person_confirms(
    tmp_path: Path, configured: None
) -> None:
    context = ready(tmp_path)
    transport = FakeJsonTransport(gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 0

    # 제안은 복원명도 좌표도 확정하지 않는다. 판정은 그대로 미확정이다.
    result = results(context)["r1"]
    assert result["status"] == "failed"
    assert result["reason"] == "unconfirmed_name"
    assert result["restoration"] is None
    assert result["business_id"] is None

    proposal = proposals(context)[0]
    assert proposal["status"] == "proposed"
    assert proposal["reason"] == "candidate_supported"
    assert proposal["merchant"] == "같은 식당"
    assert proposal["proposed_merchant"] == FULL_NAME
    assert proposal["candidate_source"]["source_id"] == "place-1"
    assert proposal["confirmed"] is False
    assert proposal["model"] == MODEL
    assert proposal["scope"]["record_id"] == "r1"

    # 사람이 확정해야 복원명이 된다. 제안 파일만으로는 판정이 바뀌지 않는다.
    save_restorations(context, restore_entry())
    classify_records(context)
    assert run_cli(context, "geocode", transport=transport) == 0
    confirmed = results(context)["r1"]
    assert confirmed["status"] == "success"
    assert confirmed["confirmed_merchant"] == FULL_NAME
    assert confirmed["restoration"]["restored_merchant"] == FULL_NAME


def test_only_extracted_candidates_and_evidence_reach_the_model_without_web_search(
    tmp_path: Path, configured: None
) -> None:
    context = ready(tmp_path)
    transport = FakeJsonTransport(gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 0

    assert len(transport.bodies) == 1
    body = transport.bodies[0]
    sent = json.dumps(body, ensure_ascii=False)
    # 자동 웹 탐색·검색 연동은 구성하지 않는다.
    assert "tools" not in body
    assert "toolConfig" not in body
    assert "googleSearch" not in sent
    # 추린 후보 상호·주소·출처·근거만 보낸다.
    assert FULL_NAME in sent
    assert "부산 합성로 10" in sent
    assert "place-1" in sent
    # 원본 전체·레코드의 다른 열·비밀값은 보내지 않는다.
    for forbidden in ("출장 식사", "총무과", "a" * 64, API_KEY):
        assert forbidden not in sent
    assert transport.headers[0]["x-goog-api-key"] == API_KEY
    assert MODEL in transport.urls[0]


def test_cases_the_operator_did_not_designate_are_never_sent(
    tmp_path: Path, configured: None
) -> None:
    context = prepare(tmp_path)
    save_input(context, truncated_lookup())
    record_spending(context, "2.50")
    transport = FakeJsonTransport(gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 0
    assert transport.bodies == []
    assert proposals(context) == []
    assert [item["kind"] for item in ledger(context)] == ["prior_usage"]

    # 지정했어도 자료 대조로 이미 해결된 건은 부르지 않는다.
    designate(context, "r1")
    save_restorations(context, restore_entry())
    classify_records(context)
    assert run_cli(context, "geocode", transport=transport) == 0
    assert results(context)["r1"]["status"] == "success"
    assert transport.bodies == []
    assert [item["reason"] for item in proposals(context)] == ["not_unresolved"]


def test_coordinate_selection_never_calls_the_model(tmp_path: Path, configured: None) -> None:
    context = prepare(tmp_path)
    # 상호는 확정됐고 좌표만 없는 건이다. 좌표 선택은 모델에 맡기지 않는다.
    save_input(context, truncated_lookup(latitude=None, longitude=None))
    save_restorations(context, restore_entry())
    classify_records(context)
    designate(context, "r1")
    record_spending(context, "2.50")
    transport = FakeJsonTransport(gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 0
    assert results(context)["r1"]["reason"] == "missing_coordinates"
    assert transport.bodies == []
    assert [item["reason"] for item in proposals(context)] == ["not_unresolved"]


@pytest.mark.parametrize(
    "response,reason",
    [
        (gemini_body(gemini_answer(restored_merchant="지어낸 식당")), "ungrounded_response"),
        (gemini_body(gemini_answer(candidate_source_id="없는-후보")), "ungrounded_response"),
        (gemini_body(gemini_answer(rationale="   ")), "ungrounded_response"),
        (gemini_body(gemini_answer(), finish_reason="MAX_TOKENS"), "incomplete_response"),
        (gemini_body("{잘린 JSON"), "invalid_response"),
        ("<html>제공자 오류 문서</html>".encode(), "invalid_response"),
        (TimeoutError("제공자 원문 오류"), "unavailable"),
        (gemini_body(gemini_answer(supported=False)), "no_supported_candidate"),
    ],
)
def test_ungrounded_or_incomplete_answers_stay_unresolved_with_a_reason(
    tmp_path: Path, configured: None, response: bytes | Exception, reason: str
) -> None:
    context = ready(tmp_path)
    transport = FakeJsonTransport(response)
    assert run_cli(context, "geocode", transport=transport) == 0
    proposal = proposals(context)[0]
    assert proposal["status"] == "withheld"
    assert proposal["reason"] == reason
    assert proposal["proposed_merchant"] is None
    assert proposal["confirmed"] is False
    assert results(context)["r1"]["reason"] == "unconfirmed_name"
    # 응답 원문은 산출물에 남기지 않는다.
    assert "지어낸 식당" not in json.dumps(proposal, ensure_ascii=False)


def test_spending_is_reserved_before_the_call_and_settled_with_actual_usage(
    tmp_path: Path, configured: None
) -> None:
    context = ready(tmp_path)
    transport = FakeJsonTransport(
        gemini_body(prompt_tokens=200, output_tokens=100, thoughts_tokens=20)
    )
    assert run_cli(context, "geocode", transport=transport) == 0
    entries = {item["kind"]: item for item in ledger(context)}
    assert set(entries) == {"prior_usage", "reservation", "settlement"}
    assert entries["reservation"]["purpose"] == "restoration_comparison"
    assert entries["reservation"]["model"] == MODEL
    # 실제 사용량: 입력 200토큰·출력 120토큰(사고 포함). totalTokenCount를 다시 더하지 않는다.
    expected = (
        Decimal("200") * Decimal(INPUT_PRICE) + Decimal("120") * Decimal(OUTPUT_PRICE)
    ) / 1_000_000
    assert Decimal(entries["settlement"]["amount_usd"]) == expected
    assert Decimal(entries["reservation"]["amount_usd"]) >= expected
    assert entries["settlement"]["entry_id"] == entries["reservation"]["entry_id"]


def test_unconfirmed_usage_keeps_the_reservation(tmp_path: Path, configured: None) -> None:
    context = ready(tmp_path)
    transport = FakeJsonTransport(gemini_body(usage=False))
    assert run_cli(context, "geocode", transport=transport) == 0
    kinds = [item["kind"] for item in ledger(context)]
    assert kinds.count("reservation") == 1
    assert "settlement" not in kinds
    assert proposals(context)[0]["status"] == "proposed"


def test_the_shared_limit_withholds_the_call_while_human_review_continues(
    tmp_path: Path, configured: None
) -> None:
    context = ready(tmp_path, spending="14.999999")
    transport = FakeJsonTransport(gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 0
    assert transport.bodies == []
    assert proposals(context)[0]["reason"] == "budget_exhausted"
    assert [item["kind"] for item in ledger(context)] == ["prior_usage"]

    # 예산이 없어도 사람 확인 경로는 그대로 동작한다.
    save_restorations(context, restore_entry())
    classify_records(context)
    assert run_cli(context, "geocode", transport=transport) == 0
    assert results(context)["r1"]["status"] == "success"


def test_unknown_prior_spending_withholds_the_call(tmp_path: Path, configured: None) -> None:
    context = prepare(tmp_path)
    save_input(context, truncated_lookup())
    designate(context, "r1")
    transport = FakeJsonTransport(gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 0
    assert transport.bodies == []
    assert proposals(context)[0]["reason"] == "unknown_prior_usage"


def test_a_held_reservation_lock_withholds_the_call_instead_of_reserving_twice(
    tmp_path: Path, configured: None
) -> None:
    context = ready(tmp_path)
    # 다른 실행이 집행 중이면 직렬화한다. 이중 예약·집행을 만들지 않는다.
    lock = context.paths.shared("llm-budget").with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("다른 실행", encoding="utf-8")
    transport = FakeJsonTransport(gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 0
    assert transport.bodies == []
    assert proposals(context)[0]["reason"] == "concurrent_execution"
    assert [item["kind"] for item in ledger(context)] == ["prior_usage"]

    lock.unlink()
    assert run_cli(context, "geocode", "--retry-failed", transport=transport) == 0
    assert len(transport.bodies) == 1
    assert proposals(context)[-1]["status"] == "proposed"
    assert not lock.exists()


def test_spending_accumulates_across_runs_and_restarts(tmp_path: Path, configured: None) -> None:
    context = ready(tmp_path, spending="2.50")
    transport = FakeJsonTransport(gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 0
    # 새 실행이 장부를 이어 쓴다. 실행·도시·날짜마다 초기화하지 않는다.
    assert [item["kind"] for item in ledger(context)] == [
        "prior_usage",
        "reservation",
        "settlement",
    ]
    committed = sum(
        Decimal(item["amount_usd"]) for item in ledger(context) if item["kind"] != "reservation"
    )
    assert committed > Decimal("2.50")


def test_unchanged_inputs_reuse_the_proposal_and_changed_evidence_asks_again(
    tmp_path: Path, configured: None
) -> None:
    context = ready(tmp_path)
    transport = FakeJsonTransport(gemini_body(), gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 0
    assert run_cli(context, "geocode", transport=transport) == 0
    assert len(transport.bodies) == 1
    assert len(proposals(context)) == 1

    # 후보·근거가 바뀌면 이전 제안을 그대로 다시 쓰지 않는다.
    changed = truncated_lookup()
    changed["candidates"][0]["address"] = "부산 합성로 11"
    changed["facts"][0]["address"] = "부산 합성로 11"
    save_input(context, changed)
    assert run_cli(context, "geocode", transport=transport) == 0
    assert len(transport.bodies) == 2
    assert len(proposals(context)) == 2


def test_withheld_proposals_are_retried_only_when_asked(tmp_path: Path, configured: None) -> None:
    context = ready(tmp_path)
    transport = FakeJsonTransport(TimeoutError("제공자 원문 오류"), gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 0
    assert proposals(context)[0]["reason"] == "unavailable"
    assert run_cli(context, "geocode", transport=transport) == 0
    assert len(transport.bodies) == 1

    assert run_cli(context, "geocode", "--retry-failed", transport=transport) == 0
    assert len(transport.bodies) == 2
    assert proposals(context)[-1]["status"] == "proposed"


def test_incomplete_model_configuration_names_only_the_missing_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    context = ready(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", API_KEY)
    transport = FakeJsonTransport(gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 2
    message = capsys.readouterr().err
    assert "GEMINI_INPUT_USD_PER_MTOK" in message
    assert "GEMINI_OUTPUT_USD_PER_MTOK" in message
    assert API_KEY not in message
    assert transport.bodies == []


def test_without_a_model_key_the_existing_paths_are_unchanged(tmp_path: Path) -> None:
    context = ready(tmp_path)
    assert run_cli(context, "geocode") == 0
    assert results(context)["r1"]["reason"] == "unconfirmed_name"
    assert proposals(context) == []


def test_secrets_and_raw_responses_never_reach_the_artifacts(
    tmp_path: Path, configured: None
) -> None:
    context = ready(tmp_path)
    transport = FakeJsonTransport(gemini_body())
    assert run_cli(context, "geocode", transport=transport) == 0
    stored = "".join(
        path.read_text(encoding="utf-8")
        for path in context.paths.data_root.rglob("*")
        if path.is_file()
    )
    assert API_KEY not in stored
    assert "responseId" not in stored
    assert "usageMetadata" not in stored


def test_lookup_comparison_confirmation_and_marker_run_through_the_existing_cli(
    tmp_path: Path, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_ID", "합성-검색-아이디")
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_SECRET", "합성-검색-비밀값")
    context = prepare(tmp_path)
    # 담당자는 근거만 준비하고 후보는 기존 조회 경로가 채운다.
    evidence = truncated_lookup()
    evidence["candidates"] = []
    save_input(context, evidence)
    designate(context, "r1")
    record_spending(context, "2.50")
    road = "부산 합성로 10"
    places = FakeTransport(naver_body(naver_item(f"<b>{FULL_NAME}</b> 부산점", road)))
    found = digest([INTERPRETATION_VERSION, f"{FULL_NAME} 부산점", road])
    answer = gemini_answer(candidate_source_id=found, restored_merchant=FULL_NAME)
    model = FakeJsonTransport(gemini_body(answer))

    assert run_cli(context, "geocode", transport=model, naver=places) == 0
    assert results(context)["r1"]["reason"] == "unconfirmed_name"
    proposal = proposals(context)[0]
    assert proposal["status"] == "proposed"
    assert proposal["proposed_merchant"] == FULL_NAME
    assert proposal["candidate_source"]["provider"] == "naver"

    # 제안을 읽은 사람이 근거와 범위를 갖춰 확정하면 그때 판정이 바뀐다.
    save_restorations(context, restore_entry())
    classify_records(context)
    assert run_cli(context, "geocode", transport=model, naver=places) == 0
    confirmed = results(context)["r1"]
    assert confirmed["status"] == "success"
    assert confirmed["confirmed_merchant"] == FULL_NAME
    assert (confirmed["latitude"], confirmed["longitude"]) == (35.1, 129.1)

    # 제안 이력이 늘어도 판정·마커의 의존성은 바뀌지 않는다.
    for stage in ("closure", "build"):
        assert run_cli(context, stage, transport=model, naver=places) == 0
    markers = json.loads(
        (context.paths.output_root / "seoul" / "markers.json").read_text(encoding="utf-8")
    )
    assert markers["candidates"][0]["merchant"] == FULL_NAME
    assert markers["candidates"][0]["record_ids"] == ["r1"]
    assert len(model.bodies) == 1
