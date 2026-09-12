"""합성 PDF. 실제 원본처럼 칸마다 괘선 사각형을 그리고 그 안에 글자를 놓는다.

실제 원본은 글자 층과 괘선을 모두 가진 PDF다(광주시청 시의회 게시분 3개 실측). 여기서는
같은 모양만 흉내 내며 원본 내용은 쓰지 않는다. 한글은 Type1 글꼴 코드에 ToUnicode 대응표를
붙여 낸다. 화면에 찍히는 글리프는 다르지만 글자 층은 실제 원본과 같은 방식으로 읽힌다.
"""

from collections.abc import Sequence

# 칸은 쪽(612×792) 안에 들어가야 하고, 글자가 칸을 넘으면 표 인식이 이웃 칸으로 샌다.
CELL_WIDTH = 90
CELL_HEIGHT = 24
LEFT = 30
TOP = 780
FONT_SIZE = 8
LINE_HEIGHT = 10
# 글자 코드는 여는 괄호·닫는 괄호·역슬래시를 피해 읽기 쉬운 범위에서 고른다.
FIRST_CODE = 0x2A
LAST_CODE = 0xFF


def document(*pages: Sequence[Sequence[str]], ruled: bool = True) -> bytes:
    """쪽마다 표 하나. `ruled`가 거짓이면 괘선 없이 글자만 둔다(표로 읽히지 않는 원본)."""
    codes: dict[str, int] = {}
    contents = [_content(rows, codes, ruled) for rows in pages]
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"")  # 자리를 먼저 잡고 아래에서 채운다.
    unicode_map = add(_stream(_to_unicode(codes)))
    objects[font - 1] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding"
        b" /ToUnicode %d 0 R >>" % unicode_map
    )
    pages_object = add(b"")
    kids = []
    for content in contents:
        stream = add(_stream(content))
        kids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792]"
                b" /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (pages_object, font, stream)
            )
        )
    objects[pages_object - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % kid for kid in kids),
        len(kids),
    )
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_object)
    return _assemble(objects, catalog)


def _content(rows: Sequence[Sequence[str]], codes: dict[str, int], ruled: bool) -> bytes:
    """칸 하나에 줄바꿈이 있으면 실제 원본처럼 칸 안에서 줄을 나눠 놓는다."""
    out = [b"0.6 w"]
    for r, cells in enumerate(rows):
        for c, value in enumerate(cells):
            x = LEFT + c * CELL_WIDTH
            y = TOP - (r + 1) * CELL_HEIGHT
            if ruled:
                out.append(b"%d %d %d %d re S" % (x, y, CELL_WIDTH, CELL_HEIGHT))
            written = [line for line in value.split("\n") if line]
            top = y + CELL_HEIGHT - FONT_SIZE - 2
            for index, line in enumerate(written):
                out.append(
                    b"BT /F1 %d Tf 1 0 0 1 %d %d Tm (%s) Tj ET"
                    % (FONT_SIZE, x + 3, top - index * LINE_HEIGHT, _encode(line, codes))
                )
    return b"\n".join(out)


def _encode(value: str, codes: dict[str, int]) -> bytes:
    out = bytearray()
    for character in value:
        if character not in codes:
            code = FIRST_CODE + len(codes)
            if code > LAST_CODE:
                raise ValueError("synthetic PDF ran out of glyph codes")
            codes[character] = code
        out.append(codes[character])
    return bytes(out).replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _to_unicode(codes: dict[str, int]) -> bytes:
    """코드 → 유니코드 대응표. 읽는 쪽은 이 표로 글자를 되살린다."""
    pairs = b"\n".join(
        b"<%02X> <%s>" % (code, character.encode("utf-16-be").hex().upper().encode("ascii"))
        for character, code in sorted(codes.items(), key=lambda item: item[1])
    )
    return (
        b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        b"/CMapName /Synthetic def\n/CMapType 2 def\n"
        b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
        b"%d beginbfchar\n%s\nendbfchar\nendcmap\n"
        b"CMapName currentdict /CMap defineresource pop\nend\nend" % (len(codes), pairs)
    )


def _stream(body: bytes) -> bytes:
    return b"<< /Length %d >>\nstream\n%s\nendstream" % (len(body), body)


def _assemble(objects: list[bytes], catalog: int) -> bytes:
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        start,
    )
    return bytes(out)
