from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from loop.data_input import data_input
from loop.revise_cv import revise_cv
from loop.rewrite_cv import rewrite_cv
from loop.user_input import clean_terminal_input
from loop.initial_rewrite import build_entries, load_inputs, sample_paths
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


def show_rewrite_content(result: dict) -> None:
    """재작성 결과를 받아 사용자에게 문장 내용만 보여주고 아무 값도 돌려주지 않는다."""
    print(f"\n[피드백 {result['attempt'] - 1}/3 반영 결과]", file=sys.stderr)
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


def main() -> int:
    """실행 인수를 받아 대화형 또는 샘플 첫 재작성을 실행하고 종료 코드를 돌려준다."""
    parser = argparse.ArgumentParser(description="요구사항별 경험을 이력서 문장으로 다듬습니다.")
    parser.add_argument("case", nargs="?", type=Path)
    parser.add_argument(
        "--sample",
        action="store_true",
        help="샘플 경험으로 첫 스타일을 자동 선택해 피드백 없이 한 번 재작성합니다.",
    )
    arguments = parser.parse_args()
    if arguments.sample and arguments.case is not None:
        parser.error("--sample과 case 경로는 함께 사용할 수 없습니다.")
    try:
        inputResult = load_sample_input() if arguments.sample else data_input(arguments.case or DEFAULT_CASE)
        revisedResult = revise_cv(inputResult, auto_select=arguments.sample)
        feedback = (
            {sentence["item_id"]: "" for sentence in revisedResult["revised_cv"][0]["sentences"]}
            if arguments.sample else None
        )
        rewriteResult = rewrite_cv(revisedResult, feedback=feedback)
        show_rewrite_content(rewriteResult)
        while not arguments.sample and rewriteResult["attempt"] < 4 and ask_rewrite_again():
            rewriteResult = rewrite_cv(rewriteResult)
            show_rewrite_content(rewriteResult)
    except (OSError, ValueError, EOFError, RuntimeError, json.JSONDecodeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(json.dumps(rewriteResult, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
