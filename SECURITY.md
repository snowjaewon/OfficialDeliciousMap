# 비밀 보호 규칙

이 저장소는 public 이다. 한 번 올라간 키는 히스토리에 남으므로, 새면 지우는 게 아니라 **폐기하고 재발급**한다.

## 키의 종류

| 키 | 성격 | 두는 곳 |
| --- | --- | --- |
| 네이버 검색 API Client ID / Secret (지오코딩, NAVER API HUB) | **비밀** | 개발자 PC의 `.env` 만. CI는 쓰지 않는다(정제 산출물이 커밋되므로). |
| 공공데이터포털 인증키 (인허가 조회, `DATA_GO_KR_KEY`) | **비밀** | 개발자 PC의 `.env` 만. CI는 쓰지 않는다(정제 산출물이 커밋되므로). |
| Gemini API 키 (헤더 매핑·비식당 판별·지정 건 후보 비교) | **비밀** | 개발자 PC의 `.env` 만. CI는 쓰지 않는다. |
| Gemini 적용 단가 (`GEMINI_INPUT_USD_PER_MTOK`·`GEMINI_OUTPUT_USD_PER_MTOK`) | **공개 가능** | 비밀이 아니지만 `.env` 에 둔다. 값이 없으면 LLM 호출을 하지 않는다. |
| 네이버 지도 클라이언트 키 | **공개 가능** | 배포된 사이트에 노출된다. 네이버 클라우드 콘솔의 **웹 서비스 URL(도메인 allowlist)** 로만 보호한다. Actions 에서는 Variables 에 둔다. |

발급은 설재원이 한다. 전달은 대면 시 상대 PC의 `.env` 에 직접 입력한다. 카톡·이메일·이슈·PR 어디에도 평문으로 적지 않는다.

## 협업자가 지킬 것

1. **처음 클론하면** 다음을 한 번 실행한다.
   ```sh
   cp .env.example .env            # 값은 대면 전달로 채운다
   winget install Gitleaks.Gitleaks  # macOS: brew install gitleaks
   git config core.hooksPath .githooks
   ```
   훅이 켜지면 커밋마다 gitleaks 가 스테이지를 검사하고, 비밀이 보이면 커밋을 막는다. gitleaks 가 없으면 커밋 자체를 막는다.
2. **`.env` 와 원본(`data/raw/`)은 절대 `git add` 하지 않는다.** `.gitignore` 가 막지만, `git add -f` 는 쓰지 않는다.
3. **키를 코드·문서·레지스트리에 하드코딩하지 않는다.** 필요하면 환경변수 이름만 적고 값은 `.env` 에서 읽는다. 새 비밀 변수를 추가하면 `.env.example` 에 빈 값으로 등록하고, `.gitleaks.toml` 의 `project-secret-env-assignment` 규칙에 이름을 추가한다.
4. **CI 의 gitleaks 가 실패하면** 그 PR 은 머지하지 않는다. 오탐이면 `.gitleaks.toml` 의 allowlist 에 사유를 적어 추가한다.
5. **정제 산출물에 개인정보가 섞이지 않게 한다.** 레코드에는 기관·부서·상호·금액·집행일·개인정보를 제거한 목적과 레코드 식별자·원본 해시·출처 위치만 남긴다. 참석자 이름·인원 같은 열은 파싱 단계에서 버리고 목적에 포함된 개인정보도 제거한다. 보존 필드는 [뼈대 구현 #25](https://github.com/snowjaewon/OfficialDeliciousMap/issues/25)의 레코드 계약과 일치시킨다. 뼈대의 합성 fixture 검증은 실제 파서의 개인정보 제거 완료를 뜻하지 않는다.

## 새면 어떻게 하나

1. 해당 키를 즉시 콘솔에서 폐기하고 재발급한다(네이버 클라우드 콘솔: Maps·API HUB, 공공데이터포털 마이페이지, Google AI Studio, Cloudflare).
2. 새 키를 대면으로 전달한다.
3. 히스토리 정리는 하지 않는다. 이미 폐기된 키라 의미가 없고, 두 사람의 클론이 어긋난다.

## 보호 장치 목록

- `.gitignore`: `.env`, `data/raw/`, `dist/`, `*.zip`
- `.env.example`: 변수 이름만, 값은 비움
- `.gitleaks.toml`: 기본 규칙 + 프로젝트 비밀 변수 이름 규칙
- `.githooks/pre-commit`: 커밋 전 스테이지 검사
- `.github/workflows/gitleaks.yml`: push·PR 마다 전체 히스토리 검사
- main 브랜치 ruleset: PR 필수, force-push·삭제 금지 (두 사람의 분담과 작업 규칙, #8)
