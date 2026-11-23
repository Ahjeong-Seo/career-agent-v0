"""화면의 사용자·채점 의견을 루프의 항목별 재작성 입력으로 바꾼다."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from loop.feedback_loop import prepare_feedback_input
from loop.retry_rewrite import validate_feedback_input


_ITEM_FEEDBACK_LINE = re.compile(r"^(req-\d+):[ \t]*(.*)$")


def parse_score_feedback(
    score_feedback_text: str, item_ids: set[str]
) -> tuple[list[dict[str, str]], list[str], list[str]]:
    """채점 feedback 문자열과 허용 item_id를 받아 연결된 의견·오류 줄을 반환한다."""
    score_by_id: dict[str, str] = {}
    unmatched_lines: list[str] = []
    unknown_item_ids: list[str] = []
    for line in score_feedback_text.splitlines():
        if not line.strip():
            continue
        match = _ITEM_FEEDBACK_LINE.fullmatch(line)
        if match is None:
            unmatched_lines.append(line)
            continue
        item_id, message = match.groups()
        message = message.strip()
        if item_id not in item_ids:
            unmatched_lines.append(line)
            if item_id not in unknown_item_ids:
                unknown_item_ids.append(item_id)
            continue
        if message:
            score_by_id[item_id] = f"{score_by_id[item_id]}\n{message}" if item_id in score_by_id else message
    return (
        [{"item_id": item_id, "text": message} for item_id, message in score_by_id.items()],
        unmatched_lines,
        unknown_item_ids,
    )


def build_feedback_input(
    current_rewrite: dict[str, Any],
    checklist: dict[str, Any],
    experience: dict[str, Any],
    style_id: str,
    user_feedback: list[dict[str, Any]],
    score_feedback_text: str,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """현재 결과와 두 의견을 받아 feedback_input 객체와 연결 실패 줄을 돌려준다."""
    attempt = current_rewrite.get("attempt")
    if attempt == 1:
        initial = deepcopy(current_rewrite)
        if "revised_cv" not in initial:
            initial["revised_cv"] = [{
                "style": initial.get("style_id", style_id),
                "sentences": initial.get("sentences", []),
            }]
        payload = prepare_feedback_input(initial, checklist, experience, style_id)
    else:
        payload = deepcopy(current_rewrite)
        current_sentences = payload.pop("sentences", [])
        payload.pop("style", None)
        payload["style_id"] = style_id
        payload["revised_cv"] = [{
            "attempt": attempt,
            "style": style_id,
            "sentences": current_sentences,
        }]
        payload["user_feedback"] = [
            {"item_id": item["id"], "given": False, "text": None}
            for item in checklist["items"]
        ]
        payload["score_feedback"] = []
        validate_feedback_input(payload)

    experience_ids = {
        entry["item_id"] for entry in experience.get("experiences", [])
    }
    submitted = {entry["item_id"]: entry for entry in user_feedback}
    payload["user_feedback"] = [
        {
            "item_id": item["id"],
            "given": bool(submitted.get(item["id"], {}).get("given"))
            if item["id"] in experience_ids else False,
            "text": submitted.get(item["id"], {}).get("text")
            if item["id"] in experience_ids and submitted.get(item["id"], {}).get("given") else None,
        }
        for item in checklist["items"]
    ]

    item_ids = {item["id"] for item in checklist["items"]}
    parsed_score_feedback, unmatched_lines, unknown_item_ids = parse_score_feedback(
        score_feedback_text, item_ids
    )
    payload["score_feedback"] = [
        entry for entry in parsed_score_feedback if entry["item_id"] in experience_ids
    ]
    validate_feedback_input(payload)
    return payload, unmatched_lines, unknown_item_ids


def has_rewrite_feedback(payload: dict[str, Any]) -> bool:
    """루프 입력을 받아 경험이 있는 항목에 전달할 의견이 있는지 돌려준다."""
    experienced_item_ids = {
        entry["item_id"]
        for entry in payload.get("experiences", [])
        if isinstance(entry, dict) and isinstance(entry.get("item_id"), str)
    }
    user_given = any(
        entry.get("given") and isinstance(entry.get("text"), str) and entry["text"].strip()
        and entry.get("item_id") in experienced_item_ids
        for entry in payload.get("user_feedback", [])
    )
    scored = any(
        isinstance(entry.get("text"), str) and entry["text"].strip()
        and entry.get("item_id") in experienced_item_ids
        for entry in payload.get("score_feedback", [])
    )
    return user_given or scored
