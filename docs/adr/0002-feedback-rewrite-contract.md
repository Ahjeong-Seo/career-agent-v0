# ADR 0002: 피드백 재작성 입출력과 이력

## 상태

합의 완료

## 결정

- 재작성 입력은 `schemas/feedback_input.json`을 따르고 결과는 `schemas/feedback_output.json`을 따른다.
- 입력의 최상위 `user_feedback`은 이번 재작성에 대한 항목별 의견이다. 경험이 없는 항목의 의견은 무시한다.
- `attempt`는 입력에서 피드백 대상인 직전 차수, 출력에서 이번에 생성한 차수다. 첫 생성은 1차이며 재작성은 2~4차까지 허용한다.
- 입력의 `revised_cv`에는 선택한 스타일의 직전 차수 하나만 둔다. 입력의 `old_revised_cv`에는 그보다 앞선 선택 스타일의 모든 차수를 순서대로 둔다.
- 재작성 프롬프트에는 항목별 원문 경험, 요구사항, 직전 문장, 그 문장에 대한 이번 피드백만 전달한다. 그보다 오래된 문장은 프롬프트에 전달하지 않는다.
- 출력의 `old_revised_cv`에는 기존 이력과 이번 피드백을 기록한 직전 문장을 모두 보존한다. 새 결과는 `revised_cv`에 둔다.
- 직전 문장의 `source`는 `experiences[].text`를 코드가 복사한다. LLM은 `text`와 `llm_opinion`만 생성한다.
- 출력 최상위 `user_feedback`과 새 `revised_cv` 문장의 `user_feedback`은 비워 다음 재작성 입력 자리로 사용한다.
- 경험이 없는 항목에는 피드백을 전달하지 않고 문장도 만들지 않는다.
- 화면에는 선택 스타일의 첫 문장과 가장 최근 결과만 표시한다. 재작성이 없으면 같은 문장을 한 번 표시한다.

## 근거

직전 문장에 대한 요청을 해당 문장과 함께 보존하고, 프롬프트에는 직전 문장만 전달하기로 루프팀과 합의했다. 전체 이력은 결과 파일에서 확인 가능하게 남기되, 최종 결과 화면에는 첫 문장과 마지막 결과만 보여 준다.

## 구현

`python -m loop.retry_rewrite <feedback_input.json> <feedback_output.json>`으로 재작성한다. 프롬프트는 `prompts/rewrite_retry_v1.md`이며 버전 상수는 `loop/constants.py`의 `RETRY_PROMPT_VERSION`이다.
