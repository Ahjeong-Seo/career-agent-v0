"""화면의 채점 피드백을 루프의 항목별 재작성 입력으로 바꾼다."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from loop.feedback_loop import prepare_feedback_input
from loop.retry_rewrite import validate_feedback_input


_ITEM_FEEDBACK_LINE = re.compile(r"^(req-\d+):[ \t]*(.*)$")


def build_feedback_input(
    current_rewrite: dict[str, Any],
    checklist: dict[str, Any],
    experience: dict[str, Any],
    style_id: str,
    feedback_text: str,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """현재 rewrite·체크리스트·경험·채점 피드백을 받아 다음 루프 입력과 미연결 줄을 돌려준다."""
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
        payload["user_feedback"] = [{item["id"]: "" for item in checklist["items"]}]
        validate_feedback_input(payload)

    item_ids = {item["id"] for item in checklist["items"]}
    feedback_by_id = payload["user_feedback"][0]
    unmatched_lines: list[str] = []
    unknown_item_ids: list[str] = []

    for line in feedback_text.splitlines():
        if not line.strip():
            continue
        match = _ITEM_FEEDBACK_LINE.fullmatch(line)
        if match is None:
            unmatched_lines.append(line)
            continue
        item_id, message = match.groups()
        if item_id not in item_ids:
            unmatched_lines.append(line)
            if item_id not in unknown_item_ids:
                unknown_item_ids.append(item_id)
            continue
        message = message.strip()
        if feedback_by_id[item_id] and message:
            feedback_by_id[item_id] += "\n" + message
        elif message:
            feedback_by_id[item_id] = message

    return payload, unmatched_lines, unknown_item_ids


def has_rewrite_feedback(payload: dict[str, Any]) -> bool:
    """루프 입력을 받아 경험이 있는 항목에 전달할 의견이 있는지 돌려준다."""
    experienced_item_ids = {
        entry["item_id"]
        for entry in payload.get("experiences", [])
        if isinstance(entry, dict) and isinstance(entry.get("item_id"), str)
    }
    has_mapped_feedback = any(
        isinstance(message, str) and message.strip() and item_id in experienced_item_ids
        for group in payload.get("user_feedback", [])
        for item_id, message in group.items()
    )
    return has_mapped_feedback
