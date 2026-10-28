# ADR 0001: main 브랜치 계약에 맞춘 첫 루프 실행

## 결정

- 파싱팀이 합의된 위치에 저장한 `checklist.json`과 `experience.json`을 입력으로 사용한다. 루프는 경험을 직접 묻거나 입력 파일을 케이스 폴더에 복사하지 않는다.
- 체크리스트의 `id`와 경험의 `item_id`를 연결 키로 쓴다.
- 첫 생성은 `achievement`, `keyword`, `concise` 세 스타일을 순서대로 만들고, 하나의 `rewrite.json`에 함께 저장한다.
- 문장에는 `item_id`, 원문 `source`, 다듬은 `text`, `llm_opinion`, 사용자 수정 요청 `user_feedback`을 둔다. 최초 수정 요청은 빈 문자열이다.
- 최종 교환 파일 이름은 `checklist.json`, `experience.json`, `rewrite.json`으로 통일한다.

## 실행

`python3 -m loop.initial_rewrite <case_id>`로 실행하면 `data/cases/<case_id>/`의 `checklist.json`과 `experience.json`을 읽어 같은 폴더에 `rewrite.json`을 저장한다. 샘플로 확인하려면 `python3 -m loop.initial_rewrite --sample`을 사용한다. rewrite 데이터 모양은 `samples/rewrite.sample.json` 예시를 따르며 `schema_version: 1`을 포함한다.
