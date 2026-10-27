"""입력 준비와 체크리스트 확인 화면. 실행: streamlit run app/main.py."""

from copy import deepcopy
import json
from pathlib import Path
import sys

import streamlit as st

# Streamlit을 저장소 밖에서 실행해도 같은 앱 모듈을 가져온다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.frontend import (  # noqa: E402
    allowed_values,
    checklist_json,
    checklist_rows,
    mark_reviewed,
    merge_checklist_edits,
    prepare_job_text,
    prepare_resume_text,
    sample_draft_checklist,
    validate_checklist,
)


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "samples" / "checklist.sample.json"


def render_txt_download(content: str, label: str, filename: str, state_key: str) -> None:
    """TXT 내용과 표시 정보를 받아 사용자가 준비한 사본만 미리보기·다운로드로 제공한다."""
    changed = state_key in st.session_state and st.session_state[state_key] != content
    if changed:
        del st.session_state[state_key]
    if st.button(f"{label} TXT 다운로드 준비", key=f"prepare_{state_key}", disabled=not bool(content)):
        st.session_state[state_key] = content
    elif changed:
        st.info(f"{label} 입력이 바뀌었습니다. TXT 다운로드 준비를 다시 눌러 주세요.")

    prepared = st.session_state.get(state_key)
    if prepared is None:
        return
    st.caption(f"아래 파일은 마지막으로 준비한 {label} 내용을 담습니다.")
    with st.expander(f"준비한 {label} TXT 내용 확인"):
        st.code(prepared, language=None)
    st.download_button(
        f"준비한 {label} TXT 다운로드",
        data=prepared,
        file_name=filename,
        mime="text/plain; charset=utf-8",
        on_click="ignore",
    )


def render_inputs() -> None:
    """인수 없이 입력란과 TXT 다운로드를 표시하고 현재 입력을 세션에 유지한다."""
    st.header("1. 지원할 공고와 이력서 준비")
    st.write("채용공고, 회사정보, 이력서를 각각 붙여 넣어 주세요.")
    job_posting = st.text_area("채용공고", key="job_posting", height=180)
    company_info = st.text_area("회사정보 (선택)", key="company_info", height=140)
    resume = st.text_area("이력서", key="resume", height=220)
    st.caption("입력은 현재 세션에만 유지되며 앱이 파일로 자동 저장하지 않습니다. 새로고침하거나 세션이 끝나면 사라질 수 있습니다.")
    st.caption("TXT 다운로드 준비를 누른 시점의 내용으로 파일을 만듭니다. 입력을 고친 뒤에는 다시 준비해 주세요.")

    job_text = ""
    try:
        job_text = prepare_job_text(company_info, job_posting)
    except ValueError as error:
        st.caption(f"공고 TXT 준비: {error}")
    render_txt_download(job_text, "회사정보·공고", "job_posting.txt", "prepared_job_text")

    resume_text = ""
    try:
        resume_text = prepare_resume_text(resume)
    except ValueError as error:
        st.caption(f"이력서 TXT 준비: {error}")
    render_txt_download(resume_text, "이력서", "resume.txt", "prepared_resume_text")


def start_sample() -> None:
    """인수 없이 저장소 샘플을 '확인 전 파싱 결과'로 읽어 검증하고 확인 시작 데이터를 세션에 넣는다."""
    # 임시: 파싱팀 make_checklist가 연결되면 샘플 대신 그 결과를 넣는다.
    draft = sample_draft_checklist(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))
    errors = validate_checklist(draft)
    if errors:
        raise ValueError("\n".join(errors))
    st.session_state.checklist_original = draft
    st.session_state.checklist_draft = deepcopy(draft)


def render_checklist() -> None:
    """인수 없이 체크리스트 확인 표와 항목별 오류를 표시하고, 확인 완료한 JSON 다운로드를 제공한다."""
    st.header("2. 체크리스트 확인")
    st.info("공고 파싱은 아직 연결되지 않았습니다. 아래 체크리스트는 위 입력에서 만든 결과가 아니라 저장소 샘플입니다.")
    if "checklist_original" not in st.session_state:
        if st.button("샘플 체크리스트로 확인 시작", key="start_sample", type="primary"):
            try:
                start_sample()
            except (OSError, ValueError) as error:
                st.error(f"샘플을 불러오지 못했습니다: {error}")
                return
        else:
            return

    original = st.session_state.checklist_original
    st.write(f"직무: **{original.get('job_title') or '직무 미지정'}**")
    values = original.get("company_values") or []
    st.write(f"회사 인재상: {', '.join(values) if values else '없음'}")
    st.caption("요구사항·키워드·유형·필수/우대를 고칠 수 있습니다. 항목 ID와 항목 수는 바뀌지 않습니다.")
    st.caption("키워드 칸을 더블클릭한 뒤 입력하고 Enter를 눌러 추가하세요. 각 키워드를 지워서 수정할 수 있습니다.")
    rows = st.data_editor(
        checklist_rows(original),
        key="checklist_editor",
        num_rows="fixed",
        hide_index=True,
        disabled=["id"],
        column_config={
            "id": st.column_config.TextColumn("항목 ID", width="small"),
            "text": st.column_config.TextColumn("요구사항", width="medium"),
            "keywords": st.column_config.ListColumn("키워드", width="medium"),
            "type": st.column_config.SelectboxColumn(
                "유형", options=allowed_values("type"), required=True, width="small"
            ),
            "level": st.column_config.SelectboxColumn(
                "필수/우대", options=allowed_values("level"), required=True, width="small"
            ),
        },
    )
    try:
        candidate = merge_checklist_edits(original, rows)
        st.session_state.checklist_draft = candidate
        errors = validate_checklist(candidate)
    except ValueError as error:
        candidate = None
        errors = [str(error)]

    # 확인 완료한 뒤 표를 다시 고치면 확인을 취소한다. 고친 내용으로 다시 확인받아야 한다.
    if candidate is None or st.session_state.get("checklist_confirmed") != mark_reviewed(candidate):
        st.session_state.pop("checklist_confirmed", None)
    for error in errors:
        st.error(error)
    if errors:
        st.warning("위 오류를 해결해야 확인 완료하거나 다운로드할 수 있습니다.")

    if st.button("확인 완료", key="confirm_checklist", disabled=bool(errors)):
        st.session_state.checklist_confirmed = mark_reviewed(candidate)
    if "checklist_confirmed" in st.session_state:
        st.success("체크리스트 확인을 마쳤습니다 (reviewed: true). 다음 단계에서 이 체크리스트를 씁니다.")
        st.download_button(
            "확인한 체크리스트 JSON 다운로드",
            data=checklist_json(st.session_state.checklist_confirmed),
            file_name="checklist.json",
            mime="application/json",
            on_click="ignore",
        )
    elif not errors:
        st.caption("확인 완료를 누르면 JSON을 다운로드할 수 있습니다. 다시 고친 뒤에는 한 번 더 눌러 주세요.")
    st.caption("검사 기준은 파싱팀 스키마(schemas/parsing/checklist.json)입니다. 다운로드에는 원래 칸이 그대로 들어갑니다.")


def main() -> None:
    """인수 없이 세로 한 열의 Streamlit 시작 화면을 그린다."""
    st.set_page_config(page_title="이력서 스터디: 입력과 체크리스트", layout="centered")
    st.title("이력서 입력과 체크리스트")
    st.write("지원 자료를 준비하고, 샘플로 체크리스트 확인 흐름을 시험해 보세요.")
    render_inputs()
    st.divider()
    render_checklist()


if __name__ == "__main__":
    main()
