"""4단계 스타일 고르기 화면: 첫 생성 3종을 나란히 보여 주고, 이어서 다듬을 스타일 하나를 고른다.

app/main.py가 2단계 다음에 render_style_step()을 부른다. 이 화면만 따로 띄울 수도 있다:
streamlit run app/style_select.py
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
# 3단계 경험 입력 화면이 확정한 experience를 넣어 두는 세션 키
EXPERIENCE_KEY = "experience_confirmed"
# 임시: 루프 PR #12의 samples/rewrite.sample.json(세 스타일 묶음) 사본. #12가 머지되면 이 파일은 지운다.
PREVIEW_REWRITE_PATH = ROOT / "app" / "preview_rewrite.sample.json"
# AGENTS.md 허용값: 스타일 이름 / style_id. 화면에도 이 순서로 보여 준다.
STYLE_LABELS = {
    "achievement": "성과 강조형",
    "keyword": "키워드 맞춤형",
    "concise": "간결형",
}
STYLE_IDS = {label: style_id for style_id, label in STYLE_LABELS.items()}

# score.json issues의 code를 화면에 보일 이름으로 바꾼다. 모르는 code는 "품질 경고"로 센다.
ISSUE_LABELS = {
    "UNGROUNDED_NUMBER": "지어낸 숫자",
    "GENERIC_PHRASE": "AI 표현",
    "TEXT_WITHOUT_EXPERIENCE": "경험 없는 문장",
}



SELECTED_STYLE_KEY = "selected_style_id"
SAMPLE_EXPERIENCE_KEY = "style_step_sample_experience"
FIRST_ATTEMPT_CHECKS_KEY = "style_step_first_attempt_checks"
# 분석한 케이스에서 만든 첫 생성 결과: {입력 서명: 루프 첫 생성 결과}. 경험을 다시 확정하면 서명이 바뀌어 새로 만든다.
FIRST_REWRITE_KEY = "style_step_first_rewrites"


def normalize_style_id(value: Any) -> str | None:
    """스타일 값(영문 style_id 또는 한글 스타일 이름)을 받아 style_id를 돌려준다. 모르는 값이면 None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value in STYLE_LABELS:
        return value
    return STYLE_IDS.get(value)


def style_label(style_id: Any) -> str:
    """style_id를 받아 화면에 보일 한글 이름을 돌려준다. 모르는 값은 그대로 글자로 돌려준다."""
    return STYLE_LABELS.get(style_id, str(style_id))


def rewrites_by_style(loop_output: Any) -> list[dict[str, Any]]:
    """루프 결과 JSON 하나를 받아 스타일별 rewrite 목록으로 돌려준다.

    - 루프팀 모양(PR #12): `revised_cv` 안에 스타일 후보가 묶여 있으면 스타일마다 하나로 나눈다.
    - 스타일 하나짜리(`sentences`가 바로 있음)면 그 하나만 목록에 담는다.
    나눈 rewrite에는 채점과 짝을 맞출 수 있게 `case_id`, `style_id`, `attempt`를 채운다.
    누가 나눌지는 11/7에 루프팀과 정한다. 정해질 때까지 화면이 나눈다.
    """
    if not isinstance(loop_output, dict):
        raise ValueError("첨삭 결과는 JSON 객체여야 합니다.")
    candidates = loop_output.get("revised_cv")
    if candidates is None:
        candidates = [loop_output]
    if not isinstance(candidates, list):
        raise ValueError("첨삭 결과의 revised_cv는 목록이어야 합니다.")

    shared = {
        key: deepcopy(value)
        for key, value in loop_output.items()
        if key not in ("revised_cv", "sentences", "style", "style_id")
    }
    rewrites = []
    for number, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            raise ValueError(f"첨삭 결과의 {number}번째 스타일 후보가 JSON 객체가 아닙니다.")
        raw_style = candidate.get("style_id", candidate.get("style"))
        rewrite = deepcopy(shared)
        rewrite.update(deepcopy(candidate))
        rewrite["style_id"] = normalize_style_id(raw_style) or raw_style
        rewrites.append(rewrite)
    return rewrites


def check_first_attempt(
    checklist: dict[str, Any], experience: dict[str, Any], rewrites: list[dict[str, Any]]
) -> list[str]:
    """확정 체크리스트, 경험 입력, 스타일별 rewrite를 받아 첫 생성 3종이 맞는지 검사한다.

    틀린 곳을 한국어 문장 목록으로 돌려준다. 빈 목록이면 통과다.
    AGENTS.md에서 코드로 맞춰 보라고 한 것만 본다: 스타일 구성, case_id·attempt 불일치,
    체크리스트에 없는 item_id, 같은 항목 중복, source와 경험 원문(text) 불일치.
    """
    errors = []
    case_id = checklist.get("case_id")
    if experience.get("case_id") != case_id:
        errors.append(f"경험 입력의 case_id({experience.get('case_id')})가 체크리스트({case_id})와 다릅니다.")

    item_ids = {item.get("id") for item in checklist.get("items", []) if isinstance(item, dict)}
    sources = {
        row.get("item_id"): row.get("text")
        for row in experience.get("experiences", [])
        if isinstance(row, dict)
    }

    styles = [rewrite.get("style_id") for rewrite in rewrites]
    for style in styles:
        if style not in STYLE_LABELS:
            errors.append(f"알 수 없는 스타일입니다: {style!r}. achievement, keyword, concise 중 하나여야 합니다.")
    for style_id in STYLE_LABELS:
        if styles.count(style_id) > 1:
            errors.append(f"{style_label(style_id)} 결과가 {styles.count(style_id)}개 있습니다. 스타일마다 하나여야 합니다.")
    missing = [style_label(style_id) for style_id in STYLE_LABELS if style_id not in styles]
    if missing:
        errors.append(f"첫 생성에는 세 스타일이 모두 필요합니다. 빠진 스타일: {', '.join(missing)}")

    for rewrite in rewrites:
        name = style_label(rewrite.get("style_id"))
        if rewrite.get("case_id") != case_id:
            errors.append(f"{name}: case_id({rewrite.get('case_id')})가 체크리스트({case_id})와 다릅니다.")
        if rewrite.get("attempt") != 1:
            errors.append(f"{name}: 첫 생성인데 attempt가 {rewrite.get('attempt')}입니다. 1이어야 합니다.")
        sentences = rewrite.get("sentences")
        if not isinstance(sentences, list):
            errors.append(f"{name}: sentences가 목록이 아닙니다.")
            continue
        seen = set()
        for sentence in sentences:
            item_id = sentence.get("item_id") if isinstance(sentence, dict) else None
            if item_id not in item_ids:
                errors.append(f"{name}: 체크리스트에 없는 item_id입니다 ({item_id}).")
                continue
            if item_id in seen:
                errors.append(f"{name}: {item_id} 문장이 두 번 있습니다.")
                continue
            seen.add(item_id)
            if item_id in sources and sentence.get("source") != sources[item_id]:
                errors.append(f"{name} {item_id}: source가 경험 입력 원문과 다릅니다.")
            elif item_id not in sources and sentence.get("source") not in (None, ""):
                errors.append(f"{name} {item_id}: 경험 입력에 없는 source가 있습니다.")
    return errors


def pair_scores(
    rewrites: list[dict[str, Any]], scores: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """스타일별 rewrite 목록과 score 목록을 받아 case_id + style_id + attempt가 같은 것끼리 짝짓는다.

    {style_id: score}와 오류 문장 목록을 돌려준다. 짝이 없는 스타일은 오류로 알린다.
    """
    errors = []
    by_key = {}
    for score in scores:
        key = (score.get("case_id"), normalize_style_id(score.get("style_id")), score.get("attempt"))
        if key in by_key:
            errors.append(f"{style_label(key[1])} attempt {key[2]}의 score가 두 개 있습니다.")
        by_key[key] = score

    paired = {}
    for rewrite in rewrites:
        key = (rewrite.get("case_id"), rewrite.get("style_id"), rewrite.get("attempt"))
        score = by_key.get(key)
        if score is None:
            errors.append(f"{style_label(key[1])}: 짝이 맞는 score가 없습니다 (case_id·style_id·attempt를 확인해 주세요).")
        else:
            paired[key[1]] = score
    return paired, errors


def score_passed(score: dict[str, Any]) -> bool | None:
    """score 하나를 받아 계약의 passed 값을 돌려준다. boolean이 아니면 None을 반환한다."""
    if isinstance(score.get("passed"), bool):
        return score["passed"]
    return None


def style_summary(
    checklist: dict[str, Any], experience: dict[str, Any], score: dict[str, Any]
) -> dict[str, Any]:
    """체크리스트, 경험 입력, 한 스타일의 score를 받아 스타일 카드에 보일 요약을 돌려준다.

    - required_met / required_total: 경험을 적은 필수 항목 중 충족 수 / 전체 수 (AGENTS.md 통과 계산 대상)
    - issues: {"지어낸 숫자": 0, "AI 표현": 1, ...} 이름별 경고 개수
    - passed: score_passed()의 결과
    """
    entered = {row.get("item_id") for row in experience.get("experiences", []) if isinstance(row, dict)}
    required = [
        item.get("id")
        for item in checklist.get("items", [])
        if item.get("level") == "필수" and item.get("type") != "기타" and item.get("id") in entered
    ]
    statuses = {row.get("item_id"): row.get("status") for row in score.get("items", []) if isinstance(row, dict)}
    issues = {
        "지어낸 숫자": len(score.get("made_up_numbers", [])),
        "AI 표현": len(score.get("ai_phrases", [])),
    }
    return {
        "required_met": sum(1 for item_id in required if statuses.get(item_id) == "충족"),
        "required_total": len(required),
        "issues": issues,
        "passed": score_passed(score),
    }


def render_style_select(
    checklist: dict[str, Any],
    experience: dict[str, Any],
    rewrites: list[dict[str, Any]],
    scores: list[dict[str, Any]] | None = None,
    heading: bool = True,
    validate_first_attempt: bool = True,
) -> str | None:
    """4단계 화면을 그린다.

    확정 체크리스트, 경험 입력, 첫 생성 스타일별 rewrite 3개, (있으면) 짝이 되는 score 3개를 받는다.
    heading이 False면 제목을 그리지 않는다(부르는 쪽이 이미 그렸을 때).
    validate_first_attempt가 False면 부르는 쪽에서 이미 끝낸 검사를 반복하지 않는다.
    사용자가 "계속"을 누르면 고른 style_id를 세션에 넣고 돌려준다. 아직 안 눌렀으면 None.
    """
    if heading:
        st.header("4. 스타일 고르기")
    st.caption("같은 경험으로 세 스타일을 써 봤어요. 의견은 고른 스타일에만 남길 수 있어요.")

    errors = check_first_attempt(checklist, experience, rewrites) if validate_first_attempt else []
    paired: dict[str, dict[str, Any]] = {}
    if scores is not None:
        paired, pair_errors = pair_scores(rewrites, scores)
        errors += pair_errors
    if errors:
        for error in errors:
            st.error(error)
        st.warning("위 오류를 해결해야 스타일을 고를 수 있습니다.")
        st.session_state.pop(SELECTED_STYLE_KEY, None)
        return None
    if scores is None:
        st.info("채점 결과가 아직 연결되지 않아 문장만 비교합니다.")

    order = list(STYLE_LABELS)
    ordered = sorted(rewrites, key=lambda rewrite: order.index(rewrite["style_id"]))
    columns = st.columns(len(ordered))
    for column, rewrite in zip(columns, ordered):
        style_id = rewrite["style_id"]
        with column, st.container(border=True):
            _render_style_card(style_id, checklist, experience, paired.get(style_id))

    choice = st.radio(
        "어느 스타일로 이어 갈까요?",
        options=[rewrite["style_id"] for rewrite in ordered],
        format_func=style_label,
        horizontal=True,
        index=None,
        key="style_choice",
    )

    selected = st.session_state.get(SELECTED_STYLE_KEY)
    if selected is not None and selected != choice:
        # 계속을 누른 뒤 라디오를 바꾸면 고른 것을 풀고 다시 누르게 한다.
        st.session_state.pop(SELECTED_STYLE_KEY, None)
        selected = None
    _render_comparison(
        checklist,
        experience,
        ordered,
        paired,
        choice,
    )

    button_label = f"{style_label(choice)}으로 계속" if choice else "스타일을 골라 주세요"
    if st.button(button_label, type="primary", disabled=choice is None, key="confirm_style"):
        st.session_state[SELECTED_STYLE_KEY] = choice
        selected = choice
    if selected:
        st.success(f"{style_label(selected)}으로 이어서 다듬어요. 다음 attempt부터 이 스타일만 씁니다.")
    st.caption("통과하면 바로 최종 결과로 가고, 아니면 채점 feedback을 받아 최대 3번 더 써요.")
    return selected


def _render_style_card(
    style_id: str, checklist: dict[str, Any], experience: dict[str, Any], score: dict[str, Any] | None
) -> None:
    """style_id와 (있으면) 그 스타일의 score를 받아 카드 한 장(이름, 필수 충족, 경고, 통과 여부)을 그린다."""
    st.markdown(f"**{style_label(style_id)}** `{style_id}`")
    if score is None:
        st.caption("채점 전")
        return
    summary = style_summary(checklist, experience, score)
    if summary["required_total"]:
        st.caption(f"필수 충족 {summary['required_met']} / {summary['required_total']}")
    else:
        st.caption("경험을 적은 필수 항목 없음")
    st.caption(" · ".join(f"{name} {count}개" for name, count in summary["issues"].items()))
    if summary["passed"] is True:
        st.markdown(":green-badge[통과]")
    elif summary["passed"] is False:
        st.markdown(":orange-badge[다시 쓰기 필요]")
    else:
        st.markdown(":gray-badge[통과 여부 없음]")


def _render_comparison(
    checklist: dict[str, Any],
    experience: dict[str, Any],
    rewrites: list[dict[str, Any]],
    scores: dict[str, dict[str, Any]],
    selected_style_id: str | None,
) -> None:
    """체크리스트 항목마다 경험 원문과 스타일별 첨삭 문장·판정·경고·고친 이유를 나란히 그린다."""
    st.subheader("항목별 문장 비교")
    sources = {
        row.get("item_id"): row.get("text")
        for row in experience.get("experiences", [])
        if isinstance(row, dict)
    }
    sentences = {
        rewrite["style_id"]: {
            sentence.get("item_id"): sentence
            for sentence in rewrite.get("sentences", [])
            if isinstance(sentence, dict)
        }
        for rewrite in rewrites
    }
    for item in checklist.get("items", []):
        item_id = item.get("id")
        st.markdown(f"**{item_id} · {item.get('level')} · {item.get('text')}**")
        if item_id not in sources:
            st.caption("경험 없음 · 문장을 만들지 않는 항목이에요. 최종 결과에 보완할 경험으로 남아요.")
            for rewrite in rewrites:
                text = sentences.get(rewrite["style_id"], {}).get(item_id, {}).get("text")
                if isinstance(text, str) and text.strip():
                    st.warning(f"{style_label(rewrite['style_id'])}: 경험이 없는 항목인데 문장이 있습니다. — {text}")
            st.divider()
            continue

        st.caption(f"원문: {sources[item_id]}")
        columns = st.columns(len(rewrites))
        for column, rewrite in zip(columns, rewrites):
            style_id = rewrite["style_id"]
            sentence = sentences[style_id].get(item_id, {})
            score = scores.get(style_id)
            with column:
                st.markdown(f"**{style_label(style_id)}**")
                st.write(sentence.get("text") or "첨삭 문장 없음")
                if score is not None:
                    item_score = next(
                        (row for row in score.get("items", []) if row.get("item_id") == item_id),
                        None,
                    )
                    if item_score is not None:
                        st.caption(f"{item_score.get('status')} · {item_score.get('reason', '')}")
                    for number in score.get("made_up_numbers", []):
                        if number.get("item_id") == item_id:
                            st.warning(f"지어낸 숫자: {number.get('number')}")
                    for phrase in score.get("ai_phrases", []):
                        if phrase.get("item_id") == item_id:
                            st.warning(f"AI 표현: {phrase.get('phrase')}")
                if sentence.get("llm_opinion"):
                    with st.expander("고친 이유"):
                        st.write(sentence["llm_opinion"])
        st.divider()

    for rewrite in rewrites:
        style_id = rewrite["style_id"]
        score = scores.get(style_id)
        if score and (
            score.get("feedback")
            or (style_id == selected_style_id and score.get("passed") is False)
        ):
            with st.expander(f"{style_label(style_id)} 채점 의견"):
                st.code(score["feedback"], language=None)


def load_sample_checklist() -> dict[str, Any]:
    """인수 없이 저장소 체크리스트 샘플을 읽어 돌려준다. 미리보기에서 2단계를 건너뛸 때 쓴다."""
    return json.loads((SAMPLES / "checklist.sample.json").read_text(encoding="utf-8"))


def load_sample_experience() -> dict[str, Any]:
    """화면 미리보기용 경험 샘플을 읽어 experience 스키마 객체로 반환한다."""
    experience = json.loads((SAMPLES / "experience.sample.json").read_text(encoding="utf-8"))
    experience.setdefault("schema_version", 1)
    return experience


def _input_signature(checklist: dict[str, Any], experience: dict[str, Any]) -> str:
    """체크리스트와 경험 근거를 받아 결과 이력에 사용할 SHA-256 서명을 반환한다."""
    payload = json.dumps({"checklist": checklist, "experience": experience}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save_attempt_result(
    checklist: dict[str, Any],
    experience: dict[str, Any],
    rewrite: dict[str, Any],
    score: dict[str, Any],
    finalize: bool = False,
) -> None:
    """체크리스트·경험·rewrite·score를 받아 세션 이력에 저장하고, finalize면 최종 차수를 기록한다."""
    history = st.session_state.setdefault("rewrite_score_history", [])
    signature = _input_signature(checklist, experience)
    entry = {
        "input_signature": signature,
        "style_id": rewrite["style_id"],
        "attempt": rewrite["attempt"],
        "rewrite": deepcopy(rewrite),
        "score": deepcopy(score),
    }
    existing = next(
        (
            row
            for row in history
            if row.get("input_signature") == signature
            and row.get("style_id") == rewrite["style_id"]
            and row.get("attempt") == rewrite["attempt"]
        ),
        None,
    )
    if existing is None:
        history.append(entry)
    else:
        existing.update(entry)
    if finalize:
        saved_key = f"final_result_saved:{signature}:{rewrite['style_id']}"
        st.session_state[saved_key] = rewrite["attempt"]


def _render_score_detail(
    score: dict[str, Any],
) -> None:
    """score 계약 객체 하나를 받아 통과 여부·항목 판정·경고·feedback을 화면에 표시한다."""
    if score["passed"]:
        st.success(f"{score['attempt']}차 채점을 통과했습니다.")
    else:
        st.warning(f"{score['attempt']}차 결과에 확인이 필요한 항목이 있습니다.")
    for item in score["items"]:
        st.write(f"**{item['item_id']} · {item['status']}** — {item['reason']}")
    for number in score["made_up_numbers"]:
        st.warning(f"{number['item_id']}: 지어낸 숫자 {number['number']}")
    for phrase in score["ai_phrases"]:
        st.warning(f"{phrase['item_id']}: AI 표현 {phrase['phrase']}")
    if score["feedback"]:
        with st.expander("채점 의견"):
            st.code(score["feedback"], language=None)


def _render_attempt_history(
    entries: list[dict[str, Any]], preview_rewrite: dict[str, Any] | None = None
) -> None:
    """차수 이력과 선택적 미리보기를 받아 화면에 문장·전달 feedback을 표시하고 아무것도 반환하지 않는다."""
    sentences_by_attempt: dict[int, list[dict[str, Any]]] = {}
    feedback_by_attempt: dict[int, set[str]] = {}

    def add_revision(
        revision: Any, fallback_attempt: int | None = None, replace: bool = False
    ) -> None:
        """재작성 차수 하나를 받아 문장과 그 문장에 전달한 feedback 이력에 등록한다."""
        if not isinstance(revision, dict):
            return
        attempt = revision.get("attempt", fallback_attempt)
        sentences = revision.get("sentences", [])
        if not isinstance(attempt, int) or not isinstance(sentences, list):
            return
        if replace:
            sentences_by_attempt[attempt] = sentences
        else:
            sentences_by_attempt.setdefault(attempt, sentences)
        for sentence in sentences:
            if not isinstance(sentence, dict):
                continue
            feedback = str(sentence.get("user_feedback") or "").strip()
            if feedback:
                label = f"{sentence.get('item_id', '')}: {feedback}"
                feedback_by_attempt.setdefault(attempt, set()).add(label)

    for entry in sorted(entries, key=lambda row: row.get("attempt", 0)):
        rewrite = entry.get("rewrite")
        if not isinstance(rewrite, dict):
            continue
        for old_attempt in rewrite.get("old_revised_cv", []):
            add_revision(old_attempt)
        add_revision(rewrite, fallback_attempt=entry.get("attempt"), replace=True)

    if preview_rewrite is not None:
        for old_attempt in preview_rewrite.get("old_revised_cv", []):
            add_revision(old_attempt)
        add_revision(preview_rewrite, replace=True)

    if not sentences_by_attempt:
        return
    with st.expander("재작성 이력", expanded=False):
        for attempt in sorted(sentences_by_attempt):
            title = "1차 문장" if attempt == 1 else f"{attempt}차 수정 문장"
            st.markdown(f"**{title}**")
            for sentence in sentences_by_attempt[attempt]:
                if isinstance(sentence, dict):
                    st.write(f"{sentence.get('item_id', '')} · {sentence.get('text') or '문장 없음'}")
            feedback = sorted(feedback_by_attempt.get(attempt, set()))
            if feedback:
                st.caption(f"{attempt}차 문장에 전달한 feedback: {' / '.join(feedback)}")


def _render_feedback_input_download(
    current_rewrite: dict[str, Any],
    checklist: dict[str, Any],
    experience: dict[str, Any],
    style_id: str,
    score_feedback_text: str,
    attempt: int,
) -> dict[str, Any] | None:
    """현재 rewrite와 채점 의견을 받아 항목별 사용자 입력과 JSON 다운로드를 표시한다."""
    from app.feedback_bridge import build_feedback_input, has_rewrite_feedback

    signature = _input_signature(checklist, experience)
    from app.feedback_bridge import parse_score_feedback

    parsed_score_feedback, _, _ = parse_score_feedback(
        score_feedback_text, {item["id"] for item in checklist["items"]}
    )
    score_by_id = {entry["item_id"]: entry["text"] for entry in parsed_score_feedback}
    user_feedback: list[dict[str, Any]] = []
    missing: list[str] = []
    for item in checklist["items"]:
        item_id = item["id"]
        has_experience = any(row["item_id"] == item_id for row in experience.get("experiences", []))
        if not has_experience:
            user_feedback.append({"item_id": item_id, "given": False, "text": None})
            continue
        state_key = f"feedback_no_need:{signature}:{style_id}:{attempt}:{item_id}"
        text_key = f"feedback_text:{signature}:{style_id}:{attempt}:{item_id}"
        st.markdown(f"**{item_id} · {item['text']}**")
        left, right = st.columns([3, 2])
        with left:
            no_need = st.checkbox("피드백 필요 없음", key=state_key)
            feedback_text = st.text_area(
                "사용자 의견",
                key=text_key,
                disabled=no_need,
                placeholder="이 항목의 문장을 어떻게 고칠지 적어 주세요.",
                label_visibility="collapsed",
            )
        with right:
            st.caption("채점 의견")
            st.write(score_by_id.get(item_id) or "채점 의견 없음")
        if no_need:
            user_feedback.append({"item_id": item_id, "given": False, "text": None})
        elif feedback_text.strip():
            user_feedback.append({"item_id": item_id, "given": True, "text": feedback_text})
        else:
            user_feedback.append({"item_id": item_id, "given": False, "text": None})
            missing.append(item_id)

    try:
        payload, unmatched, unknown_ids = build_feedback_input(
            current_rewrite, checklist, experience, style_id, user_feedback, score_feedback_text
        )
    except (KeyError, TypeError, ValueError) as error:
        st.error(f"feedback_input.json을 준비하지 못했습니다: {error}")
        return None

    if unknown_ids:
        st.warning(
            f"체크리스트에 없는 항목 ID({', '.join(unknown_ids)})는 연결하지 않았습니다. "
            "올바른 항목 피드백은 계속 전달됩니다."
        )
    if unmatched:
        st.warning(
            "형식이 맞지 않거나 연결할 수 없는 줄은 항목별 피드백으로 전달하지 않습니다. "
            "위 feedback 입력란에서 고칠 수 있습니다."
        )
    if missing:
        st.warning(f"의견을 입력하거나 '피드백 필요 없음'을 체크해 주세요: {', '.join(missing)}")
    if has_rewrite_feedback(payload):
        if st.button(
            f"의견 반영해 {attempt}차 재작성 및 채점",
            type="primary",
            key=f"run_feedback_rewrite_{style_id}_{attempt}",
            disabled=bool(missing),
        ):
            _run_feedback_rewrite(checklist, experience, payload, attempt)
        st.download_button(
            "확인하고 feedback_input.json 다운로드",
            data=json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            file_name="feedback_input.json",
            mime="application/json",
            key=f"feedback_input_download_{style_id}_{attempt}",
            on_click="ignore",
            disabled=bool(missing),
        )
    return payload


def _run_feedback_rewrite(
    checklist: dict[str, Any], experience: dict[str, Any], payload: dict[str, Any], attempt: int
) -> None:
    """확정한 체크리스트·경험·feedback_input·만들 차수를 받아 화면에서 바로 다시 쓰고 채점해 이력에 저장한다.

    통과하거나 4차면 최종 결과로 확정한다. 실패하면 오류를 보여 주고 이력은 바꾸지 않는다.
    """
    from app.feedback_bridge import run_feedback_rewrite

    with st.spinner(f"의견을 반영해 {attempt}차 문장을 만들고 채점하는 중이에요. 몇 분 걸릴 수 있어요."):
        result, errors = run_feedback_rewrite(payload)
    if result is None:
        for error in errors or ["알 수 없는 오류"]:
            st.error(f"다시 쓰지 못했습니다: {error}")
        return
    try:
        rewrites = rewrites_by_style(result)
        if len(rewrites) != 1:
            raise ValueError("재작성 결과에는 선택한 스타일 하나만 있어야 합니다.")
        scores = score_if_available(checklist, experience, rewrites)
        if scores is None:
            raise ValueError("채점 코드를 사용할 수 없습니다.")
    except (KeyError, TypeError, ValueError) as error:
        st.error(f"다시 쓴 결과를 채점하지 못했습니다: {error}")
        return
    score = scores[0]
    save_attempt_result(
        checklist,
        experience,
        rewrites[0],
        score,
        finalize=score.get("passed") is True or attempt == 4,
    )
    st.rerun()


def render_retry_scoring(
    checklist: dict[str, Any], experience: dict[str, Any], style_id: str, first_score: dict[str, Any]
) -> bool:
    """확정된 체크리스트·경험·선택 스타일·첫 score를 받아 재채점 화면을 그리고 완료 여부를 돌려준다."""
    st.header("5. 다시 쓴 문장 채점")
    st.caption("선택한 스타일의 다음 attempt rewrite JSON을 올려 주세요. 최대 attempt 4까지 채점할 수 있습니다.")
    signature = _input_signature(checklist, experience)
    history = st.session_state.setdefault("rewrite_score_history", [])
    entries = [
        entry for entry in history
        if entry["input_signature"] == signature and entry["style_id"] == style_id
    ]
    first_attempt = deepcopy(first_score)
    expected_attempt = max((entry["attempt"] for entry in entries), default=1) + 1
    saved_key = f"final_result_saved:{signature}:{style_id}"
    saved_attempt = st.session_state.get(saved_key)
    latest_attempt = max((entry["attempt"] for entry in entries), default=1)
    latest_entry = next((entry for entry in entries if entry["attempt"] == latest_attempt), None)
    latest_score = latest_entry["score"] if latest_entry is not None else first_attempt
    if saved_attempt is not None and any(entry["attempt"] == saved_attempt for entry in entries):
        _render_attempt_history(entries)
        st.success(f"{saved_attempt}차 결과로 최종 리포트를 생성합니다.")
        return True
    if latest_score.get("passed") is True:
        st.session_state[saved_key] = latest_attempt
        _render_attempt_history(entries)
        st.success(f"{latest_attempt}차 채점을 통과해 최종 결과로 확정했습니다.")
        return True
    st.subheader("1차 결과")
    _render_score_detail(first_attempt)
    for entry in entries:
        if entry["attempt"] == 1:
            continue
        st.subheader(f"{entry['attempt']}차 결과")
        _render_score_detail(entry["score"])

    if expected_attempt > 4:
        st.caption("재작성은 최대 4차까지 할 수 있습니다.")
        return True

    st.subheader(f"{latest_attempt}차 결과에 대한 의견")
    st.caption(
        "채점 의견은 자동으로 전달돼요. 항목마다 의견을 적거나 '피드백 필요 없음'을 체크한 뒤 "
        "다시 쓰세요. 이미 만든 rewrite JSON이 있으면 아래에서 올려 채점할 수도 있어요."
    )

    if latest_entry is not None and expected_attempt <= 4:
        from app.feedback_bridge import has_rewrite_feedback

        feedback_payload = _render_feedback_input_download(
            latest_entry["rewrite"], checklist, experience, style_id,
            str(latest_score.get("feedback", "")), expected_attempt
        )
        if feedback_payload is not None and not has_rewrite_feedback(feedback_payload):
            experienced = {row["item_id"] for row in experience.get("experiences", [])}
            incomplete = [
                item["id"] for item in checklist["items"]
                if item["id"] in experienced
                and not st.session_state.get(
                    f"feedback_no_need:{signature}:{style_id}:{expected_attempt}:{item['id']}", False
                )
                and not str(st.session_state.get(
                    f"feedback_text:{signature}:{style_id}:{expected_attempt}:{item['id']}", ""
                )).strip()
            ]
            if not incomplete:
                st.info("전달할 피드백이 없어 재작성하지 않고 현재 점수 결과에서 마무리합니다.")
                if st.button("현재 결과로 마무리", key=f"finalize_without_feedback_{style_id}_{latest_attempt}"):
                    save_attempt_result(
                        checklist,
                        experience,
                        latest_entry["rewrite"],
                        latest_entry["score"],
                        finalize=True,
                    )
                    st.success(f"{latest_attempt}차 결과를 최종 결과로 확정했습니다.")
                    _render_attempt_history(entries)
                    return True
            _render_attempt_history(entries)
            return False

    uploaded = st.file_uploader(
        "다시 쓴 rewrite JSON 올리기",
        type=["json"],
        key=f"retry_rewrite_upload_{expected_attempt}",
    )
    if uploaded is None:
        _render_attempt_history(entries)
        if latest_entry is not None and st.button(
            f"{latest_attempt}차 결과로 최종 확정", key=f"finalize_attempt_{latest_attempt}"
        ):
            save_attempt_result(
                checklist,
                experience,
                latest_entry["rewrite"],
                latest_score,
                finalize=True,
            )
            st.rerun()
        return False
    try:
        rewrites = rewrites_by_style(json.loads(uploaded.getvalue().decode("utf-8")))
        if len(rewrites) != 1:
            raise ValueError("재작성 attempt에는 rewrite 하나만 올려 주세요.")
        rewrite = rewrites[0]
        if rewrite.get("style_id") != style_id:
            raise ValueError("선택한 스타일의 rewrite만 채점할 수 있습니다.")
        if rewrite.get("attempt") != expected_attempt or expected_attempt > 4:
            raise ValueError(f"다음 attempt는 {expected_attempt}이어야 합니다 (최대 4).")
        retry_scores = score_if_available(checklist, experience, [rewrite])
        if retry_scores is None:
            raise ValueError("채점 코드를 사용할 수 없습니다.")
        score = retry_scores[0]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        st.error(f"재작성 결과를 채점하지 못했습니다: {error}")
        return False

    if score.get("passed") is True:
        save_attempt_result(checklist, experience, rewrite, score, finalize=True)
        st.rerun()
        return False

    if expected_attempt == 4:
        save_attempt_result(checklist, experience, rewrite, score, finalize=True)
        st.rerun()
        return False

    next_uploaded = None
    if expected_attempt < 4:
        st.caption("다음 차수 파일을 올리면 현재 미리보기 결과도 자동 저장됩니다.")
        next_uploaded = st.file_uploader(
            "다음 차수 rewrite JSON 올리기",
            type=["json"],
            key=f"retry_rewrite_upload_{expected_attempt + 1}",
        )

    if next_uploaded is not None:
        try:
            next_rewrites = rewrites_by_style(json.loads(next_uploaded.getvalue().decode("utf-8")))
            if len(next_rewrites) != 1:
                raise ValueError("재작성 attempt에는 rewrite 하나만 올려 주세요.")
            next_rewrite = next_rewrites[0]
            if next_rewrite.get("style_id") != style_id:
                raise ValueError("선택한 스타일의 rewrite만 채점할 수 있습니다.")
            if next_rewrite.get("attempt") != expected_attempt + 1:
                raise ValueError(f"다음 attempt는 {expected_attempt + 1}이어야 합니다 (최대 4).")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            st.error(f"다음 차수 재작성 결과를 채점하지 못했습니다: {error}")
        else:
            save_attempt_result(checklist, experience, rewrite, score)
            st.rerun()
            return False

    if st.button(f"{expected_attempt}차 결과로 최종 확정", key="save_retry_score"):
        save_attempt_result(checklist, experience, rewrite, score, finalize=True)
        st.rerun()
    st.caption(f"{rewrite['attempt']}차 미리보기")
    _render_attempt_history(entries, preview_rewrite=rewrite)
    _render_score_detail(score)
    return False


def load_sample_rewrites() -> tuple[list[dict[str, Any]], str]:
    """인수 없이 루프 첫 생성 샘플을 스타일별 rewrite로 나눠 (rewrite 목록, 읽은 파일 경로)를 돌려준다.

    samples/rewrite.sample.json이 세 스타일 묶음이면 그것을 쓴다.
    아직 스타일 하나짜리 옛 모양이면 app/preview_rewrite.sample.json(루프 PR #12 샘플 사본)을 쓴다.
    """
    sample_path = SAMPLES / "rewrite.sample.json"
    rewrites = rewrites_by_style(json.loads(sample_path.read_text(encoding="utf-8")))
    if len(rewrites) == len(STYLE_LABELS) or not PREVIEW_REWRITE_PATH.exists():
        return rewrites, sample_path.relative_to(ROOT).as_posix()
    preview = rewrites_by_style(json.loads(PREVIEW_REWRITE_PATH.read_text(encoding="utf-8")))
    return preview, PREVIEW_REWRITE_PATH.relative_to(ROOT).as_posix()


def score_if_available(
    checklist: dict[str, Any], experience: dict[str, Any], rewrites: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """채점 코드(scoring/score.py)가 저장소에 있으면 스타일마다 채점한 score 목록을, 아직 없으면 None을 돌려준다."""
    try:
        from scoring.score import score_case
    except ImportError:
        return None
    scores = []
    for rewrite in rewrites:
        candidate = deepcopy(rewrite)
        # 임시: 채점 PR #15가 아직 attempt_id를 요구한다. 빼기로 했으니 빠지면 이 줄도 지운다.
        candidate.setdefault("attempt_id", f"preview-{candidate.get('style_id')}")
        scores.append(score_case(checklist, experience, candidate))
    return scores


def _saved_case_id(checklist: dict[str, Any], experience: Any) -> str | None:
    """체크리스트와 확정한 경험을 받아, 분석한 케이스이고 experience.json이 저장됐으면 case_id를, 아니면 None을 돌려준다.

    샘플로 시작했으면 케이스 폴더에 파일이 없으므로 None이다.
    """
    from app.experience_input import ACTIVE_CASE_KEY, SAVED_EXPERIENCE_KEY

    case_id = checklist.get("case_id")
    active = st.session_state.get(ACTIVE_CASE_KEY)
    if not isinstance(active, dict) or active.get("case_id") != case_id:
        return None
    if not isinstance(experience, dict) or experience.get("case_id") != case_id:
        return None
    saved = st.session_state.get(SAVED_EXPERIENCE_KEY, {}).get(case_id)
    if not isinstance(saved, dict) or not saved.get("path"):
        return None
    return case_id


def _render_first_rewrite_generation(
    checklist: dict[str, Any], experience: dict[str, Any], case_id: str
) -> dict[str, Any] | None:
    """분석한 케이스의 체크리스트·경험·case_id를 받아 첫 생성 3종을 만들고 결과를 돌려준다. 아직 안 만들었으면 None.

    같은 입력으로 이미 만들었으면 다시 만들지 않고 세션에 남긴 결과를 돌려준다.
    """
    signature = _input_signature(checklist, experience)
    generated = st.session_state.setdefault(FIRST_REWRITE_KEY, {})
    if signature in generated:
        return generated[signature]

    st.write("확인한 체크리스트와 경험으로 첫 문장을 스타일 3종으로 만들어요.")
    st.caption("AI가 스타일마다 하나씩 차례로 만들어서 몇 분 걸릴 수 있어요. 같은 입력이면 저장해 둔 결과를 다시 써서 빨라요.")
    if not st.button("첫 문장 3종 만들기", type="primary", key=f"generate_first_rewrite_{case_id}"):
        return None

    from app.loop_bridge import generate_first_rewrite

    with st.spinner("첫 문장 3종을 만드는 중이에요. 창을 닫지 말고 기다려 주세요."):
        rewrite, errors = generate_first_rewrite(case_id)
    if rewrite is None:
        for error in errors or ["알 수 없는 오류"]:
            st.error(f"첫 문장을 만들지 못했습니다: {error}")
        return None
    generated[signature] = rewrite
    return rewrite


def render_style_step(checklist: dict[str, Any] | None) -> str | None:
    """app/main.py가 2단계 다음에 부르는 4단계 연결부.

    2단계에서 확정한 체크리스트(아직이면 None)를 받아 4단계 화면을 그리고, 고른 style_id(아직이면 None)를 돌려준다.
    - 3단계 경험 입력: 세션에 확정한 경험(experience_confirmed)이 있으면 그것, 없으면 저장소 샘플
    - 루프 첫 생성: 직접 올린 JSON이 있으면 그것. 없으면 분석한 케이스는 "첫 문장 3종 만들기"로 만든 결과,
      샘플로 시작했으면 저장소 샘플(세 스타일 묶음)
    - 채점: scoring/score.py가 있으면 스타일마다 채점, 없으면 문장만 비교
    """
    st.header("4. 스타일 고르기")
    if checklist is None:
        st.info("2단계에서 체크리스트를 확정하면 이어서 볼 수 있어요.")
        return None
    # 2단계에서 사용자가 확정한 체크리스트이므로 확인 완료로 본다. 옛 샘플이라 schema_version이 없으면 1로 채운다.
    checklist = deepcopy(checklist)
    checklist.setdefault("schema_version", 1)
    checklist["reviewed"] = True

    experience = st.session_state.get(EXPERIENCE_KEY)
    case_id = _saved_case_id(checklist, experience)
    if case_id is None:
        notes = st.expander(
            "아직 연결되지 않은 단계는 임시 데이터로 채웠어요",
            expanded=EXPERIENCE_KEY in st.session_state,
        )
        upload_label = "루프 첫 생성 결과 JSON 올리기 (올리지 않으면 샘플을 씁니다)"
    else:
        notes = st.expander("첫 생성 결과를 직접 올리기 (선택)", expanded=False)
        upload_label = "루프 첫 생성 결과 JSON 올리기 (올리지 않으면 이 케이스로 만든 결과를 씁니다)"
    with notes:
        uploaded = st.file_uploader(upload_label, type=["json"], key="style_step_upload")
    try:
        if experience is None:
            if SAMPLE_EXPERIENCE_KEY not in st.session_state:
                st.session_state[SAMPLE_EXPERIENCE_KEY] = load_sample_experience()
            experience = st.session_state[SAMPLE_EXPERIENCE_KEY]
            experience_note = "3단계 경험 입력: 저장소 샘플(samples/experience.sample.json)"
        else:
            experience_note = "3단계 경험 입력: 이번 세션에서 확정한 경험"
        if uploaded is not None:
            rewrites = rewrites_by_style(json.loads(uploaded.getvalue().decode("utf-8")))
            if not rewrites:
                raise ValueError("첨삭 결과에 스타일별 rewrite가 없습니다.")
            rewrite_note = f"루프 첫 생성: 올린 파일({uploaded.name})"
        elif case_id is not None:
            first_rewrite = _render_first_rewrite_generation(checklist, experience, case_id)
            if first_rewrite is None:
                return None
            rewrites = rewrites_by_style(first_rewrite)
            rewrite_note = f"루프 첫 생성: 이 케이스로 만든 결과(data/cases/{case_id}/rewrite.json)"
        else:
            rewrites, rewrite_path = load_sample_rewrites()
            rewrite_note = f"루프 첫 생성: 샘플({rewrite_path})"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        st.error(f"4단계에 넣을 데이터를 읽지 못했습니다: {error}")
        return None

    check_key = hashlib.sha256(
        json.dumps(
            [checklist, experience, rewrites], ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    cached_checks = st.session_state.setdefault(FIRST_ATTEMPT_CHECKS_KEY, {})
    if check_key not in cached_checks:
        cached_checks[check_key] = check_first_attempt(checklist, experience, rewrites)
    first_attempt_errors = cached_checks[check_key]
    if first_attempt_errors:
        if uploaded is None and case_id is None and EXPERIENCE_KEY in st.session_state:
            st.info("현재 이력서 경험과 맞는 첫 rewrite JSON을 올려 주세요. 저장소 샘플은 미리보기용입니다.")
        else:
            st.error("\n".join(first_attempt_errors))
        return None

    try:
        scores = score_if_available(checklist, experience, rewrites)
        score_note = "채점: scoring/score.py로 채점" if scores is not None else "채점: 채점 코드가 아직 없어 문장만 비교"
    except (KeyError, TypeError, ValueError) as error:
        scores = None
        score_note = f"채점: 채점하지 못해 문장만 비교 ({error})"
    with notes:
        for note in (experience_note, rewrite_note, score_note):
            st.caption(note)
        if uploaded is None and case_id is None and EXPERIENCE_KEY in st.session_state:
            st.caption("저장소의 첫 첨삭은 샘플입니다. 입력한 경험과 다르면 해당 경험으로 생성한 rewrite JSON을 올려 주세요.")



    selected_style = render_style_select(
        checklist, experience, rewrites, scores, heading=False, validate_first_attempt=False
    )
    if selected_style:
        first_rewrite = next(
            (rewrite for rewrite in rewrites if rewrite["style_id"] == selected_style),
            None,
        )
        first_score = next(
            (score for score in scores or [] if score["style_id"] == selected_style),
            None,
        )
        if first_rewrite is not None and first_score is not None:
            save_attempt_result(checklist, experience, first_rewrite, first_score)
            if render_retry_scoring(checklist, experience, selected_style, first_score):
                from app.report import render_report

                signature = _input_signature(checklist, experience)
                render_report(
                    checklist,
                    experience,
                    selected_style,
                    first_rewrite,
                    first_score,
                    st.session_state.get("rewrite_score_history", []),
                    signature,
                    final_attempt=st.session_state.get(f"final_result_saved:{signature}:{selected_style}"),
                )
        else:
            st.info("점수 결과가 없어 1차 rewrite·score 이력을 저장할 수 없습니다.")
    return selected_style


def demo() -> None:
    """인수 없이 저장소 샘플로 4단계 화면만 따로 띄운다. 2단계는 샘플 체크리스트를 확정한 것으로 본다."""
    st.set_page_config(page_title="4. 스타일 고르기 미리보기", layout="wide")
    st.title("스타일 고르기 미리보기")
    st.caption("저장소 샘플로 그린 화면입니다. 실제 사용자 결과가 아닙니다.")
    try:
        checklist = load_sample_checklist()
    except (OSError, ValueError) as error:
        st.error(f"샘플을 불러오지 못했습니다: {error}")
        return
    render_style_step(checklist)


if __name__ == "__main__":
    # streamlit run app/style_select.py 로 띄울 때 저장소 최상위의 scoring/을 찾을 수 있게 한다.
    sys.path.insert(0, str(ROOT))
    demo()
