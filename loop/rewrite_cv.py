"""선택한 스타일의 CV를 재작성해 revised_cv.json 형태로 반환한다."""

from __future__ import annotations

from copy import deepcopy
import json
import sys
from typing import Any

from app.constants import ROOT, SENTENCE_SCHEMA
from loop.call_llm import call_llm
from loop.revise_cv import safe_sentences
from loop.user_input import clean_terminal_input


PROMPT_VERSION = "loop/rewrite_cv_v2"
REWRITE_SCHEMA = deepcopy(SENTENCE_SCHEMA)
_sentence_schema = REWRITE_SCHEMA["properties"]["sentences"]["items"]
_sentence_schema["properties"]["llm_opinion"] = {"type": "string"}
_sentence_schema["required"].append("llm_opinion")


def rewrite_cv(
    revisedResult: dict, *, feedback: dict[str, str] | None = None,
    first_attempt: int = 0, max_attempt: int = 3,
) -> dict[str, Any]:
    """첫 문장·피드백·회차 범위를 받아 한 번 재작성한 결과를 돌려준다."""
    if "case" in revisedResult and "answers" in revisedResult:
        case = revisedResult["case"]
        answers = revisedResult["answers"]
    else:
        requirements = revisedResult["requirements"]
        case = {"case_id": revisedResult["case_id"], **requirements}
        answers = {item["id"]: "" for item in case["items"]}
        answers.update(
            {entry["item_id"]: entry["text"] for entry in revisedResult["experiences"]}
        )
    current = revisedResult["revised_cv"]
    # revise_cv의 기존 반환값과 revised_cv.json 형태를 모두 입력으로 받는다.
    if isinstance(current, list):
        selected_style = revisedResult.get("style_id")
        candidates = [entry for entry in current if entry["style_id"] == selected_style]
        if len(candidates) != 1:
            raise ValueError("재작성할 스타일 하나를 style_id로 선택해 주세요.")
        current = candidates[0]
    attempt = int(current["attempt"])
    if not 0 <= attempt < max_attempt:
        raise ValueError("첫 생성 후 재작성은 최대 3번까지만 가능합니다.")
    style = current.get("style_id", current.get("style"))
    if not isinstance(style, str) or not style:
        raise ValueError("재작성할 스타일이 없습니다.")

    previous_sentences = current["sentences"]
    if feedback is None and attempt == first_attempt:
        answers.update(ask_missing_experiences(previous_sentences))
    new_feedback = getUserFeedback(previous_sentences) if feedback is None else feedback
    feedback_history = revisedResult.get("user_feedback", []) + [new_feedback]
    old_revised_cv = revisedResult.get("old_revised_cv", []) + [
        {"attempt": attempt, "style_id": style, "sentences": previous_sentences}
    ]
    if any(answers.values()):
        print("피드백을 반영한 결과를 생성 중입니다. 잠시 기다려 주세요...", file=sys.stderr, flush=True)
        response = call_llm(
            make_prompt(case, answers, attempt, style, old_revised_cv, feedback_history),
            REWRITE_SCHEMA,
        )
        sentences = safe_sentences(response, case["items"], answers)
        by_id = {entry["item_id"]: entry for entry in response["sentences"]}
        for sentence in sentences:
            if not sentence["source"]:
                # 경험이 없는 항목은 LLM 답변에 내용이 있어도 빈칸으로 유지한다.
                continue
            generated = by_id[sentence["item_id"]]
            opinion = generated.get("llm_opinion")
            if not isinstance(opinion, str):
                raise ValueError("Codex 답변에 llm_opinion 문자열이 없습니다.")
            sentence["llm_opinion"] = (
                opinion if sentence["text"] == generated["text"].strip()
                else "원문의 사실을 유지하기 위해 원문을 사용했습니다."
            )
    else:
        sentences = [
            {"item_id": item["id"], "source": "", "text": "", "llm_opinion": "", "user_feedback": ""}
            for item in case["items"]
        ]
    for sentence in sentences:
        sentence["user_feedback"] = new_feedback.get(sentence["item_id"], "")

    return {
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
        "user_feedback": feedback_history,
        "old_revised_cv": old_revised_cv,
        "revised_cv": [
            {"attempt": attempt + 1, "style_id": style, "sentences": sentences}
        ],
    }


def make_prompt(
    case: dict[str, Any], answers: dict[str, str], attempt: int, style: str,
    old_revised_cv: list[dict[str, Any]], user_feedback: list[dict[str, str]],
) -> str:
    """요구사항·원문·이전 문장 이력·피드백 이력을 받아 프롬프트를 돌려준다."""
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
        "user_feedback": user_feedback,
        "old_revised_cv": old_revised_cv,
    }
    return (
        f"프롬프트 버전: {PROMPT_VERSION}\n스타일: {style}\n{instructions}\n"
        f"입력 데이터: {json.dumps(entries, ensure_ascii=False)}"
    )


def getUserFeedback(revised_cv: list[dict[str, Any]]) -> dict[str, str]:
    """이전 CV 문장 목록을 받아 항목별로 입력받은 사용자 피드백을 돌려준다."""
    user_feedback: dict[str, str] = {}
    for item in revised_cv:
        if not item["source"]:
            continue
        while True:
            print(
                f"[{item['item_id']}] {item['source']}\n-> {item['text']}\n"
                "피드백을 입력해주세요 : ",
                end="", file=sys.stderr, flush=True,
            )
            feedback_text = sys.stdin.readline()
            if feedback_text == "":
                raise EOFError("모든 항목의 피드백을 입력하기 전에 입력이 종료되었습니다.")
            feedback_text = clean_terminal_input(feedback_text)
            try:
                feedback_text.encode("utf-8")
            except UnicodeEncodeError:
                print("입력 인코딩 오류입니다. UTF-8로 다시 입력해 주세요.", file=sys.stderr)
                continue
            user_feedback[item["item_id"]] = feedback_text.strip()
            break
    return user_feedback


def ask_missing_experiences(revised_cv: list[dict[str, Any]]) -> dict[str, str]:
    """첫 첨삭의 빈 경험 항목을 받아 다시 확인하고 새로 입력한 원문만 돌려준다."""
    added: dict[str, str] = {}
    for item in revised_cv:
        if item["source"]:
            continue
        print(
            f"[{item['item_id']}] 관련 경험이 정말 없나요? "
            "있다면 실제 경험을 입력하고, 없으면 Enter를 눌러 주세요: ",
            end="", file=sys.stderr, flush=True,
        )
        answer = sys.stdin.readline()
        if answer == "":
            raise EOFError("빈 경험 항목을 확인하기 전에 입력이 종료되었습니다.")
        answer = clean_terminal_input(answer.rstrip("\r\n"))
        if answer.strip():
            added[item["item_id"]] = answer
    return added
