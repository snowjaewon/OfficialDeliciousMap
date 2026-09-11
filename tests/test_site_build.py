import json
import re
from pathlib import Path

import pytest

from deliciousmap.registry import CITIES
from tests.test_geocoding_cli import lookup, prepare, run_cli, save_input


def test_every_city_declares_a_valid_map_bounds() -> None:
    for city in CITIES:
        bounds = city.map_bounds
        assert -90 <= bounds.south < bounds.north <= 90
        assert -180 <= bounds.west < bounds.east <= 180


def test_city_page_contains_its_map_bounds_and_public_map_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NAVER_MAP_CLIENT_ID", "public-test-key")
    monkeypatch.setenv("NAVER_MAP_KEY_PARAM", "ncpKeyId")
    context = prepare(tmp_path)
    save_input(context, lookup())
    for stage in ("geocode", "closure", "build"):
        assert run_cli(context, stage) == 0

    page = (context.paths.output_root / "seoul" / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<script id="site-config" type="application/json">(.*?)</script>', page)
    assert match is not None
    config = json.loads(match.group(1))
    assert config == {
        "city": "seoul",
        "map_bounds": {"east": 129.4, "north": 38.0, "south": 34.8, "west": 126.7},
        "naver_map_client_id": "public-test-key",
        "naver_map_key_param": "ncpKeyId",
        "site_root": "../",
    }
