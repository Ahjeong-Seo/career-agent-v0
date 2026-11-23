"""첫 첨삭 결과와 사용자 피드백으로 한 회차의 재작성 결과를 만든다."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from loop.constants import FEEDBACK_SCHEMA_VERSION, STYLES
from loop.data_contracts import read_json, validate_document
from loop.initial_rewrite import case_paths
from loop.retry_rewrite import create_retry_rewrite, validate_feedback_input as validate_retry_input


ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_INPUT_SCHEMA_PATH = ROOT / "schemas" / "feedback_input.json"
FEEDBACK_OUTPUT_SCHEMA_PATH = ROOT / "schemas" / "feedback_output.json"


def clean_terminal_input(value: str) -> str:
    """터미널에서 읽은 문자열을 받아 줄바꿈을 뺀 문자열로 돌려준다."""
    return value.rstrip("\r\n")


def validate_feedback_input(data: dict[str, Any]) -> None:
    """피드백 입력을 스키마와 파일 간 연결 규칙으로 검사하고 None을 돌려준다."""
    validate_document(Path("feedback_input.json"), data, FEEDBACK_INPUT_SCHEMA_PATH)
    attempt = data["attempt"]
    style_id = data["style_id"]
    style_names = dict(STYLES)
    selected_style = style_id if style_id in style_names else next(
        key for key, name in STYLES if name == style_id
    )

    items = data["requirements"]["items"]
    item_ids: set[str] = set()
    for index, item in enumerate(items):
        if item["id"] in item_ids:
            raise ValueError(f"입력의 requirements.items에 중복된 id가 있습니다: {item['id']}")
        item_ids.add(item["id"])

    sources: dict[str, str] = {}
    for index, experience in enumerate(data["experiences"]):
        item_id = experience["item_id"]
        source = experience["text"]
        if item_id not in item_ids or item_id in sources:
            raise ValueError(f"입력의 experiences.{index}.item_id가 없거나 중복되었거나 checklist에 없습니다.")
        sources[item_id] = source

    feedback_ids: set[str] = set()
    for index, feedback in enumerate(data["user_feedback"]):
        item_id = feedback["item_id"]
        if item_id not in item_ids or item_id in feedback_ids:
            raise ValueError(f"입력의 user_feedback.{index}.item_id가 중복되었거나 checklist에 없습니다.")
        feedback_ids.add(item_id)

    history = data["old_revised_cv"]
    current = data["revised_cv"]
    for field, versions in (("old_revised_cv", history), ("revised_cv", current)):
        for index, version in enumerate(versions):
            location = f"{field}.{index}"
            version_attempt = version["attempt"]
            limit = attempt - 1 if field == "old_revised_cv" else attempt
            if not 1 <= version_attempt <= limit:
                raise ValueError(f"입력의 {location}.attempt가 잘못되었습니다.")
            if field == "revised_cv" and version_attempt != attempt:
                raise ValueError(f"입력의 {location}.attempt가 최상위 attempt와 다릅니다.")
            if version["style"] != selected_style:
                raise ValueError(f"입력의 {location}.style이 최상위 style_id와 다릅니다.")
            seen: set[str] = set()
            for sentence_index, sentence in enumerate(version["sentences"]):
                sentence_location = f"{location}.sentences.{sentence_index}"
                item_id = sentence["item_id"]
                if item_id not in item_ids or item_id in seen:
                    raise ValueError(f"입력의 {sentence_location}.item_id가 잘못되었습니다.")
                seen.add(item_id)
                if (field == "revised_cv" or sentence["source"]) and sentence["source"] != sources.get(item_id, ""):
                    raise ValueError(f"입력의 {sentence_location}.source가 experiences.text와 다릅니다.")


def validate_feedback_output(data: dict[str, Any]) -> None:
    """피드백 재작성 결과를 출력 JSON Schema로 검사하고 None을 돌려준다."""
    validate_document(Path("feedback_output.json"), data, FEEDBACK_OUTPUT_SCHEMA_PATH)


def prepare_feedback_input(
    previous: dict[str, Any], checklist: dict[str, Any], experience: dict[str, Any], style_id: str
) -> dict[str, Any]:
    """직전 첨삭·체크리스트·경험·스타일을 받아 다음 피드백 입력의 기본 객체를 돌려준다."""
    if previous.get("case_id") != checklist.get("case_id") or previous.get("case_id") != experience.get("case_id"):
        raise ValueError("직전 첨삭, checklist, experience의 case_id가 다릅니다.")
    style_names = dict(STYLES)
    selected_style = style_id if style_id in style_names else next(
        (key for key, name in STYLES if name == style_id), None
    )
    if selected_style is None:
        raise ValueError(f"알 수 없는 스타일입니다: {style_id}")

    attempt = previous.get("attempt")
    if attempt == 1:
        if isinstance(previous.get("revised_cv"), list):
            candidates = [
                row for row in previous["revised_cv"]
                if row.get("style_id", row.get("style")) == selected_style
            ]
        elif isinstance(previous.get("sentences"), list):
            previous_style = previous.get("style_id", previous.get("style"))
            candidates = (
                [{"style_id": previous_style, "sentences": previous["sentences"]}]
                if previous_style == selected_style else []
            )
        else:
            candidates = []
        if len(candidates) != 1:
            raise ValueError(f"첫 첨삭 결과에 선택한 스타일이 없습니다: {style_id}")
        selected = candidates[0]
        old_revised_cv: list[dict[str, Any]] = []
    elif isinstance(attempt, int) and 2 <= attempt <= 3:
        previous_style = previous.get("style_id")
        if previous_style is not None and previous_style != selected_style:
            raise ValueError(f"직전 첨삭 스타일({previous_style})이 선택 스타일({selected_style})과 다릅니다.")
        if isinstance(previous.get("revised_cv"), list):
            candidates = previous["revised_cv"]
        elif isinstance(previous.get("sentences"), list):
            candidates = [{"attempt": attempt, "style": selected_style, "sentences": previous["sentences"]}]
        else:
            candidates = []
        if len(candidates) != 1:
            raise ValueError("직전 재작성 결과에는 선택 스타일의 문장 묶음 하나가 있어야 합니다.")
        selected = candidates[0]
        old_revised_cv = deepcopy(previous.get("old_revised_cv", []))
    else:
        raise ValueError("피드백 입력은 직전 attempt 1~3에서만 준비할 수 있습니다.")

    if selected.get("style_id", selected.get("style")) != selected_style:
        raise ValueError(f"직전 결과에 선택한 스타일이 없습니다: {style_id}")

    result = {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "case_id": previous["case_id"],
        "prompt_version": previous["prompt_version"],
        "attempt": attempt,
        "style_id": selected_style,
        "requirements": {
            "job_title": checklist["job_title"],
            "company_values": deepcopy(checklist["company_values"]),
            "items": deepcopy(checklist["items"]),
        },
        "experiences": deepcopy(experience["experiences"]),
        "user_feedback": [
            {"item_id": item["id"], "given": False, "text": None}
            for item in checklist["items"]
        ],
        "score_feedback": [],
        "old_revised_cv": old_revised_cv,
        "revised_cv": [{
            "attempt": attempt,
            "style": selected_style,
            "sentences": [
                {key: sentence[key] for key in ("item_id", "source", "text", "llm_opinion", "user_feedback")}
                for sentence in selected["sentences"]
            ],
        }],
    }
    validate_feedback_input(result)
    return result


def collect_feedback(sentences: list[dict[str, str]]) -> dict[str, str]:
    """현재 문장 목록을 받아 터미널에서 항목별 수정 의견을 읽어 돌려준다."""
    feedback: dict[str, str] = {}
    for sentence in sentences:
        if not sentence["source"]:
            continue
        print(
            f"[{sentence['item_id']}] {sentence['source']}\n-> {sentence['text']}\n"
            "피드백을 입력해 주세요: ",
            end="", file=sys.stderr, flush=True,
        )
        answer = sys.stdin.readline()
        if answer == "":
            raise EOFError("피드백을 입력하기 전에 입력이 종료되었습니다.")
        feedback[sentence["item_id"]] = clean_terminal_input(answer).strip()
    return feedback


def rewrite_with_feedback(
    data: dict[str, Any], feedback: dict[str, str] | None = None
) -> dict[str, Any] | None:
    """현재 첨삭 객체와 선택적 피드백을 받아 다음 회차 결과를, 의견이 없으면 None을 돌려준다."""
    validate_feedback_input(data)
    if data["attempt"] >= 4:
        raise ValueError("피드백 재작성은 최대 attempt 4까지만 가능합니다.")
    if feedback is None:
        new_feedback = {
            entry["item_id"]: entry["text"] or ""
            for entry in data["user_feedback"]
            if entry["given"]
        }
    else:
        new_feedback = feedback
    item_ids = {item["id"] for item in data["requirements"]["items"]}
    if not isinstance(new_feedback, dict) or any(
        item_id not in item_ids or not isinstance(value, str)
        for item_id, value in new_feedback.items()
    ):
        raise ValueError("피드백은 checklist의 item_id를 키로 하는 문자열 객체여야 합니다.")
    if not any(value.strip() for value in new_feedback.values()) and not data["score_feedback"]:
        return None
    retry_input = deepcopy(data)
    retry_input["user_feedback"] = [
        {
            "item_id": item["id"],
            "given": bool(new_feedback.get(item["id"], "").strip()),
            "text": new_feedback[item["id"]] if new_feedback.get(item["id"], "").strip() else None,
        }
        for item in data["requirements"]["items"]
    ]
    return create_retry_rewrite(retry_input)

def main() -> int:
    """case_id 또는 입력 경로를 받아 한 회차를 실행하고 종료 코드를 돌려준다."""
    parser = argparse.ArgumentParser(description="사용자 피드백을 반영해 한 번 재작성합니다.")
    parser.add_argument("case", help="case_id 또는 feedback_input.json 경로")
    parser.add_argument("--output", type=Path, help="출력 경로 재지정 (case_id 실행은 같은 폴더의 feedback_output.json이 기본값)")
    arguments = parser.parse_args()
    try:
        candidate = Path(arguments.case)
        case_id = None
        if candidate.suffix == ".json" or candidate.parent != Path("."):
            input_path = candidate
            output_path = arguments.output
        else:
            case_id = arguments.case
            case_dir = case_paths(case_id).output.parent
            input_path = case_dir / "feedback_input.json"
            output_path = arguments.output or case_dir / "feedback_output.json"
        data = read_json(input_path)
        if case_id is not None and data.get("case_id") != case_id:
            raise ValueError(f"{input_path}의 case_id가 폴더 이름과 다릅니다: {data.get('case_id')}")
        result = rewrite_with_feedback(data)
        if result is None:
            print("피드백이 없어 재작성을 건너뛰었습니다.", file=sys.stderr)
            return 0
        output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output, encoding="utf-8")
            print(f"피드백 결과를 저장했습니다: {output_path}", file=sys.stderr)
        else:
            print(output, end="")
    except (OSError, ValueError, EOFError, RuntimeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
