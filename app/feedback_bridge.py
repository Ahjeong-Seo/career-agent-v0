"""화면의 채점 피드백을 루프의 항목별 재작성 입력으로 바꾼다."""

from __future__ import annotations

import re
from typing import Any

from loop.feedback_loop import prepare_feedback_input


_ITEM_FEEDBACK_LINE = re.compile(r"^(req-\d+):[ \t]*(.*)$")


def build_feedback_input(
    initial: dict[str, Any],
    checklist: dict[str, Any],
    experience: dict[str, Any],
    style_id: str,
    feedback_text: str,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """첫 첨삭·체크리스트·경험·채점 피드백을 받아 루프 입력과 미연결 줄·알 수 없는 ID를 돌려준다."""
    payload = prepare_feedback_input(initial, checklist, experience, style_id)
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
