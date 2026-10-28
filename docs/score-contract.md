# 채점 결과 계약 (schema version 2)

스타일별 rewrite 결과 하나마다 score 결과 하나를 만든다. 각 score는 같은 case·attempt를 유지하며 자기 `style_id`를 갖는다. 첫 attempt에서는 세 스타일 rewrite를 각각 채점하고, 이후 attempt에서는 사용자가 고른 한 스타일 rewrite를 채점한다.

## 항목 점수

- 필수 항목의 최대 점수는 10점, 우대 항목은 5점이다.
- `충족`이면 최대 점수를 받으며, `미충족` 또는 `경험 없음`이면 0점이다.
- 점수는 항목별로만 표시한다. 총점은 제공하지 않는다.
- 수치 근거 유무는 check로 표시하지만 감점하지 않는다. 원문에 없는 숫자·정형 표현·경험이 없는데 문장이 생성된 경우는 항목을 참조하는 `issues`에 한 번만 기록한다.

## score 필드

`schemas/score.json`과 `schemas/score.v0.json`은 같은 version 2 구조를 사용한다. 각 score에는 `schema_version`, `case_id`, 양의 정수 `attempt`, 공통 `attempt_id`, `style_id`, `items`, `issues`, `feedback`, `needs_revision`이 포함된다. 세 스타일 score는 `attempt_id`와 `attempt`를 공유한다.

각 `items[]`에는 `item_id`, 기존 세 상태 중 하나인 `status`, 판정 `reason`, 항목별 `{earned, max}` 점수, 일치/미일치 키워드, 수치 근거 `checks`가 포함된다. `issues[]`는 `item_id`, `code`, 검출 `value`, `reason`으로 구성한다.

## checklist 계약 및 샘플

`samples/checklist.sample.json`과 `.v0.json`은 같은 JSON 내용이며 `schema_version: 2`를 사용한다. 공식 및 v0 checklist schema도 같은 항목 구조를 검사한다. 항목은 `id`, `text`, `keywords`, `type`, `level`을 사용하고 점수 기준은 별도 weight 필드 없이 level에서 결정한다.

`samples/score.sample.json`과 `.v0.json`도 동일한 score 객체다. 샘플 테스트는 두 schema와 샘플이 동일한지, 각 최대 점수가 checklist의 필수/우대 구분에 맞는지, 획득 점수가 상태 규칙과 맞는지 검사한다.

## 입력과 결과 화면

경험 응답이 모두 준비되기 전에는 채점하지 않는다. 빈 경험 입력은 미작성으로 남기며 `경험 없음`은 사용자가 직접 선택한다. 결과 화면은 항목별 원문과 rewrite를 나란히 보여주고 status, score, reason, issue 및 다음 rewrite용 feedback을 표시한다. 같은 입력의 세 스타일은 한 attempt로 묶고, 입력이 바뀐 재작업은 새 attempt로 기록한다. 최대 attempt 횟수는 고정하지 않는다.

앱은 경험 응답을 채점기에 전달할 때 공식 experience 모양을 사용한다. `schema_version`과 `case_id`를 포함하고, 경험 있는 항목만 `{item_id, text}`로 기록하며, 명시적으로 경험 없음을 고른 항목은 생략한다. 이 JSON은 현재 화면에서 다운로드하지 않는다.
