"""체크리스트 항목마다 사용자의 실제 경험을 입력받는 화면."""

import json
from typing import Any

import streamlit as st


EXPERIENCE_KEY = "experience_confirmed"
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

    경험 글이 있는 항목만 넣는다. 연수는 사용자가 적은 숫자만 쓰고, 비어 있으면 null(None)이다.
    연수를 지어내거나 경험 글에서 뽑아 채우지 않는다.
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


def render_experience_input(
    checklist: dict[str, Any] | None, resume_text: str
) -> dict[str, Any] | None:
    """확인된 체크리스트와 이력서 원문을 받아 경험 입력 화면을 그리고, 확정 객체를 반환한다."""
    st.header("3. 경험 입력")
    if not isinstance(checklist, dict) or checklist.get("reviewed") is not True:
        st.info("체크리스트를 확정하면 경험을 입력할 수 있어요.")
        return None

    st.write("이력서를 보면서 각 요구사항에 해당하는 실제 경험을 그대로 붙여 넣어 주세요.")

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

    case_id = checklist["case_id"]
    drafts = st.session_state.setdefault(DRAFTS_KEY, {}).setdefault(case_id, {})
    years_drafts = st.session_state.setdefault(YEARS_DRAFTS_KEY, {}).setdefault(case_id, {})
    inputs: dict[str, str] = {}
    years_inputs: dict[str, Any] = {}
    with columns[1]:
        st.subheader("요구사항별 경험")
        for item in checklist.get("items", []):
            item_id = item["id"]
            st.markdown(f"**{item_id} · {item.get('text', '요구사항')}**")
            key = f"experience_text_{case_id}_{item_id}"
            if key not in st.session_state:
                st.session_state[key] = drafts.get(item_id, confirmed_by_id.get(item_id, ""))
            inputs[item_id] = st.text_area(
                f"{item_id} 경험 원문",
                key=key,
                height=100,
                placeholder="이 항목에 해당하는 실제 경험을 원문 그대로 붙여 넣으세요.",
                label_visibility="collapsed",
            )
            drafts[item_id] = inputs[item_id]

            # 요구 연수가 있는 항목에만 연수 칸을 둔다. 비워 두면 null(미확인)로 저장한다.
            needed = required_years(item)
            if needed is None:
                continue
            years_key = f"experience_years_{case_id}_{item_id}"
            if years_key not in st.session_state:
                saved_years = years_drafts.get(item_id, confirmed_years_by_id.get(item_id))
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
    if confirmed is not None and confirmed != candidate:
        st.session_state.pop(EXPERIENCE_KEY, None)

    if st.button("경험 입력 확인", key="confirm_experience"):
        st.session_state[EXPERIENCE_KEY] = candidate
        confirmed = candidate

    if confirmed == candidate:
        st.success("경험 입력을 확인했습니다. 경험이 없는 항목은 비워 둔 상태로 저장됩니다.")
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
