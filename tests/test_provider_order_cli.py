"""제공자를 하나씩 레코드 전부에 돌리는 순서를 공개 CLI로 관찰한다.

앞 제공자가 후보를 낸 레코드는 뒤 제공자에게 다시 묻지 않는다. 뒤 제공자의 조회가 훨씬
느릴 때 도시 한 곳을 도는 시간을 그 제공자가 지배하기 때문이다(2026-09-17 부산 실측:
인허가 중앙값 3.43초, 네이버 0.27초). 후보를 못 얻은 레코드는 그대로 뒤 제공자에게 묻는다.
"""

from pathlib import Path

from tests.fakes import FakeLicenseTransport, FakeTransport, license_body, naver_body, naver_item
from tests.test_geocoding_cli import prepare_many
from tests.test_license_lookup_cli import licensed, run_cli, searched  # noqa: F401
from tests.test_naver_lookup_cli import ROAD_ADDRESS

FOUND = "네이버가 찾은 식당"
UNFOUND = "아무도 찾지 못한 식당"


def asked(transport: FakeLicenseTransport) -> set[str]:
    return {item["cond[BPLC_NM::LIKE]"] for item in transport.requests}


def test_the_second_provider_is_asked_only_where_the_first_found_nothing(
    tmp_path: Path,
    searched: None,  # noqa: F811
    licensed: None,  # noqa: F811
) -> None:
    context = prepare_many(tmp_path, (FOUND, UNFOUND))
    naver = FakeTransport(
        naver_body(naver_item(FOUND, ROAD_ADDRESS)),
        naver_body(),
    )
    licenses = FakeLicenseTransport(license_body())

    assert run_cli(context, "geocode", naver=naver, licenses=licenses) == 0

    # 네이버는 두 레코드를 먼저 끝까지 돈다.
    assert [item["query"] for item in naver.requests] == [FOUND, UNFOUND]
    # 인허가는 네이버가 비운 레코드만 묻는다.
    assert asked(licenses) == {UNFOUND}
