"""rewrite JSON을 기존 채점 계약에 맞춰 규칙으로 평가한다."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AI_PHRASES_PATH = ROOT / "scoring" / "ai_phrases.txt"
NUMBER_PATTERN = re.compile(r"\d[\d,]*")


def _load_ai_phrases() -> list[str]:
    """인수 없이 AI 표현 파일을 읽어 주석과 빈 줄을 제외한 문구 목록을 반환한다."""
    return [
        line.strip()
        for line in AI_PHRASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _normalized_numbers(text: str) -> set[str]:
    """문자열을 받아 쉼표를 뺀 숫자 덩어리 집합으로 반환한다."""
    return {match.replace(",", "") for match in NUMBER_PATTERN.findall(text)}


def score_case(
    checklist: dict[str, Any], experience: dict[str, Any], rewrite: dict[str, Any]
) -> dict[str, Any]:
    """체크리스트·경험·rewrite를 받아 schemas/score.json 모양의 채점 결과를 반환한다."""
    case_id = checklist.get("case_id")
    if experience.get("case_id") != case_id or rewrite.get("case_id") != case_id:
        raise ValueError("checklist, experience, rewrite의 case_id가 일치해야 합니다.")
    style_id = rewrite.get("style_id")
    if style_id not in ("achievement", "keyword", "concise"):
        raise ValueError("rewrite의 style_id는 achievement, keyword, concise 중 하나여야 합니다.")
    attempt = rewrite.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or not 1 <= attempt <= 4:
        raise ValueError("rewrite의 attempt는 1부터 4까지의 정수여야 합니다.")

    items = checklist.get("items")
    sentences = rewrite.get("sentences")
    experiences = experience.get("experiences")
    if not isinstance(items, list) or not isinstance(sentences, list) or not isinstance(experiences, list):
        raise ValueError("checklist.items, rewrite.sentences, experience.experiences는 목록이어야 합니다.")

    checklist_ids = [item.get("id") for item in items if isinstance(item, dict)]
    if len(checklist_ids) != len(items) or len(checklist_ids) != len(set(checklist_ids)):
        raise ValueError("checklist.items는 고유한 id를 가진 객체 목록이어야 합니다.")
    experience_by_id = {}
    for row in experiences:
        if not isinstance(row, dict):
            raise ValueError("experience.experiences의 각 항목은 JSON 객체여야 합니다.")
        item_id = row.get("item_id")
        if item_id in experience_by_id:
            raise ValueError(f"experience.experiences에 item_id {item_id}가 중복됩니다.")
        if item_id not in checklist_ids:
            raise ValueError(f"체크리스트에 없는 experience.item_id입니다: {item_id}")
        experience_by_id[item_id] = row.get("text")
    sentence_by_id: dict[str, dict[str, Any]] = {}
    for sentence in sentences:
        if not isinstance(sentence, dict) or not isinstance(sentence.get("item_id"), str):
            raise ValueError("rewrite.sentences의 각 항목에는 문자열 item_id가 필요합니다.")
        item_id = sentence["item_id"]
        if item_id in sentence_by_id:
            raise ValueError(f"rewrite.sentences에 item_id {item_id}가 중복됩니다.")
        if item_id not in checklist_ids:
            raise ValueError(f"체크리스트에 없는 item_id입니다: {item_id}")
        source = sentence.get("source")
        if item_id in experience_by_id and source != experience_by_id[item_id]:
            raise ValueError(f"{item_id}: rewrite.source와 experience.text가 다릅니다.")
        if item_id not in experience_by_id and source not in (None, ""):
            raise ValueError(f"{item_id}: 경험 입력이 없는 항목에 rewrite.source가 있습니다.")
        sentence_by_id[item_id] = sentence

    ai_phrases = _load_ai_phrases()
    result_items = []
    made_up_numbers = []
    detected_ai_phrases = []
    feedback = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("checklist.items의 각 항목은 JSON 객체여야 합니다.")
        item_id = item.get("id")
        source = experience_by_id.get(item_id)
        sentence = sentence_by_id.get(item_id, {})
        text = sentence.get("text")
        text = text if isinstance(text, str) else ""
        keywords = item.get("keywords", [])

        if not isinstance(source, str) or not source.strip():
            status = "경험 없음"
            reason = "입력된 경험이 없음"
            if item.get("type") == "경력":
                reason += " · 연수 미확인"
            if text.strip():
                feedback.append(f"{item_id}: 경험 없는 항목의 문장 삭제")
        else:
            matched = next(
                (keyword for keyword in keywords if isinstance(keyword, str) and keyword.casefold() in text.casefold()),
                None,
            )
            status = "충족" if matched else "미충족"
            reason = f"'{matched}' 포함" if matched else "첨삭 문장에 체크리스트 키워드가 없음"
            if not matched:
                feedback.append(f"{item_id}: 첨삭 문장에 체크리스트 키워드 중 하나를 포함하기")
            if item.get("type") == "경력":
                reason += " · 연수 미확인"

        result_items.append({"item_id": item_id, "status": status, "reason": reason})
        if source:
            unsupported = _normalized_numbers(text) - _normalized_numbers(source)
            for number in sorted(unsupported):
                made_up_numbers.append({"item_id": item_id, "number": number, "reason": "원래 경험 글에 없는 숫자"})
                feedback.append(f"{item_id}: 원래 글에 없는 숫자 '{number}'을(를) 빼기")
        normalized_keywords = {word.casefold() for word in keywords if isinstance(word, str)}
        for phrase in ai_phrases:
            if phrase in text and phrase.casefold() not in normalized_keywords:
                detected_ai_phrases.append({"item_id": item_id, "phrase": phrase})
                feedback.append(f"{item_id}: AI 표현 '{phrase}' 바꾸기")

    counted_required_ids = {
        item["id"]
        for item in items
        if item.get("level") == "필수"
        and item.get("type") != "기타"
        and isinstance(experience_by_id.get(item.get("id")), str)
        and experience_by_id[item["id"]].strip()
    }
    status_by_id = {row["item_id"]: row["status"] for row in result_items}
    passed = (
        all(status_by_id[item_id] == "충족" for item_id in counted_required_ids)
        and not any(issue["item_id"] in counted_required_ids for issue in made_up_numbers)
        and not any(issue["item_id"] in counted_required_ids for issue in detected_ai_phrases)
        and not any(
            status_by_id[row["item_id"]] == "경험 없음" and (sentence_by_id.get(row["item_id"], {}).get("text") or "").strip()
            for row in result_items
        )
    )
    if passed:
        feedback = []
    return {
        "schema_version": 1,
        "case_id": case_id,
        "attempt": attempt,
        "style_id": style_id,
        "passed": passed,
        "items": result_items,
        "made_up_numbers": made_up_numbers,
        "ai_phrases": detected_ai_phrases,
        "feedback": "\n".join(dict.fromkeys(feedback)),
    }
