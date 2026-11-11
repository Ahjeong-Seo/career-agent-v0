"""checklist.json과 experience.json으로 첫 세 스타일의 rewrite 결과를 만든다."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loop.constants import PROMPT_VERSION, SCHEMA_VERSION, STYLES
from loop.data_contracts import (
    EXPERIENCE_SCHEMA_PATH,
    load_checklist,
    read_json,
    validate_document,
)
from loop.call_llm import call_llm


ROOT = Path(__file__).resolve().parents[1]
REWRITE_SCHEMA_PATH = ROOT / "schemas" / "rewrite.json"
REWRITE_LLM_SCHEMA_PATH = ROOT / "schemas" / "rewrite.llm.schema.json"
PROMPT_PATH = ROOT / "prompts" / f"{PROMPT_VERSION}.md"


@dataclass(frozen=True)
class RewritePaths:
    """rewrite 실행에 필요한 checklist, experience, 결과 파일 경로를 묶는다."""

    checklist: Path
    experience: Path
    output: Path


def case_paths(case_id: str) -> RewritePaths:
    """케이스 ID를 받아 data/cases 안의 입력·결과 경로를 돌려준다."""
    if not case_id or case_id in {".", ".."} or Path(case_id).name != case_id:
        raise ValueError("case_id에는 비어 있거나 폴더 경로를 넣을 수 없습니다.")
    case_dir = ROOT / "data" / "cases" / case_id
    return RewritePaths(
        checklist=case_dir / "checklist.json",
        experience=case_dir / "experience.json",
        output=case_dir / "rewrite.json",
    )


def sample_paths() -> RewritePaths:
    """샘플 입력과 샘플 실행 결과의 경로 묶음을 돌려준다."""
    samples_dir = ROOT / "samples"
    return RewritePaths(
        checklist=samples_dir / "checklist.sample.json",
        experience=samples_dir / "experience.sample.json",
        output=samples_dir / "rewrite.sample.test.json",
    )


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
        source = entry["text"]
        if not source.strip():
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
            answer = call_llm(
                make_prompt(entries, style_name), read_json(REWRITE_LLM_SCHEMA_PATH)
            )
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


def run_rewrite(
    paths: RewritePaths, *, expected_case_id: str | None = None
) -> Path:
    """파일 경로 묶음을 받아 rewrite를 만들고 저장 경로를 돌려준다."""
    checklist, experience = load_inputs(paths.checklist, paths.experience)
    if expected_case_id is not None and checklist["case_id"] != expected_case_id:
        raise ValueError(
            f"{paths.checklist}의 case_id가 폴더 이름과 다릅니다: {checklist['case_id']}"
        )
    rewrite = create_initial_rewrite(checklist, experience)
    save_rewrite(paths.output, rewrite)
    return paths.output


def run_case(case_id: str) -> Path:
    """케이스 ID를 받아 해당 케이스 파일로 rewrite를 실행하고 결과 경로를 돌려준다."""
    return run_rewrite(case_paths(case_id), expected_case_id=case_id)


def run_sample() -> Path:
    """샘플 파일로 rewrite를 실행하고 테스트 결과 경로를 돌려준다."""
    return run_rewrite(sample_paths())


def main() -> int:
    """케이스 ID 또는 --sample을 받아 rewrite.json을 만들고 종료 코드를 돌려준다."""
    parser = argparse.ArgumentParser(description="세 스타일의 첫 이력서 문장을 rewrite.json으로 저장합니다.")
    parser.add_argument(
        "case_id",
        nargs="?",
        help="data/cases/<case_id>/ 안의 checklist.json과 experience.json으로 실행",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="samples/의 입력을 사용하고 samples/rewrite.sample.test.json에 결과 저장",
    )
    arguments = parser.parse_args()

    if arguments.sample and arguments.case_id is not None:
        parser.error("--sample과 case_id는 함께 사용할 수 없습니다.")
    if not arguments.sample and not arguments.case_id:
        parser.error("case_id를 입력하거나 --sample을 사용해 주세요.")

    try:
        output_path = run_sample() if arguments.sample else run_case(arguments.case_id)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(f"세 스타일 결과를 저장했습니다: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
