"""제공자와 무관한 HTTP 경계. 테스트는 이 자리에 응답만 주입하고 어댑터는 그대로 실행한다."""

import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Protocol

MAX_RESPONSE_BYTES = 1_000_000
REQUEST_TIMEOUT = 10.0
# 조회 조건 이름의 대괄호·콜론은 그대로 두고 공백은 %20으로 보낸다. `+`를 공백으로 읽지 않는
# 제공자가 있어 urlencode의 기본 quote_plus는 쓰지 않는다.
SAFE_CHARACTERS = "[]:"


class Transport(Protocol):
    def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes: ...


class JsonTransport(Protocol):
    """본문을 실어 보내는 경계. 조회용 Transport와 요청 모양이 달라 따로 둔다."""

    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> bytes: ...


class HttpTransport:
    def __init__(self, timeout: float = REQUEST_TIMEOUT) -> None:
        self.timeout = timeout

    def fetch(self, url: str, params: Mapping[str, str], headers: Mapping[str, str]) -> bytes:
        query = urllib.parse.urlencode(
            dict(params), quote_via=urllib.parse.quote, safe=SAFE_CHARACTERS
        )
        request = urllib.request.Request(f"{url}?{query}", headers=dict(headers))
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return bytes(response.read(MAX_RESPONSE_BYTES + 1))

    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> bytes:
        request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return bytes(response.read(MAX_RESPONSE_BYTES + 1))
