"""앱 아이콘 PNG를 만든다. 결과는 `src/deliciousmap/site_assets/`에 커밋한다.

지도 마커와 같은 모양(세 모서리가 둥근 사각형을 45도 돌린 핀)을 짙은 녹색 바탕에 그린다.
표준 라이브러리만 쓰고, 부호 거리장에서 화소 덮임을 계산해 가장자리를 부드럽게 한다.
같은 코드는 언제나 같은 바이트를 낸다.

양쪽 공통: uv run python scripts/make_icons.py
"""

import math
import struct
import zlib
from pathlib import Path
from typing import Literal

ASSETS = Path(__file__).resolve().parent.parent / "src" / "deliciousmap" / "site_assets"
BACKGROUND = (0x17, 0x3F, 0x35)
PIN = (0xB2, 0x4D, 0x2D)
CREAM = (0xFF, 0xFD, 0xF8)
# 캔버스 한 변에 대한 비율. 핀은 maskable 안전 영역(지름 80% 원) 안에 들어간다.
PIN_HALF = 0.25
PIN_OUTLINE = 0.034
PIN_TIP_RADIUS = 0.02
DOT_RADIUS = 0.09
CORNER_RADIUS = 0.22
# rounded는 모서리를 투명하게 비우고(데스크톱·일반 아이콘), full은 캔버스를 채운다(maskable·iPhone).
type Background = Literal["rounded", "full"]
ICONS: tuple[tuple[str, int, Background], ...] = (
    ("icon-192.png", 192, "rounded"),
    ("icon-512.png", 512, "rounded"),
    ("icon-maskable-512.png", 512, "full"),
    ("apple-touch-icon.png", 180, "full"),
)


def rounded_box_distance(x: float, y: float, half: float, radius: float) -> float:
    """중심이 원점인 둥근 정사각형까지의 부호 거리. 안쪽이 음수다."""
    qx = abs(x) - half + radius
    qy = abs(y) - half + radius
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return min(max(qx, qy), 0.0) + outside - radius


def pin_distance(x: float, y: float, half: float, tip: float) -> float:
    """핀까지의 부호 거리(y는 아래로). 핀은 세 모서리 반지름이 half이고 아래 꼭짓점만 tip인
    사각형을 45도 돌린 모양이다."""
    u = (x + y) / math.sqrt(2)
    v = (y - x) / math.sqrt(2)
    radius = tip if u > 0 and v > 0 else half
    return rounded_box_distance(u, v, half, radius)


def coverage(distance: float) -> float:
    return min(max(0.5 - distance, 0.0), 1.0)


def blend(under: tuple[float, ...], color: tuple[int, int, int], alpha: float) -> tuple[float, ...]:
    """straight alpha의 over 합성. under는 (r, g, b, a)이고 색은 0–255, a는 0–1이다."""
    r, g, b, a = under
    out = alpha + a * (1 - alpha)
    if out == 0:
        return (0.0, 0.0, 0.0, 0.0)
    mix = [(c * alpha + u * a * (1 - alpha)) / out for c, u in zip(color, (r, g, b), strict=True)]
    return (*mix, out)


def render(size: int, background: Background) -> list[list[tuple[float, ...]]]:
    half = PIN_HALF * size
    # 핀의 위아래 끝을 캔버스 가운데에 맞춘다. 머리 위 끝은 -half, 꼭짓점은 +half*sqrt(2)다.
    center_y = size / 2 - half * (math.sqrt(2) - 1) / 2
    rows = []
    for row in range(size):
        pixels = []
        for column in range(size):
            x = column + 0.5 - size / 2
            y = row + 0.5
            if background == "full":
                pixel: tuple[float, ...] = (*BACKGROUND, 1.0)
            else:
                edge = rounded_box_distance(x, y - size / 2, size / 2, CORNER_RADIUS * size)
                pixel = blend((0.0, 0.0, 0.0, 0.0), BACKGROUND, coverage(edge))
            shape = pin_distance(x, y - center_y, half, PIN_TIP_RADIUS * size)
            pixel = blend(pixel, CREAM, coverage(shape))
            pixel = blend(pixel, PIN, coverage(shape + PIN_OUTLINE * size))
            dot = math.hypot(x, y - center_y) - DOT_RADIUS * size
            pixel = blend(pixel, CREAM, coverage(dot))
            pixels.append(pixel)
        rows.append(pixels)
    return rows


def png(rows: list[list[tuple[float, ...]]], alpha: bool) -> bytes:
    channels = 4 if alpha else 3
    raw = bytearray()
    for pixels in rows:
        raw.append(0)
        for red, green, blue, opacity in pixels:
            raw.extend((round(red), round(green), round(blue), round(opacity * 255))[:channels])

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    size = len(rows)
    header = struct.pack(">IIBBBBB", size, size, 8, 6 if alpha else 2, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", header),
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            chunk(b"IEND", b""),
        )
    )


def main() -> None:
    for name, size, background in ICONS:
        path = ASSETS / name
        path.write_bytes(png(render(size, background), alpha=background == "rounded"))
        print(f"{path.relative_to(ASSETS.parent.parent.parent)} {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
