"""이번 제출의 대상 기간. 수집·추출·화면이 같은 기간을 쓴다."""

from datetime import date

START = date(2026, 1, 1)
END = date(2026, 6, 30)
LABEL = "2026년 상반기"


def contains(day: date) -> bool:
    return START <= day <= END
