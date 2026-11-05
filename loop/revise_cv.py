from loop.call_llm import ROOT, call_llm
from loop.constants import PROMPT_VERSION, STYLES
from loop.data_contracts import read_json
from loop.initial_rewrite import (
    REWRITE_LLM_SCHEMA_PATH,
    build_entries,
    make_prompt,
    validate_llm_sentences,
)
import re
import sys
import time
from typing import Any

def revise_cv(inputResult: dict, *, auto_select: bool = False) -> dict[str, Any]:
    """체크리스트·경험을 받아 첫 생성의 입력·선택 결과·횟수를 함께 돌려준다."""
    case = inputResult["case"]
    answers = inputResult["answers"]
    experiences = [
        {"item_id": item["id"], "text": answers[item["id"]]}
        for item in case["items"] if answers[item["id"]]
    ]
    entries = build_entries(case, {"case_id": case["case_id"], "experiences": experiences})
    if entries:
        schema = read_json(REWRITE_LLM_SCHEMA_PATH)
        options = []
        for index, (style_id, style_name) in enumerate(STYLES, start=1):
            print(
                f"[{index}/{len(STYLES)}] Codex가 '{style_name}' 문장을 작성 중입니다. 잠시 기다려 주세요...",
                file=sys.stderr,
                flush=True,
            )
            started = time.monotonic()
            try:
                response = call_llm(make_prompt(entries, style_name), schema)
                sentences = validate_llm_sentences(response, entries)
            except (OSError, ValueError, RuntimeError):
                print(f"[{index}/{len(STYLES)}] '{style_name}' 작성 실패", file=sys.stderr)
                raise
            options.append(
                {"style_id": style_id, "style": style_name, "sentences": sentences}
            )
            print(
                f"[{index}/{len(STYLES)}] '{style_name}' 완료 ({time.monotonic() - started:.1f}초)",
                file=sys.stderr,
                flush=True,
            )
        selected = options[0] if auto_select else choose_style(options)
    else:
        selected = {"style_id": STYLES[0][0], "style": STYLES[0][1], "sentences": []}
    generated_by_id = {sentence["item_id"]: sentence for sentence in selected["sentences"]}
    selected["sentences"] = [
        generated_by_id[item["id"]] if answers[item["id"]] else {
            "item_id": item["id"],
            "source": "",
            "text": "",
            "llm_opinion": "",
            "user_feedback": "",
        }
        for item in case["items"]
    ]
    return {
        "case_id": case["case_id"],
        "prompt_version": str(PROMPT_VERSION),
        "attempt": 0,
        "style_id": selected["style_id"],
        "requirements": {
            "job_title": case["job_title"],
            "company_values": case["company_values"],
            "items": case["items"],
        },
        "experiences": experiences,
        "user_feedback": [],
        "old_revised_cv": [],
        "revised_cv": [
            {"attempt": 0, "style_id": selected["style_id"], "sentences": selected["sentences"]}
        ],
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


def safe_sentences(
    response: dict[str, Any], items: list[dict[str, Any]], answers: dict[str, str]
) -> list[dict[str, str]]:
    """Codex 답변과 원문을 받아 빈 문장을 건너뛰고 검증한 문장 목록을 돌려준다."""
    entries = response.get("sentences")
    if not isinstance(entries, list):
        raise ValueError("Codex 답변에 sentences 배열이 없습니다.")
    by_id: dict[str, str] = {}
    seen: set[str] = set()
    item_ids = {item["id"] for item in items}
    unknown_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("item_id"), str):
            raise ValueError("Codex 답변의 항목 ID가 잘못되었습니다.")
        item_id = entry["item_id"]
        if item_id in seen:
            raise ValueError(f"Codex 답변의 중복 항목: {item_id}")
        seen.add(item_id)
        if item_id not in item_ids:
            unknown_ids.add(item_id)
            continue
        if not answers[item_id]:
            # 경험 없는 항목에 LLM이 내용을 썼더라도 실제 결과에는 넣지 않는다.
            continue
        if not isinstance(entry.get("text"), str):
            raise ValueError(f"Codex 답변의 text는 문자열이어야 합니다: {item_id}")
        if not entry["text"].strip():
            continue
        by_id[item_id] = entry["text"].strip()

    expected = {item["id"] for item in items if answers[item["id"]]}
    if not expected.issubset(seen) or unknown_ids:
        missing = ", ".join(sorted(expected - seen)) or "없음"
        unexpected = ", ".join(sorted(unknown_ids)) or "없음"
        raise ValueError(
            f"Codex 답변의 항목 ID가 입력한 경험과 일치하지 않습니다. "
            f"누락: {missing}; 입력에 없는 ID: {unexpected}"
        )

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
            sentences.append({
                "item_id": item_id,
                "source": "",
                "text": "",
                "llm_opinion": "",
                "user_feedback": "",
            })
            continue
        if item_id not in by_id:
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
        sentences.append({"item_id": item_id, "source": source, "text": revised, "user_feedback": ""})
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
