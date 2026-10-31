from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.loop.data_input import data_input
from app.loop.revise_cv import revise_cv
from app.loop.rewrite_cv import rewrite_cv
from app.loop.user_input import clean_terminal_input
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


def main() -> int:
    """명령행 인수를 받아 프로그램을 실행하고 JSON을 출력한 뒤 종료 코드를 돌려준다."""
    parser = argparse.ArgumentParser(description="요구사항별 경험을 이력서 문장으로 다듬습니다.")
    parser.add_argument("case", nargs="?", type=Path, default=DEFAULT_CASE)
    arguments = parser.parse_args()
    try:
        inputResult = data_input(arguments.case)
        revisedResult = revise_cv(inputResult)
        rewriteResult = rewrite_cv(revisedResult)
        show_rewrite_content(rewriteResult)
        while rewriteResult["attempt"] < 4 and ask_rewrite_again():
            rewriteResult = rewrite_cv(rewriteResult)
            show_rewrite_content(rewriteResult)
    except (OSError, ValueError, EOFError, RuntimeError, json.JSONDecodeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(json.dumps(rewriteResult, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
