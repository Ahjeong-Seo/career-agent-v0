"""첫 첨삭 결과와 사용자 피드백으로 한 회차의 재작성 결과를 만든다."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.loop.user_input import clean_terminal_input
from loop.yjh_call_llm import call_llm
from loop.yjh_constants import STYLES
from loop.yjh_data_contracts import read_json
from loop.yjh_initial_rewrite import case_paths


ROOT = Path(__file__).resolve().parents[1]
PROMPT_VERSION = "loop/rewrite_cv_v2"
PROMPT_PATH = ROOT / "prompts" / f"{PROMPT_VERSION}.md"
LLM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sentences"],
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item_id", "text", "llm_opinion"],
                "properties": {
                    "item_id": {"type": "string", "minLength": 1},
                    "text": {"type": "string"},
                    "llm_opinion": {"type": "string"},
                },
            },
        }
    },
}


def validate_feedback_input(data: dict[str, Any]) -> None:
    """rewrite_cv 모양의 입력 객체를 받아 필드와 연결 관계를 확인하고 None을 돌려준다."""
    required = (
        "case_id", "prompt_version", "attempt", "style_id", "requirements",
        "experiences", "user_feedback", "old_revised_cv", "revised_cv",
    )
    for field in required:
        if field not in data:
            raise ValueError(f"입력의 {field} 칸이 없습니다.")
    if not isinstance(data["case_id"], str) or not data["case_id"]:
        raise ValueError("입력의 case_id는 빈 문자열이 아니어야 합니다.")
    if not isinstance(data["prompt_version"], str) or not data["prompt_version"]:
        raise ValueError("입력의 prompt_version은 빈 문자열이 아니어야 합니다.")
    attempt = data["attempt"]
    if type(attempt) is not int or not 1 <= attempt <= 4:
        raise ValueError("입력의 attempt는 1부터 4까지의 정수여야 합니다.")
    style_id = data["style_id"]
    style_names = dict(STYLES)
    allowed_styles = set(style_names) | set(style_names.values())
    if not isinstance(style_id, str) or style_id not in allowed_styles:
        raise ValueError("입력의 style_id가 허용된 스타일이 아닙니다.")
    selected_style = style_id if style_id in style_names else next(
        key for key, name in STYLES if name == style_id
    )

    requirements = data["requirements"]
    if not isinstance(requirements, dict):
        raise ValueError("입력의 requirements는 객체여야 합니다.")
    for field in ("job_title", "company_values", "items"):
        if field not in requirements:
            raise ValueError(f"입력의 requirements.{field} 칸이 없습니다.")
    if not isinstance(requirements["job_title"], str):
        raise ValueError("입력의 requirements.job_title은 문자열이어야 합니다.")
    if not isinstance(requirements["company_values"], list):
        raise ValueError("입력의 requirements.company_values는 목록이어야 합니다.")
    items = requirements["items"]
    if not isinstance(items, list):
        raise ValueError("입력의 requirements.items는 목록이어야 합니다.")
    item_ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError(f"입력의 requirements.items.{index}.id가 잘못되었습니다.")
        if item["id"] in item_ids:
            raise ValueError(f"입력의 requirements.items에 중복된 id가 있습니다: {item['id']}")
        item_ids.add(item["id"])

    experiences = data["experiences"]
    if not isinstance(experiences, list):
        raise ValueError("입력의 experiences는 목록이어야 합니다.")
    sources: dict[str, str] = {}
    for index, experience in enumerate(experiences):
        if not isinstance(experience, dict):
            raise ValueError(f"입력의 experiences.{index}는 객체여야 합니다.")
        item_id = experience.get("item_id")
        source = experience.get("text")
        if not isinstance(item_id, str) or item_id not in item_ids or item_id in sources:
            raise ValueError(f"입력의 experiences.{index}.item_id가 없거나 중복되었거나 checklist에 없습니다.")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"입력의 experiences.{index}.text는 빈 문자열이 아니어야 합니다.")
        sources[item_id] = source

    if not isinstance(data["user_feedback"], list):
        raise ValueError("입력의 user_feedback은 목록이어야 합니다.")
    for index, feedback in enumerate(data["user_feedback"]):
        if not isinstance(feedback, dict) or any(
            item_id not in item_ids or not isinstance(value, str)
            for item_id, value in feedback.items()
        ):
            raise ValueError(f"입력의 user_feedback.{index}은 항목별 문자열 객체여야 합니다.")

    history = data["old_revised_cv"]
    current = data["revised_cv"]
    if not isinstance(history, list) or not isinstance(current, list) or len(current) != 1:
        raise ValueError("입력의 old_revised_cv는 목록, revised_cv는 한 건의 목록이어야 합니다.")
    for field, versions in (("old_revised_cv", history), ("revised_cv", current)):
        for index, version in enumerate(versions):
            location = f"{field}.{index}"
            if not isinstance(version, dict):
                raise ValueError(f"입력의 {location}은 객체여야 합니다.")
            version_attempt = version.get("attempt")
            limit = attempt - 1 if field == "old_revised_cv" else attempt
            if type(version_attempt) is not int or not 1 <= version_attempt <= limit:
                raise ValueError(f"입력의 {location}.attempt가 잘못되었습니다.")
            if field == "revised_cv" and version_attempt != attempt:
                raise ValueError(f"입력의 {location}.attempt가 최상위 attempt와 다릅니다.")
            if version.get("style") != selected_style:
                raise ValueError(f"입력의 {location}.style이 최상위 style_id와 다릅니다.")
            sentences = version.get("sentences")
            if not isinstance(sentences, list):
                raise ValueError(f"입력의 {location}.sentences는 목록이어야 합니다.")
            seen: set[str] = set()
            for sentence_index, sentence in enumerate(sentences):
                sentence_location = f"{location}.sentences.{sentence_index}"
                if not isinstance(sentence, dict):
                    raise ValueError(f"입력의 {sentence_location}은 객체여야 합니다.")
                item_id = sentence.get("item_id")
                if not isinstance(item_id, str) or item_id not in item_ids or item_id in seen:
                    raise ValueError(f"입력의 {sentence_location}.item_id가 잘못되었습니다.")
                seen.add(item_id)
                for key in ("source", "text", "llm_opinion", "user_feedback"):
                    if not isinstance(sentence.get(key), str):
                        raise ValueError(f"입력의 {sentence_location}.{key}는 문자열이어야 합니다.")
                if (field == "revised_cv" or sentence["source"]) and sentence["source"] != sources.get(item_id, ""):
                    raise ValueError(f"입력의 {sentence_location}.source가 experiences.text와 다릅니다.")


def prepare_feedback_input(
    initial: dict[str, Any], checklist: dict[str, Any], experience: dict[str, Any], style_id: str
) -> dict[str, Any]:
    """첫 첨삭·체크리스트·경험·선택 스타일을 받아 feedback_loop 입력 객체를 돌려준다."""
    if initial.get("case_id") != checklist.get("case_id") or initial.get("case_id") != experience.get("case_id"):
        raise ValueError("첫 첨삭, checklist, experience의 case_id가 다릅니다.")
    if initial.get("attempt") != 1:
        raise ValueError("첫 첨삭 결과의 attempt는 1이어야 합니다.")
    style_names = dict(STYLES)
    selected_style = style_id if style_id in style_names else next(
        (key for key, name in STYLES if name == style_id), None
    )
    selected = [row for row in initial.get("revised_cv", []) if row.get("style") == selected_style]
    if len(selected) != 1:
        raise ValueError(f"첫 첨삭 결과에 선택한 스타일이 없습니다: {style_id}")
    result = {
        "case_id": initial["case_id"],
        "prompt_version": initial["prompt_version"],
        "attempt": 1,
        "style_id": style_id,
        "requirements": {
            "job_title": checklist["job_title"],
            "company_values": deepcopy(checklist["company_values"]),
            "items": deepcopy(checklist["items"]),
        },
        "experiences": deepcopy(experience["experiences"]),
        "user_feedback": [],
        "old_revised_cv": [],
        "revised_cv": [{
            "attempt": 1,
            "style": selected_style,
            "sentences": [
                {key: sentence[key] for key in ("item_id", "source", "text", "llm_opinion", "user_feedback")}
                for sentence in selected[0]["sentences"]
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
) -> dict[str, Any]:
    """현재 첨삭 객체와 선택적 피드백을 받아 다음 회차의 같은 모양 객체를 돌려준다."""
    validate_feedback_input(data)
    if data["attempt"] >= 4:
        raise ValueError("피드백 재작성은 최대 attempt 4까지만 가능합니다.")
    current = data["revised_cv"][0]
    if feedback is None and data["user_feedback"]:
        new_feedback = data["user_feedback"][-1]
        feedback_history = deepcopy(data["user_feedback"])
    else:
        new_feedback = collect_feedback(current["sentences"]) if feedback is None else feedback
        feedback_history = [*deepcopy(data["user_feedback"]), deepcopy(new_feedback)]
    item_ids = {item["id"] for item in data["requirements"]["items"]}
    if not isinstance(new_feedback, dict) or any(
        item_id not in item_ids or not isinstance(value, str)
        for item_id, value in new_feedback.items()
    ):
        raise ValueError("피드백은 checklist의 item_id를 키로 하는 문자열 객체여야 합니다.")
    next_attempt = data["attempt"] + 1
    history = [deepcopy(current), *deepcopy(data["old_revised_cv"])]
    style_names = dict(STYLES)
    selected_style = data["style_id"] if data["style_id"] in style_names else next(
        key for key, name in STYLES if name == data["style_id"]
    )
    sources = {entry["item_id"]: entry["text"] for entry in data["experiences"]}
    sentences: list[dict[str, str]] = []
    if sources:
        prompt_data = {
            "case_id": data["case_id"],
            "prompt_version": PROMPT_VERSION,
            "attempt": next_attempt,
            "style_id": data["style_id"],
            "requirements": data["requirements"],
            "experiences": data["experiences"],
            "user_feedback": feedback_history,
            "old_revised_cv": history,
        }
        instructions = PROMPT_PATH.read_text(encoding="utf-8")
        prompt = (
            f"프롬프트 버전: {PROMPT_VERSION}\n스타일: {data['style_id']}\n"
            f"{instructions}\n입력 데이터: {json.dumps(prompt_data, ensure_ascii=False)}"
        )
        response = call_llm(prompt, LLM_SCHEMA)
        if not isinstance(response, dict) or not isinstance(response.get("sentences"), list):
            raise ValueError("Codex 답변에 sentences 목록이 없습니다.")
        by_id: dict[str, dict[str, Any]] = {}
        for index, sentence in enumerate(response["sentences"]):
            if not isinstance(sentence, dict) or not isinstance(sentence.get("item_id"), str):
                raise ValueError(f"Codex 답변의 sentences.{index}.item_id가 잘못되었습니다.")
            item_id = sentence["item_id"]
            if item_id not in item_ids or item_id in by_id:
                raise ValueError(f"Codex 답변의 item_id가 중복되었거나 checklist에 없습니다: {item_id}")
            if not isinstance(sentence.get("text"), str) or not isinstance(sentence.get("llm_opinion"), str):
                raise ValueError(f"Codex 답변의 sentences.{index}.text/llm_opinion은 문자열이어야 합니다.")
            by_id[item_id] = sentence
        missing = set(sources) - set(by_id)
        if missing:
            raise ValueError(f"Codex 답변에 입력 경험의 item_id가 빠졌습니다: {', '.join(sorted(missing))}")
        for item in data["requirements"]["items"]:
            item_id = item["id"]
            if item_id not in sources:
                continue
            generated = by_id[item_id]
            text = generated["text"].strip()
            if not text:
                continue
            opinion = generated["llm_opinion"].strip()
            if not opinion:
                raise ValueError(f"Codex 답변의 llm_opinion이 비어 있습니다: {item_id}")
            sentences.append({
                "item_id": item_id,
                "source": sources[item_id],
                "text": text,
                "llm_opinion": opinion,
                "user_feedback": "",
            })
    result = {
        "case_id": data["case_id"],
        "prompt_version": PROMPT_VERSION,
        "attempt": next_attempt,
        "style_id": data["style_id"],
        "requirements": deepcopy(data["requirements"]),
        "experiences": deepcopy(data["experiences"]),
        "user_feedback": [{item["id"]: "" for item in data["requirements"]["items"]}],
        "old_revised_cv": history,
        "revised_cv": [{"attempt": next_attempt, "style": selected_style, "sentences": sentences}],
    }
    validate_feedback_input(result)
    return result


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
