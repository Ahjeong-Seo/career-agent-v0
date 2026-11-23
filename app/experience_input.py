"""체크리스트 항목마다 사용자의 실제 경험을 입력받는 화면.

분석한 케이스면 파싱이 만든 경험 초안(experience_draft.json)으로 입력란을 미리 채우고,
사용자가 확인·수정해 확정하면 experience.json을 케이스 폴더에 저장한다 (C안: 미리 채우고 사람이 확인).
샘플로 시작했으면 미리 채우지 않고, 파일도 저장하지 않는다.
"""

import json
from pathlib import Path
from typing import Any

import streamlit as st

from app.parsing_bridge import (
    keywords_missing,
    prefill_from_draft,
    regenerate_experience_draft,
    save_confirmed_experience,
)


ROOT = Path(__file__).resolve().parents[1]
EXPERIENCE_KEY = "experience_confirmed"
# 분석한 케이스 정보: {"case_id", "job_text", "resume_text"}. 샘플로 시작하면 없다.
ACTIVE_CASE_KEY = "active_case"
# 파싱이 만든 경험 초안: {case_id: experience_draft 객체}
EXPERIENCE_DRAFT_KEY = "experience_draft"
# 경험 초안을 만들다 난 오류: {case_id: [오류 문장]}
DRAFT_ERRORS_KEY = "experience_draft_errors"
# experience.json 저장 결과: {case_id: {"path": 저장 경로 또는 None, "errors": [오류 문장]}}
SAVED_EXPERIENCE_KEY = "experience_saved"
# 입력란과 따로 두는 초안: {case_id: {item_id: 적은 글}}.
# 체크리스트를 고치는 동안에는 입력란을 그리지 않는데, Streamlit은 화면에 없는 입력란 값을 지운다.
# 그래서 적은 글을 여기에도 남겨 두고, 체크리스트를 다시 확인하면 입력란을 이 값으로 채운다.
DRAFTS_KEY = "experience_drafts"
# 연수 입력란도 같은 이유로 따로 남겨 둔다: {case_id: {item_id: 연수 또는 None}}.
YEARS_DRAFTS_KEY = "experience_years_drafts"


def required_years(item: dict[str, Any]) -> int | None:
    """체크리스트 항목 하나를 받아 요구 연수(1 이상 정수)를 돌려준다. 요구 연수가 없거나 0이면 None."""
    years = item.get("years")
    if isinstance(years, int) and not isinstance(years, bool) and years > 0:
        return years
    return None


def _clean_years(value: Any) -> int | None:
    """연수 입력값을 받아 0~100 정수면 그대로, 비었거나 숫자가 아니면 None을 돌려준다."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != int(value) or not 0 <= value <= 100:
        return None
    return int(value)


def _experience_from_inputs(
    checklist: dict[str, Any],
    inputs: dict[str, str],
    years_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """확인된 체크리스트, 항목별 경험 글, 항목별 연수를 받아 experience 계약 객체를 반환한다.

    경험 글이 있는 항목만 넣는다. 연수는 입력란에 남은 숫자만 쓰고, 비어 있으면 null(None)이다.
    이 함수는 연수를 지어내거나 경험 글에서 뽑지 않는다. (미리 채운 연수는 파싱 초안에서 온다)
    """
    years_inputs = years_inputs or {}
    experiences = []
    for item in checklist.get("items", []):
        item_id = item["id"]
        text = inputs.get(item_id, "")
        if text.strip():
            experiences.append(
                {
                    "item_id": item_id,
                    "text": text,
                    "years": _clean_years(years_inputs.get(item_id)),
                }
            )

    return {
        "case_id": checklist["case_id"],
        "schema_version": 2,
        "experiences": experiences,
    }


def _text_key(case_id: str, item_id: str) -> str:
    """케이스·항목 ID를 받아 경험 글 입력란의 세션 키를 돌려준다."""
    return f"experience_text_{case_id}_{item_id}"


def _years_key(case_id: str, item_id: str) -> str:
    """케이스·항목 ID를 받아 연수 입력란의 세션 키를 돌려준다."""
    return f"experience_years_{case_id}_{item_id}"


def _display_path(path: str) -> str:
    """저장 경로를 받아 저장소 기준 상대 경로(가능하면)로 돌려준다."""
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _fill_empty_inputs(
    checklist: dict[str, Any],
    draft: dict[str, Any],
    drafts: dict[str, str],
    years_drafts: dict[str, Any],
) -> None:
    """새 초안을 받아 아직 비어 있는 입력란만 채운다. 사용자가 이미 적은 칸은 건드리지 않는다."""
    case_id = checklist["case_id"]
    texts, years = prefill_from_draft(draft, checklist)
    for item in checklist.get("items", []):
        item_id = item["id"]
        key = _text_key(case_id, item_id)
        current = st.session_state.get(key, drafts.get(item_id, ""))
        if not current.strip() and item_id in texts:
            st.session_state[key] = texts[item_id]
            drafts[item_id] = texts[item_id]
        years_key = _years_key(case_id, item_id)
        if required_years(item) and item_id in years:
            if st.session_state.get(years_key, years_drafts.get(item_id)) is None:
                st.session_state[years_key] = years[item_id]
                years_drafts[item_id] = years[item_id]


def _render_draft_status(
    checklist: dict[str, Any], drafts: dict[str, str], years_drafts: dict[str, Any]
) -> None:
    """분석한 케이스의 경험 초안 상태(채움/실패)를 보여 주고, '초안 다시 만들기' 버튼을 그린다."""
    case_id = checklist["case_id"]
    draft = st.session_state.get(EXPERIENCE_DRAFT_KEY, {}).get(case_id)
    errors = st.session_state.get(DRAFT_ERRORS_KEY, {}).get(case_id) or []
    if draft is not None:
        st.info(
            "이력서에서 항목마다 맞는 원문을 찾아 미리 채웠어요. "
            "맞는지 확인하고 고친 뒤 '경험 입력 확인'을 눌러 주세요."
        )
    elif errors:
        st.warning("경험 초안을 만들지 못했어요. 직접 입력하거나 '초안 다시 만들기'를 눌러 주세요.")
        for error in errors:
            st.caption(error)
    else:
        st.write("이력서를 보면서 각 요구사항에 해당하는 실제 경험을 그대로 붙여 넣어 주세요.")

    if st.button(
        "초안 다시 만들기 (빈 칸만 채워요)",
        key=f"regenerate_draft_{case_id}",
        help="AI를 다시 불러 초안을 새로 만들어요. 이미 적은 칸은 그대로 둬요. 몇 분 걸릴 수 있어요.",
    ):
        with st.spinner("이력서에서 항목별 경험을 다시 찾는 중이에요..."):
            new_draft, new_errors = regenerate_experience_draft(case_id)
        st.session_state.setdefault(DRAFT_ERRORS_KEY, {})[case_id] = new_errors
        if new_draft is not None:
            st.session_state.setdefault(EXPERIENCE_DRAFT_KEY, {})[case_id] = new_draft
            _fill_empty_inputs(checklist, new_draft, drafts, years_drafts)
        st.rerun()


def _render_prefill_note(item: dict[str, Any], current: str, prefilled: str | None) -> None:
    """항목, 지금 입력란의 글, 초안이 채운 글을 받아 '자동으로 가져온 글'·'키워드 없음'·'못 찾음' 안내를 그린다."""
    if prefilled and current == prefilled:
        st.caption("이력서에서 자동으로 가져온 글이에요. 맞는지 확인하고 고쳐 주세요.")
        keywords = item.get("keywords") or []
        if keywords_missing(current, keywords):
            st.warning(
                f"이 글에는 항목 키워드({', '.join(keywords)})가 없어요. 맞는 경험인지 확인해 주세요."
            )
    elif not prefilled and not current.strip():
        st.caption("이력서에서 맞는 경험을 못 찾았어요. 있으면 직접 적어 주세요.")


def render_experience_input(
    checklist: dict[str, Any] | None, resume_text: str
) -> dict[str, Any] | None:
    """확인된 체크리스트와 이력서 원문을 받아 경험 입력 화면을 그리고, 확정 객체를 반환한다."""
    st.header("3. 경험 입력")
    if not isinstance(checklist, dict) or checklist.get("reviewed") is not True:
        st.info("체크리스트를 확정하면 경험을 입력할 수 있어요.")
        return None

    case_id = checklist["case_id"]
    active = st.session_state.get(ACTIVE_CASE_KEY)
    # 분석한 케이스일 때만 초안으로 미리 채우고 experience.json을 저장한다. 샘플은 화면 안에서만 쓴다.
    real_case = isinstance(active, dict) and active.get("case_id") == case_id
    drafts = st.session_state.setdefault(DRAFTS_KEY, {}).setdefault(case_id, {})
    years_drafts = st.session_state.setdefault(YEARS_DRAFTS_KEY, {}).setdefault(case_id, {})

    if real_case:
        _render_draft_status(checklist, drafts, years_drafts)
    else:
        st.write("이력서를 보면서 각 요구사항에 해당하는 실제 경험을 그대로 붙여 넣어 주세요.")
    draft = st.session_state.get(EXPERIENCE_DRAFT_KEY, {}).get(case_id) if real_case else None
    prefill_texts, prefill_years = prefill_from_draft(draft, checklist)

    columns = st.columns([1, 1.4])
    with columns[0]:
        st.subheader("이력서 원문")
        if resume_text.strip():
            st.code(resume_text, language=None, wrap_lines=True)
        else:
            st.info("이력서 원문이 없습니다. 필요한 경험을 오른쪽 항목에 직접 입력해 주세요.")

    confirmed = st.session_state.get(EXPERIENCE_KEY)
    confirmed_by_id: dict[str, str] = {}
    confirmed_years_by_id: dict[str, Any] = {}
    if isinstance(confirmed, dict) and confirmed.get("case_id") == checklist.get("case_id"):
        rows = [row for row in confirmed.get("experiences", []) if isinstance(row, dict)]
        confirmed_by_id = {row.get("item_id"): row.get("text", "") for row in rows}
        confirmed_years_by_id = {row.get("item_id"): row.get("years") for row in rows}

    inputs: dict[str, str] = {}
    years_inputs: dict[str, Any] = {}
    with columns[1]:
        st.subheader("요구사항별 경험")
        for item in checklist.get("items", []):
            item_id = item["id"]
            st.markdown(f"**{item_id} · {item.get('text', '요구사항')}**")
            key = _text_key(case_id, item_id)
            if key not in st.session_state:
                # 우선순위: 이번에 적던 글 > 확인한 글 > 파싱 초안 > 빈칸
                st.session_state[key] = drafts.get(
                    item_id, confirmed_by_id.get(item_id, prefill_texts.get(item_id, ""))
                )
            inputs[item_id] = st.text_area(
                f"{item_id} 경험 원문",
                key=key,
                height=100,
                placeholder="이 항목에 해당하는 실제 경험을 원문 그대로 붙여 넣으세요.",
                label_visibility="collapsed",
            )
            drafts[item_id] = inputs[item_id]
            if draft is not None:
                _render_prefill_note(item, inputs[item_id], prefill_texts.get(item_id))

            # 요구 연수가 있는 항목에만 연수 칸을 둔다. 비워 두면 null(미확인)로 저장한다.
            needed = required_years(item)
            if needed is None:
                continue
            years_key = _years_key(case_id, item_id)
            if years_key not in st.session_state:
                saved_years = years_drafts.get(
                    item_id, confirmed_years_by_id.get(item_id, prefill_years.get(item_id))
                )
                if saved_years is not None:
                    st.session_state[years_key] = saved_years
            years_inputs[item_id] = st.number_input(
                f"{item_id} 경력 연수 (선택 · 요구 {needed}년)",
                min_value=0,
                max_value=100,
                value=None,
                step=1,
                key=years_key,
                placeholder="숫자만, 비워 두면 미확인",
                help="이 항목과 관련된 경력이 몇 년인지 직접 적어 주세요. 비워 둬도 됩니다.",
                width=240,
            )
            years_drafts[item_id] = years_inputs[item_id]
            if years_inputs[item_id] is not None and not inputs[item_id].strip():
                st.caption("경험 글을 적어야 연수도 함께 저장돼요.")

    candidate = _experience_from_inputs(checklist, inputs, years_inputs)
    saved = st.session_state.setdefault(SAVED_EXPERIENCE_KEY, {})
    if confirmed is not None and confirmed != candidate:
        st.session_state.pop(EXPERIENCE_KEY, None)
        saved.pop(case_id, None)

    if st.button("경험 입력 확인", key="confirm_experience"):
        st.session_state[EXPERIENCE_KEY] = candidate
        confirmed = candidate
        if real_case:
            path, errors = save_confirmed_experience(candidate)
            saved[case_id] = {"path": str(path) if path else None, "errors": errors}

    if confirmed == candidate:
        st.success("경험 입력을 확인했습니다. 경험이 없는 항목은 비워 둔 상태로 저장됩니다.")
        result = saved.get(case_id)
        if real_case and result:
            if result["path"]:
                st.caption(f"{_display_path(result['path'])}에 저장했어요. 루프는 이 파일을 읽어요.")
            for error in result["errors"]:
                st.error(f"experience.json을 저장하지 못했습니다: {error}")
        st.download_button(
            "확인한 경험 JSON 다운로드",
            data=json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
            file_name="experience.json",
            mime="application/json",
            on_click="ignore",
        )
        return candidate

    st.caption("입력을 바꾼 뒤에는 다시 ‘경험 입력 확인’을 눌러야 다음 단계로 갈 수 있습니다.")
    return None
