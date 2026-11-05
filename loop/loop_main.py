from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from loop.data_input import data_input
from loop.revise_cv import choose_style, revise_cv
from loop.rewrite_cv import rewrite_cv
from loop.user_input import clean_terminal_input
from loop.constants import SCHEMA_VERSION, STYLES
from loop.data_contracts import EXPERIENCE_SCHEMA_PATH, read_json, validate_document
from loop.initial_rewrite import (
    REWRITE_SCHEMA_PATH,
    RewritePaths,
    build_entries,
    case_paths,
    load_inputs,
    run_case,
    sample_paths,
    save_rewrite,
)
from app.constants import DEFAULT_CASE


def ask_rewrite_again() -> bool:
    """사용자의 계속 여부 입력을 받아 재작성을 계속할지 돌려준다."""
    while True:
        print("피드백을 더 반영할까요? (y: 계속 / n: 완료): ", end="", file=sys.stderr, flush=True)
        choice = sys.stdin.readline()
        if choice == "":
            raise EOFError("재작성 계속 여부를 입력하기 전에 입력이 종료되었습니다.")
        answer = clean_terminal_input(choice).strip().casefold()
        if answer in {"y", "yes", "예", "네"}:
            return True
        if answer in {"n", "no", "아니요", "아니오"}:
            return False
        print("y 또는 n으로 입력해 주세요.", file=sys.stderr)


def show_rewrite_content(result: dict, *, first_attempt: int = 0) -> None:
    """재작성 결과와 첫 회차 번호를 받아 문장을 보여주고 아무 값도 돌려주지 않는다."""
    round_number = result["attempt"] - first_attempt
    title = "첫 첨삭 결과" if round_number == 0 else f"피드백 {round_number}/3 반영 결과"
    print(f"\n[{title}]", file=sys.stderr)
    for version in result["revised_cv"]:
        for sentence in version["sentences"]:
            print(f"{sentence['item_id']}: {sentence['text']}", file=sys.stderr)


def load_sample_input() -> dict:
    """샘플 체크리스트·경험을 검사해 대화형 루프가 받는 입력 모양으로 돌려준다."""
    paths = sample_paths()
    checklist, experience = load_inputs(paths.checklist, paths.experience)
    entries = build_entries(checklist, experience)
    answers = {item["id"]: "" for item in checklist["items"]}
    answers.update({entry["item_id"]: entry["source"] for entry in entries})
    return {"case": checklist, "answers": answers}


def save_case_feedback(paths: RewritePaths, experience: dict, result: dict) -> None:
    """케이스 경로·경험·재작성 결과를 받아 계약을 검사하고 두 JSON 파일을 저장한다."""
    rewrite = {
        "schema_version": SCHEMA_VERSION,
        "case_id": result["case_id"],
        "prompt_version": result["prompt_version"],
        "attempt": result["attempt"],
        "style": result["style_id"],
        "revised_cv": [{
            "attempt": result["attempt"],
            "style": result["style_id"],
            "sentences": [
                sentence
                for sentence in result["revised_cv"][0]["sentences"] if sentence["source"]
            ],
        }],
    }
    known_ids = {entry["item_id"] for entry in experience["experiences"]}
    added = [entry for entry in result["experiences"] if entry["item_id"] not in known_ids]
    updated_experience = {**experience, "experiences": experience["experiences"] + added}
    validate_document(paths.experience, updated_experience, EXPERIENCE_SCHEMA_PATH)
    validate_document(paths.output, rewrite, REWRITE_SCHEMA_PATH)
    if added:
        paths.experience.write_text(
            json.dumps(updated_experience, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        experience["experiences"].extend(added)
    save_rewrite(paths.output, rewrite)


def run_case_feedback(case_id: str) -> Path:
    """case_id를 받아 첫 첨삭을 저장하고 사용자 피드백을 반영한 파일 경로를 돌려준다."""
    paths = case_paths(case_id)
    run_case(case_id)
    checklist, experience = load_inputs(paths.checklist, paths.experience)
    first = read_json(paths.output)
    style_names = dict(STYLES)
    options = [
        {"style_id": version["style"], "style": style_names[version["style"]],
         "sentences": version["sentences"]}
        for version in first["revised_cv"]
    ]
    selected = choose_style(options)
    by_id = {sentence["item_id"]: sentence for sentence in selected["sentences"]}
    sentences = [
        by_id.get(item["id"], {
            "item_id": item["id"], "source": "", "text": "",
            "llm_opinion": "", "user_feedback": "",
        })
        for item in checklist["items"]
    ]
    current = {
        "case_id": case_id,
        "prompt_version": first["prompt_version"],
        "attempt": 1,
        "style_id": selected["style_id"],
        "requirements": {
            "job_title": checklist["job_title"],
            "company_values": checklist["company_values"],
            "items": checklist["items"],
        },
        "experiences": experience["experiences"],
        "user_feedback": [],
        "old_revised_cv": [],
        "revised_cv": [{"attempt": 1, "style_id": selected["style_id"], "sentences": sentences}],
    }
    while True:
        current = rewrite_cv(current, first_attempt=1, max_attempt=4)
        save_case_feedback(paths, experience, current)
        show_rewrite_content(current, first_attempt=1)
        if current["attempt"] == 4 or not ask_rewrite_again():
            return paths.output


def main() -> int:
    """case_id 또는 기존 입력을 받아 첫 rewrite 저장이나 대화형 재작성을 실행하고 종료 코드를 돌려준다."""
    parser = argparse.ArgumentParser(description="요구사항별 경험을 이력서 문장으로 다듬습니다.")
    parser.add_argument("case", nargs="?", help="case_id 또는 기존 체크리스트 JSON 파일 경로")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="샘플 경험으로 첫 스타일을 자동 선택하고 피드백을 받습니다.",
    )
    arguments = parser.parse_args()
    if arguments.sample and arguments.case is not None:
        parser.error("--sample과 case_id/경로는 함께 사용할 수 없습니다.")
    if arguments.case is not None:
        case_path = Path(arguments.case)
        if case_path.suffix != ".json" and case_path.parent == Path("."):
            try:
                output_path = run_case_feedback(arguments.case)
            except (OSError, ValueError, EOFError, RuntimeError) as error:
                print(f"오류: {error}", file=sys.stderr)
                return 1
            print(f"피드백 결과를 저장했습니다: {output_path}")
            return 0
    latest_result = None
    stage = "input"
    try:
        inputResult = load_sample_input() if arguments.sample else data_input(Path(arguments.case) if arguments.case else DEFAULT_CASE)
        stage = "revise_cv"
        revisedResult = revise_cv(inputResult, auto_select=arguments.sample)
        latest_result = revisedResult
        if arguments.sample:
            show_rewrite_content(revisedResult)
        stage = "rewrite_cv"
        rewriteResult = rewrite_cv(revisedResult)
        latest_result = rewriteResult
        show_rewrite_content(rewriteResult)
        while rewriteResult["attempt"] < 3:
            stage = "feedback_choice"
            if not ask_rewrite_again():
                break
            stage = "rewrite_cv"
            rewriteResult = rewrite_cv(rewriteResult)
            latest_result = rewriteResult
            show_rewrite_content(rewriteResult)
    except (OSError, ValueError, EOFError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({
            "ok": False,
            "stage": stage,
            "error": {"type": type(error).__name__, "message": str(error)},
            "result": latest_result,
        }, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(rewriteResult, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
