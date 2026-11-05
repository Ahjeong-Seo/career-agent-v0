"""체크리스트 항목별 경험을 사용자가 직접 입력하는 화면."""

from copy import deepcopy
from typing import Any

import streamlit as st


EXPERIENCE_KEY = "experience_confirmed"


def render_experience_step(checklist: dict[str, Any] | None, resume_text: str) -> dict[str, Any] | None:
    """확정 체크리스트와 이력서 원문을 받아 입력 화면을 그리고, 확정 경험 객체를 반환한다."""
    if checklist is None:
        return None

    st.header("3. 항목별 경험 입력")
    st.write("각 항목과 관련된 경험을 직접 적어 주세요. 경험이 없으면 비워 두셔도 됩니다.")
    resume_column, experience_column = st.columns([1, 2])

    with resume_column:
        st.subheader("이력서 원문 참고")
        st.caption("복사 버튼을 눌러 원문을 가져올 수 있습니다.")
        st.code(resume_text or "1단계에서 입력한 이력서가 없습니다.", language=None)

    with experience_column:
        with st.form("experience_input_form", border=False):
            for item in checklist.get("items", []):
                item_id = item.get("id")
                if not isinstance(item_id, str):
                    continue
                st.markdown(f"**{item_id} · {item.get('level')} · {item.get('text')}**")
                st.text_area(
                    f"{item_id} 경험",
                    height=120,
                    key=f"experience_{item_id}",
                    help="이력서 원문을 참고해 직접 입력하세요. 입력하지 않으면 경험 없음으로 처리합니다.",
                )
            submitted = st.form_submit_button("경험 입력 확정", type="primary", key="confirm_experience")

    if submitted:
        experiences = []
        for item in checklist.get("items", []):
            item_id = item.get("id")
            if not isinstance(item_id, str):
                continue
            text = st.session_state.get(f"experience_{item_id}", "")
            if isinstance(text, str) and text.strip():
                experiences.append({"item_id": item_id, "text": text})
        st.session_state[EXPERIENCE_KEY] = {
            "schema_version": checklist.get("schema_version", 1),
            "case_id": checklist.get("case_id"),
            "experiences": experiences,
        }

    confirmed = st.session_state.get(EXPERIENCE_KEY)
    if isinstance(confirmed, dict) and confirmed.get("case_id") == checklist.get("case_id"):
        st.success("경험 입력을 확정했습니다. 다음 단계에서 첫 첨삭 결과를 확인할 수 있습니다.")
        return deepcopy(confirmed)

    st.caption("입력을 확정하면 다음 단계로 넘어갑니다.")
    return None
