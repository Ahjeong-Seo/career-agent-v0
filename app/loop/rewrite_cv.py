"""선택한 스타일의 CV를 재작성해 revised_cv.json 형태로 반환한다."""

from copy import deepcopy
import json
import sys
from typing import Any

from app.constants import ROOT, SENTENCE_SCHEMA
from app.loop.call_llm import call_llm
from app.loop.revise_cv import safe_sentences


PROMPT_VERSION = "loop/rewrite_cv_v1"
REWRITE_SCHEMA = deepcopy(SENTENCE_SCHEMA)
_sentence_schema = REWRITE_SCHEMA["properties"]["sentences"]["items"]
_sentence_schema["properties"]["llm_opinion"] = {"type": "string"}
_sentence_schema["required"].append("llm_opinion")


def rewrite_cv(revisedResult: dict) -> dict[str, Any]:
    """체크리스트·경험·선택한 CV를 받아 재작성한 CV를 예시 JSON 형태로 돌려준다."""
    case = revisedResult["case"]
    answers = revisedResult["answers"]
    current = revisedResult["revised_cv"]
    # revise_cv의 기존 반환값과 revised_cv.json 형태를 모두 입력으로 받는다.
    if isinstance(current, list):
        selected_style = revisedResult.get("style_id")
        candidates = [entry for entry in current if entry["style_id"] == selected_style]
        if len(candidates) != 1:
            raise ValueError("재작성할 스타일 하나를 style_id로 선택해 주세요.")
        current = candidates[0]
    attempt = int(current["attempt"])
    if not 1 <= attempt < 4:
        raise ValueError("첫 생성 후 재작성은 최대 3번까지만 가능합니다.")
    style = current.get("style_id", current.get("style"))
    if not isinstance(style, str) or not style:
        raise ValueError("재작성할 스타일이 없습니다.")

    previous_sentences = current["sentences"]
    user_feedback = getUserFeedback(previous_sentences)
    if any(answers.values()):
        response = call_llm(
            make_prompt(case, answers, attempt, style, previous_sentences, user_feedback),
            REWRITE_SCHEMA,
        )
        sentences = safe_sentences(response, case["items"], answers)
        by_id = {entry["item_id"]: entry for entry in response["sentences"]}
        for sentence in sentences:
            generated = by_id[sentence["item_id"]]
            opinion = generated.get("llm_opinion")
            if not isinstance(opinion, str):
                raise ValueError("Codex 답변에 llm_opinion 문자열이 없습니다.")
            sentence["llm_opinion"] = (
                opinion if sentence["text"] == generated["text"].strip()
                else "원문의 사실을 유지하기 위해 원문을 사용했습니다."
            )
    else:
        sentences = []

    return {
        "case_id": case["case_id"],
        "prompt_version": PROMPT_VERSION,
        "attempt": attempt + 1,
        "style_id": style,
        "revised_cv": [
            {"attempt": attempt + 1, "style_id": style, "sentences": sentences}
        ],
    }


def make_prompt(
    case: dict[str, Any], answers: dict[str, str], attempt: int, style: str,
    revised_cv: list[dict[str, Any]], user_feedback: dict[str, str],
) -> str:
    """요구사항·원문·이전 문장·피드백을 받아 재작성용 프롬프트를 돌려준다."""
    instructions = (ROOT / "prompts" / f"{PROMPT_VERSION}.md").read_text(encoding="utf-8")
    entries = {
        "case_id": case["case_id"],
        "prompt_version": PROMPT_VERSION,
        "attempt": attempt + 1,
        "style_id": style,
        "requirements": {
            "job_title": case["job_title"],
            "company_values": case["company_values"],
            "items": case["items"],
        },
        "experiences": [
            {"item_id": item["id"], "text": answers[item["id"]]}
            for item in case["items"] if answers[item["id"]]
        ],
        "user_feedback": [user_feedback],
        "old_revised_cv": [
            {"attempt": attempt, "style_id": style, "sentences": revised_cv}
        ],
    }
    return (
        f"프롬프트 버전: {PROMPT_VERSION}\n스타일: {style}\n{instructions}\n"
        f"입력 데이터: {json.dumps(entries, ensure_ascii=False)}"
    )


def getUserFeedback(revised_cv: list[dict[str, Any]]) -> dict[str, str]:
    """이전 CV 문장 목록을 받아 항목별로 입력받은 사용자 피드백을 돌려준다."""
    user_feedback: dict[str, str] = {}
    for item in revised_cv:
        while True:
            print(
                f"[{item['item_id']}] {item['source']}\n-> {item['text']}\n"
                "피드백을 입력해주세요 : ",
                end="", file=sys.stderr, flush=True,
            )
            feedback_text = sys.stdin.readline()
            if feedback_text == "":
                raise EOFError("모든 항목의 피드백을 입력하기 전에 입력이 종료되었습니다.")
            try:
                feedback_text.encode("utf-8")
            except UnicodeEncodeError:
                print("입력 인코딩 오류입니다. UTF-8로 다시 입력해 주세요.", file=sys.stderr)
                continue
            user_feedback[item["item_id"]] = feedback_text.strip()
            break
    return user_feedback
