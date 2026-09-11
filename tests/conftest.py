import socket

import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture(autouse=True)
def block_real_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """개발자 PC의 실제 키가 테스트에 새어 들어가지 않게 한다."""
    for name in (
        "NAVER_SEARCH_CLIENT_ID",
        "NAVER_SEARCH_CLIENT_SECRET",
        "NAVER_MAP_CLIENT_ID",
        "NAVER_MAP_KEY_PARAM",
        "DATA_GO_KR_KEY",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GEMINI_INPUT_USD_PER_MTOK",
        "GEMINI_OUTPUT_USD_PER_MTOK",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """개발자 PC의 .env 처럼 모델 키와 확인한 단가가 준비된 상태. 값은 합성이다."""
    monkeypatch.setenv("GEMINI_API_KEY", "합성-제미나이-키")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.6-flash")
    monkeypatch.setenv("GEMINI_INPUT_USD_PER_MTOK", "1.50")
    monkeypatch.setenv("GEMINI_OUTPUT_USD_PER_MTOK", "7.50")


@pytest.fixture(autouse=True)
def public_map_key(monkeypatch: pytest.MonkeyPatch, block_real_keys: None) -> None:
    """지도 SDK는 공개 키를 요구한다. 실제 키가 아닌 합성 값으로 build를 실행한다."""
    monkeypatch.setenv("NAVER_MAP_CLIENT_ID", "synthetic-map-key")
