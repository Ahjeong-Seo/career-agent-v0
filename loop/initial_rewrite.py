"""checklist.json과 experience.json으로 첫 세 스타일의 rewrite 결과를 만든다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from loop.constants import PROMPT_VERSION, SCHEMA_VERSION, STYLES
from loop.data_contracts import (
    EXPERIENCE_SCHEMA_PATH,
    load_checklist,
    read_json,
    validate_document,
)
from loop.llm import call_llm


ROOT = Path(__file__).resolve().parents[1]
REWRITE_SCHEMA_PATH = ROOT / "schemas" / "rewrite.json"
PROMPT_PATH = ROOT / "prompts" / f"{PROMPT_VERSION}.md"

# Codex는 문장과 편집 이유를 만들고, 사용자 수정 요청은 빈 문자열로 시작한다.
SENTENCE_SCHEMA: dict[str, Any] = {
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
                    "text": {"type": "string", "minLength": 1},
                    "llm_opinion": {"type": "string", "minLength": 1},
                },
            },
        }
    },
}


def load_inputs(
    checklist_path: Path, experience_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """체크리스트와 경험 파일을 읽어 각 JSON Schema로 검사한 두 객체를 돌려준다."""
    # 체크리스트는 ID 중복까지 확인하는 공통 로더로 읽는다.
    checklist = load_checklist(checklist_path)
    experience = read_json(experience_path)
    validate_document(experience_path, experience, EXPERIENCE_SCHEMA_PATH)
    return checklist, experience


def build_entries(
    checklist: dict[str, Any], experience: dict[str, Any]
) -> list[dict[str, Any]]:
    """체크리스트와 경험을 받아 LLM 입력 및 원문 대조에 쓸 항목 목록을 돌려준다."""
    if checklist["case_id"] != experience["case_id"]:
        raise ValueError("checklist.json과 experience.json의 case_id가 다릅니다.")

    items_by_id = {item["id"]: item for item in checklist["items"]}
    sources: dict[str, str] = {}
    for entry in experience["experiences"]:
        item_id = entry["item_id"]
        if item_id not in items_by_id:
            raise ValueError(
                f"experience.json의 experiences에 checklist에 없는 item_id가 있습니다: {item_id}"
            )
        if item_id in sources:
            raise ValueError(f"experience.json에 중복된 item_id가 있습니다: {item_id}")
        source = entry["text"].strip()
        if not source:
            raise ValueError(f"experience.json의 text가 비어 있습니다: {item_id}")
        sources[item_id] = source

    # checklist 순서를 유지해 이후 LLM 응답과 화면 목록 순서가 흔들리지 않게 한다.
    return [
        {
            "item_id": item["id"],
            "requirement": item["text"],
            "keywords": item["keywords"],
            "type": item["type"],
            "level": item["level"],
            "source": sources[item["id"]],
        }
        for item in checklist["items"]
        if item["id"] in sources
    ]


def make_prompt(entries: list[dict[str, Any]], style_name: str) -> str:
    """항목별 실제 경험과 한글 스타일 이름을 받아 한 번의 LLM 프롬프트를 돌려준다."""
    instructions = PROMPT_PATH.read_text(encoding="utf-8")
    return (
        f"프롬프트 버전: {PROMPT_VERSION}\n"
        f"작성 스타일: {style_name}\n"
        f"{instructions}\n"
        f"입력 데이터: {json.dumps(entries, ensure_ascii=False)}"
    )


def validate_llm_sentences(
    response: dict[str, Any], entries: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """LLM 답변과 입력 항목을 받아 ID·문장을 검사한 sentence 목록을 돌려준다."""
    sentences = response.get("sentences")
    if not isinstance(sentences, list):
        raise ValueError("Codex 답변에 sentences 배열이 없습니다.")

    expected_ids = {entry["item_id"] for entry in entries}
    sentences_by_id: dict[str, dict[str, str]] = {}
    for sentence in sentences:
        if not isinstance(sentence, dict):
            raise ValueError("Codex 답변의 sentence 항목은 JSON 객체여야 합니다.")
        item_id = sentence.get("item_id")
        text = sentence.get("text")
        opinion = sentence.get("llm_opinion")
        if not isinstance(item_id, str) or item_id in sentences_by_id:
            raise ValueError("Codex 답변에 item_id가 없거나 중복되었습니다.")
        if item_id not in expected_ids:
            raise ValueError(f"Codex 답변에 입력되지 않은 item_id가 있습니다: {item_id}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Codex 답변의 text가 비어 있습니다: {item_id}")
        if not isinstance(opinion, str) or not opinion.strip():
            raise ValueError(f"Codex 답변의 llm_opinion이 비어 있습니다: {item_id}")
        sentences_by_id[item_id] = {
            "text": text.strip(),
            "llm_opinion": opinion.strip(),
        }

    if set(sentences_by_id) != expected_ids:
        missing = sorted(expected_ids - set(sentences_by_id))
        raise ValueError(f"Codex 답변에 입력 경험의 문장이 빠졌습니다: {', '.join(missing)}")

    # source는 LLM이 다시 쓰지 않고 원본 경험 파일에서 복사해 일치성을 보장한다.
    return [
        {
            "item_id": entry["item_id"],
            "source": entry["source"],
            "text": sentences_by_id[entry["item_id"]]["text"],
            "llm_opinion": sentences_by_id[entry["item_id"]]["llm_opinion"],
            "user_feedback": "",
        }
        for entry in entries
    ]


def create_initial_rewrite(
    checklist: dict[str, Any], experience: dict[str, Any]
) -> dict[str, Any]:
    """검증한 체크리스트와 경험을 받아 세 스타일 후보가 든 rewrite 객체를 돌려준다."""
    entries = build_entries(checklist, experience)
    style_results: list[dict[str, Any]] = []

    # 회의 합의대로 세 스타일은 동시에가 아니라 정해진 순서로 하나씩 생성한다.
    for number, (style_id, style_name) in enumerate(STYLES, start=1):
        print(f"[{number}/3] '{style_name}' 문장을 생성합니다.", file=sys.stderr, flush=True)
        if entries:
            answer = call_llm(make_prompt(entries, style_name), SENTENCE_SCHEMA)
            sentences = validate_llm_sentences(answer, entries)
        else:
            # 경험이 하나도 없으면 지어낸 내용을 만들지 않고 빈 후보를 저장한다.
            sentences = []
        style_results.append(
            {"attempt": 1, "style": style_id, "sentences": sentences}
        )

    result = {
        "schema_version": SCHEMA_VERSION,
        "case_id": checklist["case_id"],
        "prompt_version": PROMPT_VERSION,
        "attempt": 1,
        "style": "",
        "revised_cv": style_results,
    }
    validate_document(Path("rewrite.json"), result, REWRITE_SCHEMA_PATH)
    return result


def save_rewrite(path: Path, rewrite: dict[str, Any]) -> None:
    """rewrite.json 경로와 결과 객체를 받아 폴더를 만들고 저장한 뒤 None을 돌려준다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rewrite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_from_files(
    checklist_path: Path, experience_path: Path, output_path: Path
) -> Path:
    """체크리스트·경험·결과 경로를 받아 rewrite를 저장하고 그 경로를 돌려준다."""
    checklist, experience = load_inputs(checklist_path, experience_path)
    rewrite = create_initial_rewrite(checklist, experience)
    save_rewrite(output_path, rewrite)
    return output_path


def main() -> int:
    """명령행에서 두 입력 파일을 받아 rewrite.json을 만들고 종료 코드를 돌려준다."""
    parser = argparse.ArgumentParser(description="세 스타일의 첫 이력서 문장을 rewrite.json으로 저장합니다.")
    parser.add_argument("checklist", type=Path, help="앞 단계에서 만든 checklist.json 파일 경로")
    parser.add_argument("experience", type=Path, help="앞 단계에서 만든 experience.json 파일 경로")
    parser.add_argument("rewrite", type=Path, help="생성한 rewrite.json을 저장할 경로")
    arguments = parser.parse_args()
    try:
        output = create_from_files(arguments.checklist, arguments.experience, arguments.rewrite)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(f"세 스타일 결과를 저장했습니다: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
