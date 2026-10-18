from app.loop.call_llm import *
from app.constants import PROMPT_VERSION, STYLES, SENTENCE_SCHEMA
import re
import sys
from typing import Any

def revise_cv(inputResult: dict) -> dict[str, Any]:
    case = inputResult["case"]
    answers = inputResult["answers"]
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
        "case" : case,
        "answers" : answers,
        "revised_cv" : {
            "case_id": case["case_id"],
            "prompt_version": str(PROMPT_VERSION),
            "style": selected["style"],
            "attempt": 1,
            "sentences": selected["sentences"],
            "feedback": feedback,
        }
    }

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
        for line in (ROOT.parent / "scoring" / "ai_phrases.txt").read_text(
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