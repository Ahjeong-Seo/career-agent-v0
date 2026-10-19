
from typing import Any
import sys
from app.loop.call_llm import *
from app.loop.revise_cv import safe_sentences
from app.constants import ROOT, REWRITE_PROMPT_VERSION


def rewrite_cv(revisedResult: dict) -> dict[str, Any]:
    print(revisedResult)
    case = revisedResult['case']
    answers = revisedResult['answers']
    attempt = int(revisedResult['revised_cv']['attempt'])
    revised_cv = revisedResult['revised_cv']['sentences']
    style = revisedResult['revised_cv']['style']
    user_feedback = []

    if(int(revisedResult['revised_cv']['attempt']) > 5):
        rewrite_cv['error_msg'] = "5회 이상 계속할 수 없습니다."
        return rewrite_cv
    else:
        print(revised_cv)
        user_feedback = getUserFeedback(revised_cv)

        response = make_prompt(case, answers, attempt, style, revised_cv, user_feedback)
        '''
        started = time.monotonic()

        try:
            response = call_llm(make_prompt(case, answers, style, user_feedback), SENTENCE_SCHEMA)
            sentences = safe_sentences(response, case["items"], answers)
        except (OSError, ValueError, RuntimeError):
            print(f"[{index}/{len(STYLES)}] '{style}' 작성 실패", file=sys.stderr)
            raise
        '''
    #return rewrite_cv
    return response

def make_prompt( case: dict[str, Any], answers: dict[str, str], attempt: int, style: str, revised_cv: dict[str, Any],
    user_feedback: dict[str, str]) -> str:

    """체크리스트와 경험·스타일을 받아 Codex에 보낼 프롬프트를 돌려준다."""
    instructions = (ROOT / "prompts" / f"{REWRITE_PROMPT_VERSION}.md").read_text(
        encoding="utf-8"
    )
    entries = {}

    entries['case_id'] = case['case_id']
    entries['prompt_version'] = REWRITE_PROMPT_VERSION
    entries['attempt'] = attempt+1
    entries['style'] = style
    entries['requirements'] = {
        "job_title" : case['job_title'],
        "company_values": case ['company_values'],
        "items" : case['items']
    },
    entries['experiences'] = answers
    entries['user_feedback'] = user_feedback

    return (
        f"프롬프트 버전: {REWRITE_PROMPT_VERSION}\n"
        f"스타일: {style}\n{instructions}\n"
        f"입력 데이터: {json.dumps(entries, ensure_ascii=False, default=str)}"
    )

def getUserFeedback(revised_cv: dict) -> dict[str, Any]:
    user_feedback: dict[str, str] = {}
    for item in revised_cv:
        while True:
            print(
                f"[{item['item_id']}] {item['source']}\n-> {item['text']})\n"
                "피드백을 입력해주세요 : ",
                end="",
                file=sys.stderr,
                flush=True,
            )
            feedback_text = sys.stdin.readline()
            if feedback_text == "":
                raise EOFError("모든 항목의 피드백을 입력하기 전에 입력이 종료되었습니다.")
            try:
                feedback_text.encode("utf-8")
            except UnicodeEncodeError:
                print(
                    "입력 인코딩 오류입니다. 이 항목을 다시 입력해 주세요. "
                    "터미널 문자 인코딩도 UTF-8인지 확인해 주세요.",
                    file=sys.stderr,
                )
                continue
            user_feedback[item["item_id"]] = feedback_text.strip()
            break
    return user_feedback

