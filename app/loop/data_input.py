from pathlib import Path
from typing import Any
import json
import sys
import time

from app.loop.call_llm import *

def data_input(case_path: Path) -> dict[str, Any]:
    """체크리스트 경로를 받아 경험 수집·첨삭 후 최종 JSON 데이터를 돌려준다."""
    case = load_case(case_path)
    answers = ask_experiences(case["items"])

    return {
        "case" : case,
        "answers" : answers
    }

def load_case(path: Path) -> dict[str, Any]:
    """체크리스트 파일 경로를 받아 필수 항목을 확인한 데이터를 돌려준다."""
    case = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(case, dict) or not isinstance(case.get("items"), list):
        raise ValueError("체크리스트에 items 배열이 필요합니다.")
    if not isinstance(case.get("case_id"), str) or not case["case_id"]:
        raise ValueError("체크리스트에 case_id 문자열이 필요합니다.")
    seen: set[str] = set()
    for item in case["items"]:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str) and item[key]
            for key in ("id", "text", "level")
        ):
            raise ValueError("각 항목에는 id, text, level 문자열이 필요합니다.")
        if item["id"] in seen:
            raise ValueError(f"중복된 항목 ID: {item['id']}")
        seen.add(item["id"])
    return case

def ask_experiences(items: list[dict[str, Any]]) -> dict[str, str]:
    """요구사항 목록을 받아 사용자에게 차례로 묻고 항목별 원문을 돌려준다."""
    answers: dict[str, str] = {}
    for item in items:
        while True:
            print(
                f"[{item['id']}] {item['text']} ({item['level']})\n"
                "실제 경험을 적어 주세요. 없으면 Enter, 종료하려면 exit: ",
                end="",
                file=sys.stderr,
                flush=True,
            )
            answer = sys.stdin.readline()
            if answer == "":
                raise EOFError("모든 항목의 경험을 입력하기 전에 입력이 종료되었습니다.")
            if answer.strip().casefold() == "exit":
                print("프로그램을 종료합니다.", file=sys.stderr)
                raise SystemExit(0)
            try:
                answer.encode("utf-8")
            except UnicodeEncodeError:
                print(
                    "입력 인코딩 오류입니다. 이 항목을 다시 입력해 주세요. "
                    "터미널 문자 인코딩도 UTF-8인지 확인해 주세요.",
                    file=sys.stderr,
                )
                continue
            answers[item["id"]] = answer.strip()
            break
    return answers
