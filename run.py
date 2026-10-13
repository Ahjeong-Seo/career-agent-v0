"""체크리스트별 경험을 입력받고 Codex로 다듬은 JSON을 출력한다."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from loop.llm import call_llm


ROOT = Path(__file__).resolve().parent
DEFAULT_CASE = ROOT / "samples" / "checklist.sample.json"
PROMPT_VERSION = "write_v1"
STYLES = ("성과 강조형", "담백한 사실형", "직무 연결형")
SENTENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["item_id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
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
                "실제 경험을 적어 주세요. 없으면 Enter: ",
                end="",
                file=sys.stderr,
                flush=True,
            )
            answer = sys.stdin.readline()
            if answer == "":
                raise EOFError("모든 항목의 경험을 입력하기 전에 입력이 종료되었습니다.")
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


def make_feedback(item: dict[str, Any], source: str) -> str:
    """요구사항과 원문을 받아 부족한 실제 정보에 관한 피드백을 돌려준다."""
    if not source:
        return "경험 없음: 실제 경험이 있다면 입력해 주세요. 없는 내용은 작성하지 않습니다."

    messages: list[str] = []
    required_years = re.search(r"(\d+)\s*년\s*이상", item["text"])
    source_has_duration = re.search(r"\d+\s*(?:년|개월|주|일)", source)
    if required_years and not source_has_duration:
        messages.append(
            f"요구사항은 {required_years.group(1)}년 이상입니다. "
            "실제 사용 기간이 얼마인지 알려 주세요."
        )
    if len(source.split()) <= 4:
        messages.append("실제로 한 업무나 사용 사례가 있다면 구체적으로 알려 주세요.")
    return " ".join(messages) if messages else "추가로 확인할 정보가 없습니다."


def make_prompt(
    case: dict[str, Any], answers: dict[str, str], style: str
) -> str:
    """체크리스트와 경험·스타일을 받아 Codex에 보낼 프롬프트를 돌려준다."""
    instructions = (ROOT / "prompts" / f"{PROMPT_VERSION}.md").read_text(
        encoding="utf-8"
    )
    entries = [
        {"item_id": item["id"], "requirement": item["text"], "source": answers[item["id"]]}
        for item in case["items"]
        if answers[item["id"]]
    ]
    return (
        f"프롬프트 버전: {PROMPT_VERSION}\n"
        f"스타일: {style}\n{instructions}\n"
        f"입력 데이터: {json.dumps(entries, ensure_ascii=False)}"
    )


def safe_sentences(
    response: dict[str, Any], items: list[dict[str, Any]], answers: dict[str, str]
) -> list[dict[str, str]]:
    """Codex 답변과 원문을 받아 항목·숫자를 검증한 문장 목록을 돌려준다."""
    entries = response.get("sentences")
    if not isinstance(entries, list):
        raise ValueError("Codex 답변에 sentences 배열이 없습니다.")
    by_id: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("item_id"), str):
            raise ValueError("Codex 답변의 항목 ID가 잘못되었습니다.")
        if not isinstance(entry.get("text"), str) or not entry["text"].strip():
            raise ValueError("Codex 답변에 빈 문장이 있습니다.")
        if entry["item_id"] in by_id:
            raise ValueError(f"Codex 답변의 중복 항목: {entry['item_id']}")
        by_id[entry["item_id"]] = entry["text"].strip()

    expected = {item["id"] for item in items if answers[item["id"]]}
    if set(by_id) != expected:
        raise ValueError("Codex 답변의 항목 ID가 입력한 경험과 일치하지 않습니다.")

    phrases = [
        line.strip()
        for line in (ROOT / "scoring" / "ai_phrases.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    sentences: list[dict[str, str]] = []
    for item in items:
        item_id = item["id"]
        source = answers[item_id]
        if not source:
            continue
        revised = by_id[item_id]
        source_numbers = set(re.findall(r"\d+(?:\.\d+)?", source))
        revised_numbers = set(re.findall(r"\d+(?:\.\d+)?", revised))
        keywords = [str(word).casefold() for word in item.get("keywords", [])]
        has_keyword = any(word in source.casefold() for word in keywords)
        kept_keyword = any(word in revised.casefold() for word in keywords)
        bad_phrase = any(
            phrase in revised and phrase.casefold() not in keywords for phrase in phrases
        )
        if (
            not revised_numbers.issubset(source_numbers)
            or bad_phrase
            or has_keyword != kept_keyword
            or len(source.split()) <= 4
        ):
            revised = source
        sentences.append({"item_id": item_id, "source": source, "text": revised})
    return sentences


def choose_style(options: list[dict[str, Any]]) -> dict[str, Any]:
    """세 가지 문장 후보를 받아 사용자 선택에 해당하는 결과를 돌려준다."""
    for index, option in enumerate(options, start=1):
        print(f"\n{index}. {option['style']}", file=sys.stderr)
        for sentence in option["sentences"]:
            print(f"  {sentence['item_id']}: {sentence['text']}", file=sys.stderr)
    print("스타일 번호를 선택해 주세요 (1-3): ", end="", file=sys.stderr, flush=True)
    choice = sys.stdin.readline().strip()
    if choice not in {"1", "2", "3"}:
        raise ValueError("스타일은 1, 2, 3 중 하나를 선택해 주세요.")
    return options[int(choice) - 1]


def run(case_path: Path) -> dict[str, Any]:
    """체크리스트 경로를 받아 경험 수집·첨삭 후 최종 JSON 데이터를 돌려준다."""
    case = load_case(case_path)
    answers = ask_experiences(case["items"])
    feedback = [
        {"item_id": item["id"], "text": make_feedback(item, answers[item["id"]])}
        for item in case["items"]
    ]
    if any(answers.values()):
        options = []
        for index, style in enumerate(STYLES, start=1):
            print(
                f"[{index}/{len(STYLES)}] Codex가 '{style}' 문장을 작성 중입니다. 잠시 기다려 주세요...",
                file=sys.stderr,
                flush=True,
            )
            started = time.monotonic()
            try:
                response = call_llm(make_prompt(case, answers, style), SENTENCE_SCHEMA)
                sentences = safe_sentences(response, case["items"], answers)
            except (OSError, ValueError, RuntimeError):
                print(f"[{index}/{len(STYLES)}] '{style}' 작성 실패", file=sys.stderr)
                raise
            options.append(
                {"style": style, "sentences": sentences}
            )
            print(
                f"[{index}/{len(STYLES)}] '{style}' 완료 ({time.monotonic() - started:.1f}초)",
                file=sys.stderr,
                flush=True,
            )
        selected = choose_style(options)
    else:
        selected = {"style": STYLES[0], "sentences": []}
    return {
        "case_id": case["case_id"],
        "prompt_version": PROMPT_VERSION,
        "style": selected["style"],
        "attempt": 1,
        "sentences": selected["sentences"],
        "feedback": feedback,
    }


def main() -> int:
    """명령행 인수를 받아 프로그램을 실행하고 JSON을 출력한 뒤 종료 코드를 돌려준다."""
    parser = argparse.ArgumentParser(description="요구사항별 경험을 이력서 문장으로 다듬습니다.")
    parser.add_argument("case", nargs="?", type=Path, default=DEFAULT_CASE)
    arguments = parser.parse_args()
    try:
        result = run(arguments.case)
    except (OSError, ValueError, EOFError, RuntimeError, json.JSONDecodeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
