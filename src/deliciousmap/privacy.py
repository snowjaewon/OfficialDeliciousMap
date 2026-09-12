"""목적·상호에 섞인 개인정보 제거. 레코드 보존 필드 밖의 값은 파싱 단계에서 버린다(SECURITY.md).

원본에서 본 모양만 규칙으로 둔다. 경조사 지출은 받은 사람의 이름·직급이 괄호나 상호 칸에 적힌다.
이름을 지운 뒤에도 남는 개인정보가 있는지는 도시마다 목적 목록을 사람이 다시 본다.
"""

import re

# 상호 칸에 적힌 사람 이름을 대신하는 표기. 원본 상호를 추측한 값이 아니라 가린 표시다.
REDACTED = "개인(성명 비공개)"
CONTACTS = (
    # 주민등록번호, 전화번호, 이메일
    re.compile(r"\d{6}\s*-\s*[1-4]\d{6}"),
    re.compile(r"(?<!\d)0\d{1,2}[-. )]\d{3,4}[-. ]\d{4}(?!\d)"),
    re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"),
)
# 받은 사람이 드러나는 개인 경조사 지출. 낱말 첫머리에서만 찾는다(`정부의`·`환경조성`은 아니다).
PERSONAL_EVENT = re.compile(
    r"(?:(?<![가-힣])|(?<=직원|경사|애사|소속))"
    r"(축의|부의|조의|축부의|경조사|애경사|별세|빙모|빙부|모친상|부친상|장인상|장모상|장례|근조|순직)"
    r"|故"
)
# 일부를 가린 이름: 김ㅇㅇ, 한*지, 허 * *, 박○수.
MASKED = re.compile(r"[가-힣](\s*[*＊○◯ㅇ]){1,2}(?:\s*[가-힣](?![가-힣]))?")
PERSON = re.compile(r"[가-힣]{2,4}")
# 경조사 행의 상호 칸에 흔한 일반 명칭. 사람 이름이 아니다.
GENERIC_PAYEES = frozenset(
    {"직원", "소속직원", "개인", "축의금", "부의금", "조의금", "경조사", "화환", "집무실"}
)


def scrub(purpose: str) -> str:
    for pattern in CONTACTS:
        purpose = pattern.sub(" ", purpose)
    if PERSONAL_EVENT.search(purpose):
        # 괄호 안이 받은 사람의 소속·직급·이름이다.
        purpose = re.sub(r"\([^)]*\)", " ", purpose)
    purpose = MASKED.sub(" ", purpose)
    return " ".join(purpose.split())


def scrub_merchant(merchant: str, purpose: str) -> str:
    """경조사 지출의 받는 사람이나 가린 이름은 상호로 남기지 않는다."""
    compact = "".join(merchant.split())
    if MASKED.fullmatch(merchant.strip()) or MASKED.fullmatch(compact):
        return REDACTED
    if (
        PERSONAL_EVENT.search(purpose)
        and PERSON.fullmatch(compact)
        and compact not in GENERIC_PAYEES
    ):
        return REDACTED
    return merchant
