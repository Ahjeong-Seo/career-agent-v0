"""피드백 입력 파일에서 선택 스타일의 다음 재작성 결과를 만든다."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from loop.call_llm import call_llm
from loop.constants import RETRY_PROMPT_VERSION, STYLES
from loop.data_contracts import read_json, validate_document
from loop.initial_rewrite import REWRITE_LLM_SCHEMA_PATH, validate_llm_sentences


ROOT = Path(__file__).resolve().parents[1]
INPUT_SCHEMA_PATH = ROOT / "schemas" / "feedback_input.json"
OUTPUT_SCHEMA_PATH = ROOT / "schemas" / "feedback_output.json"
PROMPT_PATH = ROOT / "prompts" / f"{RETRY_PROMPT_VERSION}.md"
RETRY_STYLES = {style_id for style_id, _ in STYLES}


def validate_feedback_input(
    payload: dict[str, Any], source_path: Path = Path("feedback_input.json")
) -> None:
    """재작성 입력 객체를 받아 JSON Schema와 파일 간 연결 조건을 검사한다."""
    validate_document(source_path, payload, INPUT_SCHEMA_PATH)
    source_name = str(source_path)
    if payload["style_id"] not in RETRY_STYLES:
        raise ValueError(f"{source_name}의 style_id가 허용된 스타일이 아닙니다.")
    if payload["attempt"] >= 4:
        raise ValueError("최대 재작성 차수는 4차입니다.")

    item_ids = [item["id"] for item in payload["requirements"]["items"]]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError(f"{source_name}의 requirements.items에 중복 id가 있습니다.")
    experience_by_id: dict[str, str] = {}
    for entry in payload["experiences"]:
        item_id = entry["item_id"]
        if item_id not in item_ids:
            raise ValueError(f"{source_name} experiences에 requirements에 없는 item_id가 있습니다: {item_id}")
        if item_id in experience_by_id:
            raise ValueError(f"{source_name} experiences에 중복 item_id가 있습니다: {item_id}")
        experience_by_id[item_id] = entry["text"]

    current = payload["revised_cv"]
    if len(current) != 1:
        raise ValueError(f"{source_name}의 revised_cv에는 직전 차수 스타일 하나만 있어야 합니다.")
    previous = current[0]
    if previous["attempt"] != payload["attempt"]:
        raise ValueError(f"{source_name}의 attempt와 revised_cv.attempt가 다릅니다.")
    if previous["style"] != payload["style_id"]:
        raise ValueError(f"{source_name}의 style_id와 revised_cv.style이 다릅니다.")

    history_attempts = [revision["attempt"] for revision in payload["old_revised_cv"]]
    if history_attempts != list(range(1, payload["attempt"])):
        raise ValueError(f"{source_name} old_revised_cv에는 1차부터 직전 이전 차수까지 순서대로 있어야 합니다.")
    if any(revision["style"] != payload["style_id"] for revision in payload["old_revised_cv"]):
        raise ValueError(f"{source_name} old_revised_cv에는 선택한 스타일의 이력만 넣어야 합니다.")

    requirement_ids = set(item_ids)
    feedback_ids = {item_id for group in payload["user_feedback"] for item_id in group}
    unknown_feedback_ids = sorted(feedback_ids - requirement_ids)
    if unknown_feedback_ids:
        raise ValueError(f"{source_name} user_feedback에 checklist에 없는 item_id가 있습니다: {', '.join(unknown_feedback_ids)}")

    for revision in payload["old_revised_cv"]:
        old_sentence_ids: list[str] = []
        for sentence in revision["sentences"]:
            item_id = sentence["item_id"]
            if item_id not in experience_by_id:
                raise ValueError(f"경험이 없는 항목은 과거 문장에 포함할 수 없습니다: {item_id}")
            if sentence["source"] != experience_by_id[item_id]:
                raise ValueError(f"{source_name} old_revised_cv의 source가 experiences.text와 다릅니다: {item_id}")
            old_sentence_ids.append(item_id)
        if len(old_sentence_ids) != len(set(old_sentence_ids)):
            raise ValueError(f"{source_name} old_revised_cv에 중복 item_id가 있습니다.")
        if set(old_sentence_ids) != set(experience_by_id):
            raise ValueError(f"{source_name} old_revised_cv에는 경험이 있는 모든 항목의 문장이 있어야 합니다.")

    sentence_ids: list[str] = []
    for sentence in previous["sentences"]:
        item_id = sentence["item_id"]
        if item_id not in experience_by_id:
            raise ValueError(f"경험이 없는 항목은 직전 문장에 포함할 수 없습니다: {item_id}")
        if sentence["source"] != experience_by_id[item_id]:
            raise ValueError(f"{source_name} revised_cv의 source가 experiences.text와 다릅니다: {item_id}")
        sentence_ids.append(item_id)
    if len(sentence_ids) != len(set(sentence_ids)):
        raise ValueError(f"{source_name} revised_cv.sentences에 중복 item_id가 있습니다.")
    if set(sentence_ids) != set(experience_by_id):
        missing = sorted(set(experience_by_id) - set(sentence_ids))
        raise ValueError(f"{source_name} revised_cv에 경험 항목의 문장이 빠졌습니다: {', '.join(missing)}")


def _feedback_by_item(payload: dict[str, Any]) -> dict[str, str]:
    """항목별 피드백 배열을 받아 item_id별 문자열 사전을 돌려준다."""
    feedback: dict[str, str] = {}
    for group in payload["user_feedback"]:
        feedback.update(group)
    experience_ids = {entry["item_id"] for entry in payload["experiences"]}
    return {item_id: text for item_id, text in feedback.items() if item_id in experience_ids}


def _retry_entries(payload: dict[str, Any], feedback: dict[str, str]) -> list[dict[str, Any]]:
    """재작성 입력과 피드백을 받아 요구사항 순서의 직전 문장 항목을 돌려준다."""
    previous_by_id = {
        sentence["item_id"]: sentence
        for sentence in payload["revised_cv"][0]["sentences"]
    }
    items_by_id = {item["id"]: item for item in payload["requirements"]["items"]}
    experience_by_id = {entry["item_id"]: entry["text"] for entry in payload["experiences"]}
    return [
        {
            "item_id": item_id,
            "requirement": items_by_id[item_id]["text"],
            "keywords": items_by_id[item_id]["keywords"],
            "type": items_by_id[item_id]["type"],
            "level": items_by_id[item_id]["level"],
            "source": experience_by_id[item_id],
            "previous_text": previous_by_id[item_id]["text"],
            "user_feedback": feedback.get(item_id, ""),
        }
        for item_id in (item["id"] for item in payload["requirements"]["items"])
        if item_id in experience_by_id
    ]


def _retry_prompt(payload: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    """선택 스타일과 직전 문장 항목을 받아 LLM 프롬프트를 돌려준다."""
    instructions = PROMPT_PATH.read_text(encoding="utf-8")
    style_name = dict(STYLES)[payload["style_id"]]
    return (
        f"프롬프트 버전: {RETRY_PROMPT_VERSION}\n"
        f"작성 스타일: {style_name} ({payload['style_id']})\n"
        f"직전 차수: {payload['attempt']}\n"
        f"{instructions}\n"
        f"입력 데이터: {json.dumps(entries, ensure_ascii=False)}"
    )


def create_retry_rewrite(
    payload: dict[str, Any],
    *,
    input_path: Path = Path("feedback_input.json"),
    output_path: Path = Path("feedback_output.json"),
) -> dict[str, Any]:
    """피드백 입력을 받아 직전 문장 기반의 다음 차수 결과 객체를 돌려준다."""
    validate_feedback_input(payload, input_path)

    feedback = _feedback_by_item(payload)
    entries = _retry_entries(payload, feedback)
    previous_revisions = copy.deepcopy(payload["old_revised_cv"])
    previous_revision = copy.deepcopy(payload["revised_cv"][0])
    for sentence in previous_revision["sentences"]:
        sentence["user_feedback"] = feedback.get(sentence["item_id"], "")
    previous_revisions.append(previous_revision)

    answer = (
        call_llm(_retry_prompt(payload, entries), read_json(REWRITE_LLM_SCHEMA_PATH))
        if payload["experiences"]
        else {"sentences": []}
    )
    current_sentences = validate_llm_sentences(answer, entries)
    all_requirement_ids = [item["id"] for item in payload["requirements"]["items"]]
    cleared_feedback = [{item_id: "" for item_id in all_requirement_ids}]
    result = {
        "schema_version": 1,
        "case_id": payload["case_id"],
        "prompt_version": RETRY_PROMPT_VERSION,
        "attempt": payload["attempt"] + 1,
        "style_id": payload["style_id"],
        "requirements": copy.deepcopy(payload["requirements"]),
        "experiences": copy.deepcopy(payload["experiences"]),
        "user_feedback": cleared_feedback,
        "old_revised_cv": previous_revisions,
        "revised_cv": [{
            "attempt": payload["attempt"] + 1,
            "style": payload["style_id"],
            "sentences": current_sentences,
        }],
    }
    validate_document(output_path, result, OUTPUT_SCHEMA_PATH)
    return result


def run_files(input_path: Path, output_path: Path) -> Path:
    """입력·출력 경로를 받아 재작성 결과를 생성하고 저장 경로를 돌려준다."""
    payload = read_json(input_path)
    result = create_retry_rewrite(payload, input_path=input_path, output_path=output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    """입력·출력 JSON 경로를 받아 재작성 실행 결과 코드를 돌려준다."""
    parser = argparse.ArgumentParser(description="피드백을 반영해 선택한 스타일을 다시 씁니다.")
    parser.add_argument("input", type=Path, help="feedback_input.json 경로")
    parser.add_argument("output", type=Path, help="feedback_output.json 경로")
    arguments = parser.parse_args()
    try:
        output = run_files(arguments.input, arguments.output)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(f"재작성 결과를 저장했습니다: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
