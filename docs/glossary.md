# 용어

| 용어 | 뜻 |
| --- | --- |
| `checklist.json` | 파싱팀이 만든 채용 요구사항과 항목 ID 목록이다. |
| `experience.json` | 파싱·입력 단계가 체크리스트 항목별로 정리해 루프에 전달하는 원문 경험이다. |
| `rewrite.json` | 첫 생성에서 세 스타일의 문장 후보를 함께 담는 파일이다. |
| `item_id` | 경험과 첨삭 문장을 체크리스트 항목에 연결하는 ID다. 체크리스트의 `items[].id`를 참조한다. |
| `style` | 스타일을 저장하는 고정 ID다. `achievement`, `keyword`, `concise`를 사용한다. |
| `llm_opinion` | LLM이 원문 사실을 어떻게 문장에 반영했는지 설명하는 값이다. |
| `score.feedback` | 채점기가 미통과 결과에 대해 만든 다음 수정 안내다. 사용자는 다음 재작성 전에 이를 편집할 수 있으며, 통과 결과에서는 빈 문자열이다. |
| `rewrite.sentences[].user_feedback` | 사용자가 해당 체크리스트 항목의 재작성 문장에 덧붙이는 의견이다. 스타일과 attempt별로 유지해 다음 루프 실행에 전달한다. |
