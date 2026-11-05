"""체크리스트 항목마다 사용자의 실제 경험을 입력받는 화면."""

import json
from typing import Any

import streamlit as st


EXPERIENCE_KEY = "experience_confirmed"
# 입력란과 따로 두는 초안: {case_id: {item_id: 적은 글}}.
# 체크리스트를 고치는 동안에는 입력란을 그리지 않는데, Streamlit은 화면에 없는 입력란 값을 지운다.
# 그래서 적은 글을 여기에도 남겨 두고, 체크리스트를 다시 확인하면 입력란을 이 값으로 채운다.
DRAFTS_KEY = "experience_drafts"


def _experience_from_inputs(
    checklist: dict[str, Any], inputs: dict[str, str]
) -> dict[str, Any]:
    """확인된 체크리스트와 항목별 입력을 받아 experience 계약 객체를 반환한다."""
    experiences = []
    for item in checklist.get("items", []):
        item_id = item["id"]
        text = inputs.get(item_id, "")
        if text.strip():
            experiences.append({"item_id": item_id, "text": text})

    return {
        "case_id": checklist["case_id"],
        "schema_version": 1,
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
    if isinstance(confirmed, dict) and confirmed.get("case_id") == checklist.get("case_id"):
        confirmed_by_id = {
            row.get("item_id"): row.get("text", "")
            for row in confirmed.get("experiences", [])
            if isinstance(row, dict)
        }

    drafts = st.session_state.setdefault(DRAFTS_KEY, {}).setdefault(checklist["case_id"], {})
    inputs: dict[str, str] = {}
    with columns[1]:
        st.subheader("요구사항별 경험")
        for item in checklist.get("items", []):
            item_id = item["id"]
            st.markdown(f"**{item_id} · {item.get('text', '요구사항')}**")
            key = f"experience_text_{checklist['case_id']}_{item_id}"
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

    candidate = _experience_from_inputs(checklist, inputs)
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
