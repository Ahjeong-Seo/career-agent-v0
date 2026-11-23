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
- 피드백이 비어 있는 경험 항목은 LLM에 보내지 않고 직전 문장을 그대로 복사한다.
- 모든 항목의 피드백이 비어 있어도 오류로 막지 않는다. 직전 문장을 복사하고 attempt를 다음 차수로 올린다.
- 화면에는 선택 스타일의 첫 문장과 가장 최근 결과만 표시한다. 두 결과가 같은 attempt이면 문장을 한 번만 표시한다.
- 채점 feedback의 `req-N: 의견` 줄은 checklist에 있는 같은 ID의 항목 피드백으로 옮긴다. 형식이 맞지 않거나 ID가 없는 줄은 항목별 입력으로 보내지 않고 화면에 안내한다. 나머지 유효한 항목 피드백은 계속 전달한다.
- 채점의 통과 여부는 `score.passed`를 따른다. 통과하면 그 차수를 자동으로 최종 결과로 확정하며, 4차까지 미통과이면 4차를 최종 결과로 확정한다.
- 최종 차수는 화면 세션의 `final_result_saved` 값으로 관리해 리포트에 직접 전달한다. 재작성 이력 항목에 `finalized` 표시는 두지 않는다.
- TXT 파일에는 첫 문장을 넣지 않고 최종 문장만 항목별로 저장한다.

## 근거

직전 문장에 대한 요청을 해당 문장과 함께 보존하고, 프롬프트에는 직전 문장만 전달하기로 루프팀과 합의했다. 전체 이력은 결과 파일에서 확인 가능하게 남기되, 최종 결과 화면에는 첫 문장과 마지막 결과만 보여 준다.

## 구현

재작성 핵심은 `loop.retry_rewrite`가 맡는다. `python -m loop.retry_rewrite <feedback_input.json> <feedback_output.json>`은 JSON 파일 실행 경로이며, `python -m loop.feedback_loop <case_id>`는 케이스 폴더와 터미널 입력을 유지하는 연결 경로다. 프롬프트는 `prompts/rewrite_retry_v2.md`이며 버전 상수는 `loop/constants.py`의 `RETRY_PROMPT_VERSION`이다.

## 다음 작업

화면의 채점 feedback을 항목별 `user_feedback`으로 바꾸어 `feedback_input.json`으로 내려받는 연결은 `app/feedback_bridge.py`가 제공한다. 연결할 수 없는 줄은 어느 항목에도 임의로 배정하지 않는다.
