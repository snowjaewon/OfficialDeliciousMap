status: verified

# classify의 낡음 판정과 꼬리말 규칙 버전

#137 이후 `classify`는 꼬리말을 뗀 이름을 판별한다(`merchants.chosen_name` → `merchants.read`).
그런데 꼬리말 규칙이 바뀌어도 `classify`의 `dependencies`는 달라지지 않았다. 옛 이름으로 판별한
판정이 신선한 산출물로 통과했다. 이번 변경은 꼬리말 규칙에 전용 버전 `merchants.TAIL_VERSION`
(`tail-1`)을 두고, 그 값을 `classify`의 `dependencies`에 `tail_policy`로 싣는다.

## 고치기 전 실측

`develop`(`98c1619`)에서 합성 파이프라인으로 `run`을 한 번 돌렸다(`tests.test_pipeline.context_at` +
`SyntheticAdapters`). 그다음 값을 바꾸고 `ArtifactStore.load`를 불렀다.

| 바꾼 것 | `classify` | `geocode` |
| --- | --- | --- |
| `merchants.POLICY_VERSION` | 낡음 | 낡음 |
| `identity.POLICY_VERSION` | 신선 | 낡음 |
| `merchants._TAIL`만 | 신선 | 신선 |

`merchants.POLICY_VERSION`이 바뀐 경우는 이미 잡힌다. `classify`를 불러올 때 `_validate`가 `parse`를
다시 불러오고, `parse`의 `dependencies`에 그 값이 있기 때문이다. 원래 이 이슈가 적었던 경우가
이것이어서 범위를 꼬리말 규칙으로 좁혔다.

## 뒤 단계가 막히는 방식

`geocode`·`closure`·`build`의 `dependencies`에는 `tail_policy`를 따로 넣지 않았다. 세 단계는
`classify.json`의 해시를 이미 담는다. 그리고 `geocode`를 불러올 때 `_validate`가 `classify`를 다시
불러온다. 그래서 `classify`만 낡음으로 걸려도 세 단계가 함께 `invalid-artifact`로 멈춘다. 이를
`test_changed_tail_rule_cannot_reuse_stale_classification`이 세 단계 각각에 대해 확인한다.

- 고치기 전: `DID NOT RAISE PipelineFailure`로 3건 모두 실패했다.
- 고친 뒤: 3건 모두 통과했다.

`classify` 산출물 자체가 낡음으로 걸리는지는
`test_changed_tail_rule_marks_the_classification_itself_stale`가 `ArtifactStore.load("classify", …)`로
직접 확인한다. 고치기 전에는 `DID NOT RAISE ValueError`로 실패했다. 두 테스트의 "고치기 전" 결과는
`develop`의 `storage.py`로 잠시 되돌려 얻었다.

좌표 판정의 이력 키(`geocode_dependency_key`)는 계속 `identity.POLICY_VERSION`이 맡는다. 좌표 판정도
꼬리말을 뗀 이름을 근거와 대조하기 때문에, 꼬리말 규칙을 바꾸면 두 버전을 함께 올린다. 이력 키에
`tail_policy`를 넣지 않은 이유는 두 가지다. 넣으면 모든 키가 바뀌어 이력이 통째로 다시 쌓인다
(ADR-0005). 그리고 그 판정 의미는 지금도 `identity.POLICY_VERSION`이 지키고 있다.

## 버전을 올리지 않은 규칙 변경

`tests/test_merchants.py`의 `FROZEN`은 꼬리말 규칙이 표기 14개에 낸 답을
`(TAIL_VERSION, identity.POLICY_VERSION)` 쌍에 묶어 적어 둔 표다. 테스트 두 개가 이 표를 본다.

- `test_the_tail_rule_answers_as_its_versions_froze_it`: 현재 버전 쌍의 줄을 규칙의 실제 답과 대조한다.
- `test_a_new_tail_rule_comes_with_both_versions_raised`: 두 가지를 확인한다. 한 좌표 판정 버전은 한
  줄에만 쓰여야 하고, 같은 꼬리말 버전의 줄들은 답이 같아야 한다.

실제로 막는지 확인하려고 `_TAIL`을 바꿔 봤다. 수를 적지 않은 맨끝 `외`를 떼지 않는 규칙으로 바꾸고,
표와 버전을 경우마다 다르게 조정해 두 테스트 함수를 불렀다.

| 경우 | 대조 | 두 버전 |
| --- | --- | --- |
| 규칙만 바꾸고 표·버전은 그대로 | 실패 | 통과 |
| 꼬리말 버전만 올리고 새 줄 추가 | 통과 | 실패 |
| 좌표 판정 버전만 올리고 새 줄 추가 | 통과 | 실패 |
| 두 버전을 모두 올리고 새 줄 추가 | 통과 | 통과 |
| 규칙은 그대로, 다른 사유로 좌표 판정 버전만 올림 | 통과 | 통과 |

이 표는 적어 둔 14개 표기의 답만 얼린다. 표에 없는 표기에만 영향을 주는 규칙 변경(예: `외 3개점`)은
잡지 못한다.

## 재생성

커밋된 `classify.json`은 13개다(`git ls-tree -r --name-only HEAD data | grep 'classify.json$'`). 이 가운데
11개 대상은 `classify`·`geocode`·`closure`·`build`를 다시 냈고, 울산 남구는 `classify`만 다시 냈다.
러너 조건은 다음과 같다.

- `cli.main`을 부르며, `.env`에서 `NAVER_SEARCH_*`·`NAVER_MAP_*`·`DATA_GO_KR_KEY`만 싣고 `GEMINI_*`는 뺐다.
- Naver·식품 인허가·모델 전송은 `BaseException`을 던지는 거부 전송으로 바꿨다. 캐시에 없는 외부
  호출이 생기면 실행이 멈춘다.
- 광주의 `--raw-root`에는 커밋된 `fetch.json`이 담은 다른 작업 공간의 원본 경로를 그대로 줬다. 이
  경로는 비교에만 쓰고 읽지 않는다. 울산은 이 PC의 저장소 밖 원본 폴더를 줬다.

| 대상 | 단계 | 결과 |
| --- | --- | --- |
| 광주 도시, 광주 5개 기관(`buk`·`dong`·`gwangsan`·`nam`·`seo`) | classify → build | 모두 종료 0 |
| 울산 도시, `ulsan-city`·`ulsan-bukgu`·`ulsan-donggu`·`ulsan-junggu` | classify → build | 모두 종료 0 |
| `ulsan-namgu` | classify | 종료 0 |
| `ulsan-namgu` | geocode | 캐시에 없는 Naver 조회에서 거부 전송이 멈췄다 |
| `ulsan-ulju` | classify | `regeneration-required` — `parse.json`의 `schema_version`이 4, 현재는 5다 |

남구 `geocode`는 이번 변경 전부터 `confirmations` 때문에 낡아 있었다. 울주 `parse`도 이번 변경 전부터
옛 스키마였다. 둘 다 #160으로 넘겼다. CI의 `check-data`와 도시 `build`는 기관 산출물을 불러오지
않으므로 이 둘이 CI를 막지는 않는다.

### 전·후 대조

재생성 전은 `develop`(`98c1619`)의 파일이고, 재생성 후는 이 브랜치의 파일이다. 저장소 루트에서
Git Bash로 아래 스크립트를 돌려 셌다. 이 스크립트는 바뀐 파일의 디렉터리마다 단계별 조각을 모두
꺼내 `storage.read_artifact`로 이어 읽고, `payload`와 `classify` 판정을 비교한다.

```bash
git diff --name-only develop -- data | wc -l          # 바뀐 파일 48
git diff --name-only develop -- 'data/**/*.jsonl'     # 출력 없음
PYTHONIOENCODING=utf-8 uv run python - <<'EOF'
import subprocess, tempfile
from pathlib import Path
from deliciousmap.storage import SPLIT_PAYLOAD_FIELD, read_artifact
git = lambda *a: subprocess.run(["git", *a], capture_output=True, check=True)
changed = git("diff", "--name-only", "develop", "--", "data").stdout.decode().split()
compared = differs = decisions = 0
for d in sorted({str(Path(p).parent).replace("\\", "/") for p in changed}):
    for stage in ("classify", "geocode", "closure", "build"):
        names = git("ls-files", f"{d}/{stage}.json", f"{d}/{stage}.0*.json").stdout.decode().split()
        if not set(names) & set(changed):
            continue
        tmp = Path(tempfile.mkdtemp())
        for n in names:
            (tmp / Path(n).name).write_bytes(git("show", f"develop:{n}").stdout)
        field = SPLIT_PAYLOAD_FIELD.get(stage)
        old = read_artifact(tmp / f"{stage}.json", field)["payload"]
        new = read_artifact(Path(d) / f"{stage}.json", field)["payload"]
        compared += 1
        differs += old != new
        if stage == "classify":
            before = {x["record_id"]: x for x in old["decisions"]}
            decisions += sum(before.get(x["record_id"]) != x for x in new["decisions"])
print(compared, differs, decisions)  # 45 0 0
EOF
```

| 대조 | 수 |
| --- | --- |
| 다시 낸 논리 산출물(대상 × 단계) | 45 (11 × 4 + 남구 `classify` 1) |
| 그 가운데 `payload`가 달라진 것 | **0** |
| 판정이 달라진 `classify` 레코드(12개 대상 합) | **0** |
| 바뀐 파일 | 48 (광주 `geocode`가 4조각이라 45보다 3 많다) |
| 바뀐 `.jsonl`(공통 캐시·조회 캐시·이력·예산 장부) | **0** |

`classify.json` 12개는 `dependencies`에 `tail_policy: tail-1`이 더해졌고, 나머지 키 값은 그대로다.
`geocode`·`closure`·`build`는 선행 산출물의 해시만 달라졌다. 광주 `geocode` 판정 결과는 7,082건으로
전후가 같다(`read_artifact(Path("data/gwangju/geocode.json"), "results")["payload"]["results"]`의 길이).

`check-data`의 결과는 다음과 같다.

```text
uv run python -m deliciousmap.ci check-data --data-root data
gwangju
ulsan
```

종료 코드는 0이다.

## LLM 비용

이번 실행의 LLM 호출은 0회, 비용은 USD 0이다. 모델을 설정하지 않았고 모델 전송도 거부했다.
`data/_shared/llm-budget.jsonl`은 755줄로 바뀌지 않았다(`git diff --quiet HEAD -- data/_shared/llm-budget.jsonl`).
공통 예산 누적액은 USD 0.75009150 / 15다(`Budget(Path("data/_shared/llm-budget.jsonl")).committed()`).

## 검사

```text
uv run pytest                 # 810 passed
uv run ruff check .           # All checks passed!
uv run ruff format --check .  # 161 files already formatted
git diff --check              # 출력 없음
```
