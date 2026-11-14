# 용어

| 용어 | 뜻 |
| --- | --- |
| `checklist.json` | 파싱팀이 만든 채용 요구사항과 항목 ID 목록이다. |
| `experience.json` | 파싱·입력 단계가 체크리스트 항목별로 정리해 루프에 전달하는 원문 경험이다. |
| `rewrite.json` | 첫 생성에서 세 스타일의 문장 후보를 함께 담는 파일이다. 재작성 왕복은 `feedback_input.json`과 `feedback_output.json`을 쓴다. |
| `item_id` | 경험과 첨삭 문장을 체크리스트 항목에 연결하는 ID다. 체크리스트의 `items[].id`를 참조한다. |
| `style` | 스타일을 저장하는 고정 ID다. `achievement`, `keyword`, `concise`를 사용한다. |
| `llm_opinion` | LLM이 원문 사실을 어떻게 문장에 반영했는지 설명하는 값이다. |
| `user_feedback` | 재작성 요청 최상위 칸에 이번 피드백을 담고, 결과에서는 피드백 대상이 된 직전 문장 안에 기록하는 수정 요청이다. 새 문장의 `user_feedback`은 빈 문자열로 둔다. |
| `old_revised_cv` | 선택 스타일에서 완료된 모든 과거 차수의 문장과 차수별 피드백을 순서대로 보존하는 배열이다. |
| `attempt` (피드백 입력) | 사용자가 피드백을 단 직전 차수다. 출력 결과의 `attempt`는 새로 생성한 차수다. |
