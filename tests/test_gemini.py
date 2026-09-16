"""환경에서 세운 모델 어댑터의 배선을 본다. 모델을 실제로 부르지 않는다."""

from deliciousmap import gemini
from deliciousmap.transport import REQUEST_TIMEOUT, HttpTransport

# 2026-09-16 울산 실측: 상호 40개(classify.BATCH_SIZE) 한 묶음의 응답에 걸린 시간.
MEASURED_BATCH_SECONDS = 10.4


def test_model_requests_wait_longer_than_a_board_fetch(configured: None) -> None:
    """게시판 기본 대기로는 40개 묶음이 매번 끊겨 판별 108회가 통째로 보류됐다(#171).

    상수끼리 견주면 값을 낮춰도 통과하므로 실측의 몇 배인지를 초 단위로 못 박는다.
    """
    models = gemini.models_from_environment()

    assert models is not None
    assert REQUEST_TIMEOUT < MEASURED_BATCH_SECONDS
    # 세 용도가 같은 경계를 쓴다. 판별만 고치고 비교·헤더 매핑을 10초에 두지 않는다.
    for model in (models.comparator, models.header_mapper, models.classifier):
        transport = model.transport
        assert isinstance(transport, HttpTransport)
        # 실측의 다섯 배는 기다린다. 제공자가 느려진 날에도 판별을 통째로 잃지 않는다.
        assert transport.timeout >= 5 * MEASURED_BATCH_SECONDS
