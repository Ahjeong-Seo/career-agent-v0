# career-agent-v0

채용공고와 경험을 바탕으로 이력서 문장을 첨삭하고 코드로 채점하는 팀 프로젝트입니다.

## 현재 실행할 수 있는 화면

채용공고·회사정보·이력서 입력을 한 열로 배치하고, 준비한 입력을 TXT로 내려받을 수 있습니다. 저장소의 가짜 체크리스트를 불러와 요구사항과 키워드를 수정하고, 검증 후 확정한 JSON을 내려받을 수 있습니다.

공고 파싱, 경험 입력, LLM 첨삭, 실제 채점, 결과 화면은 아직 연결되지 않았습니다. 표시되는 체크리스트는 입력한 공고를 분석한 결과가 아니라 `samples/checklist.sample.json`입니다. 입력은 현재 Streamlit 세션에만 유지되며 앱이 파일로 자동 저장하지 않습니다.

## 시작하기

Python 3.11 이상에서 저장소 루트 기준으로 실행합니다.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app/main.py
```

키워드 목록 편집을 위해 Streamlit 1.66 이상을 사용합니다. 이 화면 실행에는 API 키나 LLM 호출이 필요하지 않습니다.

## 터미널에서 루프 실행

```sh
python3 -m loop.initial_rewrite path/to/checklist.json path/to/experience.json path/to/rewrite.json
```

앞 단계에서 정해진 위치에 저장한 `checklist.json`과 `experience.json`을 입력으로 받습니다. 루프는 입력 파일을 만들거나 케이스 폴더로 옮기지 않고, 생성한 세 스타일 결과만 지정한 `rewrite.json` 경로에 저장합니다. LLM 생성에는 Codex CLI가 필요합니다.

## 확인하기

```sh
.venv/bin/python -m unittest discover -s tests -v
```

입력 원문 보존, 편집·확정 상태, 잘못된 체크리스트 차단, Streamlit 화면 흐름과 채점 JSON Schema를 검사합니다.

## 데이터 약속과 검토 자료

- [채점 결과 계약](docs/score-contract.md): 10/13 회의 합의에 따른 `schemas/score.json`과 `samples/score.sample.json`. 실제 채점 로직은 포함하지 않습니다.
- [AI 표현 검토 후보](docs/ai-phrases-review.md): 기존 표현과 추가 후보 10개를 구분했습니다. 후보는 검토 자료이며 채점 목록에 자동 반영하지 않았습니다.
- 체크리스트 편집은 기존 필드와 메타데이터를 보존하며 ID·유형·필수/우대 구분·항목 수는 바꾸지 않습니다. 파싱팀 스키마 병합 후 필수 메타데이터와 연결을 맞춰야 합니다.

실제 이력서, 로그인 정보, API 키, 캐시는 커밋하지 않습니다. 팀 간 데이터와 역할 규칙은 [AGENTS.md](AGENTS.md)를 따릅니다.
