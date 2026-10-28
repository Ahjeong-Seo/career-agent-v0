# 주간 목표 구현 및 계약 정리

## 반영한 결정

- 입력은 채용공고와 선택 회사정보 두 칸이다. 회사정보 안내는 사업내용·인재상으로 제한한다. 이력서 자동 채움은 v1 후보다.
- 경험은 checklist 항목마다 직접 입력하거나 사용자가 `경험 없음`을 선택한다. 미작성 항목이 있으면 채점을 시작하지 않는다.
- 첫 attempt에서는 achievement, keyword, concise 세 스타일의 rewrite를 각각 score로 채점하고 하나의 attempt로 묶는다. 이후 재작업은 선택된 한 스타일의 rewrite만 채점한다.
- 필수 항목은 10점, 우대 항목은 5점이다. 충족이면 만점, 그 외에는 0점이며 총점은 두지 않는다. 수치 근거 유무는 표시하고 점수에는 반영하지 않는다.
- 결과 항목은 상태, 이유, 점수, 키워드와 checks를 가진다. 품질 경고는 항목 참조를 포함한 `issues` 한 곳에만 저장한다.
- 입력이 달라지면 새 attempt를 만들고 이전 결과를 세션 이력에 보존한다. 최대 횟수 정책은 고정하지 않는다.

## 계약 정렬

- `schemas/score.json`과 `schemas/score.v0.json`은 schema version 2의 같은 구조다.
- `samples/score.sample.json`과 `.v0.json`은 같은 항목별 점수 결과다.
- `samples/checklist.sample.json`과 `.v0.json`은 같은 checklist이며 level로 점수 가중치(필수 10, 우대 5)를 정한다.
- 두 checklist schema 역시 같은 구조를 검증한다.
- 점수 정책 변경에 따라 score schema/sample version을 2로 올렸다. 이 schema는 `passed`와 총점을 저장하지 않는다.

## 현재 범위와 제한

파싱과 rewrite 생성을 아직 연결하지 않아 rewrite JSON을 화면에 업로드한다. 첫 attempt에는 세 스타일이 모두 필요하며, 재작업에는 한 스타일만 허용된다. 화면의 attempt 이력은 Streamlit 세션 안에서만 유지된다.

Windows에서 검증할 때:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
