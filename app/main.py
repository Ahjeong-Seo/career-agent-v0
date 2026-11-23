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
    years_label,
)
from app.experience_input import (  # noqa: E402
    ACTIVE_CASE_KEY,
    DRAFT_ERRORS_KEY,
    DRAFTS_KEY,
    EXPERIENCE_DRAFT_KEY,
    EXPERIENCE_KEY,
    YEARS_DRAFTS_KEY,
)
from app import parsing_bridge  # noqa: E402


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "samples" / "checklist.sample.json"
ANALYZE_ERRORS_KEY = "analyze_errors"
# 새 케이스를 시작하면 지우는 아래 단계 세션 값. 체크리스트·경험·스타일 선택을 처음부터 다시 한다.
DOWNSTREAM_KEYS = (
    "checklist_original",
    "checklist_draft",
    "checklist_confirmed",
    "checklist_editor",
    EXPERIENCE_KEY,
    "selected_style_id",
    "style_choice",
)


def reset_downstream() -> None:
    """인수 없이 체크리스트 확인부터 아래 단계의 세션 값을 지운다. 새 케이스를 시작할 때 부른다."""
    for key in DOWNSTREAM_KEYS:
        st.session_state.pop(key, None)


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
    st.caption("분석하기를 누르기 전까지 입력은 이 화면에만 있고, 새로고침하면 사라질 수 있습니다. 분석하면 케이스 폴더에 저장됩니다.")
    st.caption("TXT 다운로드 준비를 누른 시점의 내용으로 파일을 만듭니다. 입력을 고친 뒤에는 다시 준비해 주세요.")

    job_text = ""
    try:
        job_text = prepare_job_text(company_info, job_posting)
    except ValueError as error:
        st.caption(f"공고 TXT 준비: {error}")
    render_txt_download(job_text, "채용공고", "jd.txt", "prepared_job_text")

    resume_text = ""
    try:
        resume_text = prepare_resume_text(resume)
    except ValueError as error:
        st.caption(f"이력서 TXT 준비: {error}")
    render_txt_download(resume_text, "이력서", "resume.txt", "prepared_resume_text")

    render_analyze(job_text, resume_text)


def render_analyze(job_text: str, resume_text: str) -> None:
    """공고 TXT 내용과 이력서 원문을 받아 '분석하기' 버튼을 그린다. 누르면 새 케이스와 체크리스트를 만든다."""
    st.subheader("공고·이력서 분석")
    st.caption(
        "분석하기를 누르면 공고·이력서가 data/cases/<case_id>/에 저장되고, AI가 체크리스트를 만들어요. "
        "몇 분 걸릴 수 있어요."
    )
    if st.button(
        "분석하기", key="analyze_inputs", type="primary", disabled=not (job_text and resume_text)
    ):
        with st.spinner("공고를 읽고 체크리스트를 만드는 중이에요..."):
            case_id, checklist, errors = parsing_bridge.start_case_from_inputs(job_text, resume_text)
        if errors:
            st.session_state[ANALYZE_ERRORS_KEY] = errors
        else:
            st.session_state.pop(ANALYZE_ERRORS_KEY, None)
            reset_downstream()
            # 체크리스트 확인 뒤 경험 초안을 만들 때 처음과 똑같은 공고·이력서를 넘겨야 해서 함께 남긴다.
            st.session_state[ACTIVE_CASE_KEY] = {
                "case_id": case_id,
                "job_text": job_text,
                "resume_text": resume_text,
            }
            st.session_state.checklist_original = checklist
            st.session_state.checklist_draft = deepcopy(checklist)

    for error in st.session_state.get(ANALYZE_ERRORS_KEY, []):
        st.error(f"분석하지 못했습니다: {error}")
    active = st.session_state.get(ACTIVE_CASE_KEY)
    if isinstance(active, dict):
        st.success(f"케이스 {active['case_id']}로 분석했어요. 아래에서 체크리스트를 확인해 주세요.")
        if (active["job_text"], active["resume_text"]) != (job_text, resume_text):
            st.warning("입력이 분석한 내용과 달라졌어요. 바뀐 내용을 쓰려면 다시 분석해 주세요(새 케이스로 시작해요).")


def start_sample() -> None:
    """인수 없이 저장소 샘플을 '확인 전 파싱 결과'로 읽어 검증하고 확인 시작 데이터를 세션에 넣는다.

    공고 분석 없이 화면 흐름만 시험할 때 쓴다. 샘플은 케이스 폴더에 아무것도 저장하지 않는다.
    """
    draft = sample_draft_checklist(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))
    errors = validate_checklist(draft)
    if errors:
        raise ValueError("\n".join(errors))
    st.session_state.pop(ACTIVE_CASE_KEY, None)
    st.session_state.checklist_original = draft
    st.session_state.checklist_draft = deepcopy(draft)


def fetch_draft_for_active_case(confirmed: dict) -> None:
    """확인한 체크리스트를 받아, 분석한 케이스이면 경험 초안을 만들어 세션에 넣는다. 샘플이면 아무것도 하지 않는다."""
    active = st.session_state.get(ACTIVE_CASE_KEY)
    if not isinstance(active, dict) or active.get("case_id") != confirmed.get("case_id"):
        return
    case_id = active["case_id"]
    with st.spinner("이력서에서 항목별 경험을 찾는 중이에요. AI를 부르는 거라 몇 분 걸릴 수 있어요..."):
        draft, errors = parsing_bridge.fetch_experience_draft(
            active["job_text"], active["resume_text"], confirmed, case_id
        )
    if draft is not None:
        st.session_state.setdefault(EXPERIENCE_DRAFT_KEY, {})[case_id] = draft
    st.session_state.setdefault(DRAFT_ERRORS_KEY, {})[case_id] = errors


def render_checklist() -> None:
    """인수 없이 체크리스트 확인 표와 항목별 오류를 표시하고, 확인 완료한 JSON 다운로드를 제공한다."""
    st.header("2. 체크리스트 확인")
    active = st.session_state.get(ACTIVE_CASE_KEY)
    if isinstance(active, dict) and "checklist_original" in st.session_state:
        st.caption(f"케이스 {active['case_id']}: 위 공고를 AI가 읽어 만든 체크리스트예요. 틀린 곳을 고친 뒤 확인 완료를 눌러 주세요.")
    elif "checklist_original" in st.session_state:
        st.info("공고 분석 없이 저장소 샘플로 시험 중이에요. 이 체크리스트는 위 입력에서 만든 결과가 아닙니다.")
    else:
        st.info("위에서 분석하기를 누르면 체크리스트가 여기에 나와요. 분석 없이 화면만 시험하려면 샘플로 시작하세요.")
    if "checklist_original" not in st.session_state:
        if st.button("샘플 체크리스트로 확인 시작", key="start_sample"):
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
    st.caption("요구사항·키워드·유형·필수/우대를 고칠 수 있습니다. 항목 ID·요구 연수와 항목 수는 바뀌지 않습니다.")
    st.caption("키워드 칸을 더블클릭한 뒤 입력하고 Enter를 눌러 추가하세요. 각 키워드를 지워서 수정할 수 있습니다.")
    rows = st.data_editor(
        # 요구 연수는 보여 주기만 하므로 "3년" / "-" 글자로 바꿔 그린다. 저장할 때는 원래 값을 쓴다.
        [{**row, "years": years_label(row["years"])} for row in checklist_rows(original)],
        key="checklist_editor",
        num_rows="fixed",
        hide_index=True,
        disabled=["id", "years"],
        column_config={
            "id": st.column_config.TextColumn("항목 ID", width="small"),
            "years": st.column_config.TextColumn(
                "요구 연수",
                help="공고에서 읽은 요구 연수입니다. '-'는 요구 연수가 없는 항목입니다.",
                width="small",
            ),
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
        experience = st.session_state.get(EXPERIENCE_KEY)
        if isinstance(candidate, dict) and isinstance(experience, dict):
            case_id = candidate.get("case_id")
            if experience.get("case_id") == case_id:
                drafts = st.session_state.setdefault(DRAFTS_KEY, {}).setdefault(case_id, {})
                years_drafts = st.session_state.setdefault(YEARS_DRAFTS_KEY, {}).setdefault(case_id, {})
                for row in experience.get("experiences", []):
                    if isinstance(row, dict) and isinstance(row.get("item_id"), str):
                        drafts.setdefault(row["item_id"], row.get("text", ""))
                        years_drafts.setdefault(row["item_id"], row.get("years"))
    for error in errors:
        st.error(error)
    if errors:
        st.warning("위 오류를 해결해야 확인 완료하거나 다운로드할 수 있습니다.")

    if st.button("확인 완료", key="confirm_checklist", disabled=bool(errors)):
        st.session_state.checklist_confirmed = mark_reviewed(candidate)
        # 분석한 케이스면 확인한 체크리스트를 저장하고 경험 초안을 받아 온다 (C안: 미리 채우고 사람이 확인).
        fetch_draft_for_active_case(st.session_state.checklist_confirmed)
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
    st.write("공고와 이력서를 넣고 분석하면 체크리스트와 경험 초안을 만들어 드려요. 샘플로 흐름만 시험해 볼 수도 있어요.")
    render_inputs()
    st.divider()
    render_checklist()
    st.divider()
    # 경험 입력 화면에서 경험을 확인한 다음 스타일 고르기 화면을 표시한다.
    from app.experience_input import render_experience_input
    from app.style_select import render_style_step

    checklist = st.session_state.get("checklist_confirmed")
    # 분석한 케이스면 분석할 때 쓴 이력서를, 샘플이면 지금 입력란의 이력서를 옆에 보여 준다.
    active = st.session_state.get(ACTIVE_CASE_KEY)
    if isinstance(active, dict) and isinstance(checklist, dict) and active["case_id"] == checklist.get("case_id"):
        resume_for_reference = active["resume_text"]
    else:
        resume_for_reference = st.session_state.get("resume", "")
    experience = render_experience_input(checklist, resume_for_reference)
    if checklist is not None and experience is not None:
        render_style_step(checklist)


if __name__ == "__main__":
    main()
