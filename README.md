# career-agent-v0

채용공고와 경험을 바탕으로 이력서 문장을 첨삭하고 코드로 채점하는 팀 프로젝트입니다.

## 현재 실행할 수 있는 화면

채용공고·회사정보·이력서 입력을 한 열로 배치하고, 준비한 입력을 TXT로 내려받을 수 있습니다. 저장소의 샘플 체크리스트를 불러와 요구사항·키워드·유형·필수/우대를 고치고, "확인 완료"를 누르면 `reviewed: true`가 된 JSON을 내려받을 수 있습니다. 체크리스트를 확인하면 항목별 경험을 직접 입력하는 화면이 이어지며, 입력 중 이력서 원문 전체를 참고할 수 있습니다.

공고 파싱과 LLM 첨삭은 아직 연결되지 않았습니다. 표시되는 체크리스트는 입력한 공고를 분석한 결과가 아니라 `samples/checklist.sample.json`입니다. 경험은 항목별 입력 단계에서 사용자가 직접 작성하며, 비워 둔 항목은 경험 없음으로 전달됩니다. 첫 rewrite는 아직 업로드 또는 샘플 미리보기로 연결되어 있습니다. 스타일 선택 후에는 해당 스타일의 attempt 2–4 rewrite를 추가로 올려 채점 이력을 볼 수 있습니다. 입력은 현재 Streamlit 세션에만 유지되며 앱이 파일로 자동 저장하지 않습니다.

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
python3 -m loop.initial_rewrite case-01
```

`data/cases/case-01/checklist.json`과 `experience.json`을 읽고, 결과를 같은 폴더의 `rewrite.json`에 저장합니다. LLM 생성에는 Codex CLI가 필요합니다.

샘플로 실행하려면 다음 명령을 사용합니다. 샘플 입력은 `samples/`에서 읽고 결과는 `samples/rewrite.sample.test.json`에 저장합니다.

```sh
python3 -m loop.initial_rewrite --sample
```

### 피드백 재작성 연결

첫 생성 결과(`rewrite.json`)에서 사용자가 고른 `style_id` 하나를 정한 뒤, 호출하는 쪽에서 `prepare_feedback_input()`으로 피드백 입력을 만듭니다. 이 함수는 선택한 첫 문장·체크리스트·경험 원문을 `feedback_input.json` 모양으로 합칩니다.

```python
import json
from pathlib import Path
from loop.data_contracts import read_json
from loop.feedback_loop import prepare_feedback_input

case_dir = Path("data/cases/case-01")
feedback_input = prepare_feedback_input(
    read_json(case_dir / "rewrite.json"),
    read_json(case_dir / "checklist.json"),
    read_json(case_dir / "experience.json"),
    "achievement",  # 사용자가 고른 style_id
)
feedback_input["user_feedback"] = [{"req-1": "성과를 더 앞에 보여 주세요."}]
(case_dir / "feedback_input.json").write_text(
    json.dumps(feedback_input, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
```

그다음 한 회차 재작성을 실행합니다.

```sh
python3 -m loop.feedback_loop case-01
```

`data/cases/case-01/feedback_input.json`을 읽어 같은 폴더의 `feedback_output.json`에 attempt 2 결과를 저장합니다. 직전 attempt의 문장에는 제출한 의견이 `user_feedback`으로 남고, 새 attempt의 문장은 비어 있는 `user_feedback`으로 시작합니다. 다음 회차는 `feedback_output.json`을 다음 입력 상태로 사용하고, 새 의견을 최상위 `user_feedback`에 넣어 다시 실행합니다. 최대 attempt는 4입니다.

## 확인하기

```sh
.venv/bin/python -m unittest discover -s tests -v
```

입력 원문 보존, 편집·확정 상태, 잘못된 체크리스트 차단, 스타일 화면 흐름, 규칙 채점과 채점 결과 JSON Schema를 검사합니다.

## 데이터 약속과 검토 자료

- [채점 결과 계약](docs/score-contract.md): 10/13 회의 합의에 따른 `schemas/score.json`과 `samples/score.sample.json`. 채점 결과는 이 스키마에 정의된 값만 사용합니다.
- [AI 표현 검토 후보](docs/ai-phrases-review.md): 기존 표현과 추가 후보 10개를 구분했습니다. 후보는 검토 자료이며 채점 목록에 자동 반영하지 않았습니다.
- 체크리스트 확인 화면은 파싱팀 스키마(`schemas/parsing/checklist.json`)로 검사하고, id 중복은 코드로 검사합니다. 항목 ID와 항목 수는 바꾸지 않으며, 기존 필드와 메타데이터는 그대로 둡니다. 파싱이 연결되기 전까지는 샘플을 `reviewed: false` 초안으로 읽어 씁니다.
- 공고 TXT는 `회사정보`가 있을 때만 해당 제목을 포함하고, 공고는 항상 `채용공고` 제목 아래에 둡니다. 파일명은 `jd.txt`입니다.

실제 이력서, 로그인 정보, API 키, 캐시는 커밋하지 않습니다. 팀 간 데이터와 역할 규칙은 [AGENTS.md](AGENTS.md)를 따릅니다.
