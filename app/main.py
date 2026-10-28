"""입력 준비와 샘플 체크리스트 편집 화면. 실행: streamlit run app/main.py."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

import streamlit as st

# Streamlit을 저장소 밖에서 실행해도 같은 앱 모듈을 가져온다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.frontend import (  # noqa: E402
    checklist_json,
    checklist_rows,
    merge_checklist_edits,
    prepare_job_text,
    validate_checklist,
)
from scoring.score import score_case  # noqa: E402


SAMPLE_PATH = Path(__file__).resolve().parents[1] / "samples" / "checklist.sample.json"
REWRITE_SAMPLE_PATH = Path(__file__).resolve().parents[1] / "samples" / "rewrite.sample.json"
STYLE_ORDER = {"achievement": 0, "keyword": 1, "concise": 2}


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
    """인수 없이 공고·회사정보 입력과 TXT 다운로드를 표시한다."""
    st.header("1. 채용공고와 회사정보")
    st.write("채용공고와 회사정보를 붙여 넣어 주세요.")
    job_posting = st.text_area(
        "채용공고",
        key="job_posting",
        height=180,
        help="직무 개요, 담당 업무, 자격요건, 우대사항을 포함해 공고 내용을 붙여 넣어 주세요.",
    )
    company_info = st.text_area(
        "회사정보 (선택)",
        key="company_info",
        height=140,
        help="사업내용과 인재상처럼 확인된 정보를 붙여 넣어 주세요. 재무·SWOT·경쟁사·최근 이슈는 v0 입력에 포함하지 않습니다.",
    )
    st.caption("입력은 현재 세션에만 유지되며 앱이 파일로 자동 저장하지 않습니다. 새로고침하거나 세션이 끝나면 사라질 수 있습니다.")
    st.caption("TXT 다운로드 준비를 누른 시점의 내용으로 파일을 만듭니다. 입력을 고친 뒤에는 다시 준비해 주세요.")
    st.caption("v0에서는 이력서 원문을 붙여 넣지 않습니다. 이력서로 경험 칸을 미리 채우는 기능은 v1 후보입니다.")

    job_text = ""
    try:
        job_text = prepare_job_text(company_info, job_posting)
    except ValueError as error:
        st.caption(f"공고 TXT 준비: {error}")
    render_txt_download(job_text, "회사정보·공고", "jd.txt", "prepared_job_text")


def start_sample() -> None:
    """인수 없이 저장소 샘플을 읽어 검증하고 편집 시작 데이터를 세션에 넣는다."""
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    sample.setdefault("reviewed", False)
    errors = validate_checklist(sample)
    if errors:
        raise ValueError("\n".join(errors))
    st.session_state.checklist_original = sample
    st.session_state.checklist_draft = deepcopy(sample)


def render_checklist() -> None:
    """인수 없이 샘플 편집 표와 항목별 오류를 표시하고 유효한 JSON 다운로드를 제공한다."""
    st.header("2. 샘플 체크리스트 편집")
    st.info("공고 파싱과 AI 첨삭은 아직 연결되지 않았습니다. 아래 샘플은 위 입력 내용에서 생성한 결과가 아닙니다.")
    if "checklist_original" not in st.session_state:
        if st.button("샘플 체크리스트 편집 시작", key="start_sample", type="primary"):
            try:
                start_sample()
            except (OSError, ValueError) as error:
                st.error(f"샘플을 불러오지 못했습니다: {error}")
                return
        else:
            return

    original = st.session_state.checklist_original
    st.write(f"샘플 직무: **{original.get('job_title') or '직무 미지정'}**")
    st.caption("요구사항과 키워드를 수정할 수 있습니다. 항목 ID·유형·필수/우대 구분과 항목 수는 유지됩니다.")
    st.caption("키워드 칸을 더블클릭한 뒤 입력하고 Enter를 눌러 추가하세요. 각 키워드를 지워서 수정할 수 있습니다.")
    rows = st.data_editor(
        checklist_rows(original),
        key="checklist_editor",
        num_rows="fixed",
        hide_index=True,
        disabled=["id", "type", "level"],
        column_config={
            "id": st.column_config.TextColumn("항목 ID", width="small"),
            "text": st.column_config.TextColumn("요구사항", width="large"),
            "keywords": st.column_config.ListColumn("키워드", width="medium"),
            "type": st.column_config.TextColumn("유형", width="small"),
            "level": st.column_config.TextColumn("필수/우대", width="small"),
        },
    )
    try:
        candidate = merge_checklist_edits(original, rows)
        st.session_state.checklist_draft = candidate
        errors = validate_checklist(candidate)
    except ValueError as error:
        candidate = None
        errors = [str(error)]

    confirmed_candidate = deepcopy(candidate) if candidate is not None else None
    if confirmed_candidate is not None:
        confirmed_candidate["reviewed"] = True
    if st.session_state.get("checklist_confirmed") != confirmed_candidate:
        st.session_state.pop("checklist_confirmed", None)
    for error in errors:
        st.error(error)
    if errors:
        st.warning("위 오류를 해결해야 편집 내용을 확정하거나 다운로드할 수 있습니다.")

    if st.button("편집 내용 확정", key="confirm_checklist", disabled=bool(errors)):
        st.session_state.checklist_confirmed = deepcopy(confirmed_candidate)
    if "checklist_confirmed" in st.session_state:
        st.success("샘플 편집 내용을 확정했습니다. 현재 세션에서 유지됩니다.")
        st.download_button(
            "확정한 체크리스트 JSON 다운로드",
            data=checklist_json(st.session_state.checklist_confirmed),
            file_name="checklist.json",
            mime="application/json",
            on_click="ignore",
        )
    elif not errors:
        st.caption("편집 내용을 확정하면 JSON을 다운로드할 수 있습니다. 다시 수정한 뒤에는 한 번 더 확정해 주세요.")
    st.caption("다운로드에는 원본 메타데이터와 기존 필드가 그대로 포함됩니다. 이후 파싱·첨삭 연결은 준비 중입니다.")
    if "checklist_confirmed" in st.session_state:
        render_experience_inputs(st.session_state.checklist_confirmed)


def render_experience_inputs(checklist: dict) -> None:
    """확정 checklist를 받아 항목별 경험 응답을 입력하고 완성된 응답을 세션에 저장한다."""
    st.header("3. 항목별 경험 입력")
    st.caption("각 항목에 경험 원문을 입력하거나, 관련 경험이 없으면 직접 선택해 주세요. 빈칸은 경험 없음으로 처리하지 않습니다.")
    responses = []
    answer_snapshot = {}
    incomplete = []
    for item in checklist["items"]:
        item_id = item["id"]
        st.markdown(f"**{item_id} · {item['level']} · {item['type']}** — {item['text']}")
        selected = st.radio(
            f"{item_id} 경험 응답",
            options=("선택", "경험 있음", "경험 없음"),
            key=f"experience_status_{item_id}",
            horizontal=True,
            label_visibility="collapsed",
        )
        if selected == "경험 없음":
            answer_snapshot[item_id] = {"status": "경험 없음"}
        elif selected == "경험 있음":
            text = st.text_area(
                f"{item_id} 경험 원문",
                key=f"experience_text_{item_id}",
                height=100,
            )
            if text.strip():
                responses.append({"item_id": item_id, "text": text})
                answer_snapshot[item_id] = {"status": "경험 있음", "text": text}
            else:
                incomplete.append(item_id)
        else:
            incomplete.append(item_id)
            answer_snapshot[item_id] = {"status": "미작성"}

    response_payload = _build_experience_payload(checklist["case_id"], responses)
    complete = len(answer_snapshot) == len(checklist["items"]) and not incomplete
    if not complete:
        st.warning(f"채점을 시작하려면 모든 항목에 응답해 주세요. 미작성: {', '.join(incomplete)}")

    confirmed_key = "experience_confirmed"
    snapshot_key = "experience_answer_snapshot"
    if st.session_state.get(snapshot_key) != answer_snapshot:
        st.session_state.pop(confirmed_key, None)
    if st.button("경험 응답 확정", key="confirm_experience", disabled=not complete):
        st.session_state[confirmed_key] = deepcopy(response_payload)
        st.session_state[snapshot_key] = deepcopy(answer_snapshot)
    if confirmed_key in st.session_state:
        st.success("모든 항목의 경험 응답을 확정했습니다.")
        render_result_screen(checklist, st.session_state[confirmed_key])


def _build_experience_payload(case_id: str, experience_rows: list[dict]) -> dict:
    """케이스 ID와 경험 있는 항목의 원문 목록을 받아 schema_version이 포함된 payload를 반환한다."""
    return {
        "case_id": case_id,
        "schema_version": 1,
        "experiences": [
            {"item_id": row["item_id"], "text": row["text"]}
            for row in experience_rows
        ],
    }


def _load_rewrite_uploads(uploaded_files) -> tuple[list[dict], list[str]]:
    """업로드된 rewrite JSON 파일들을 받아 결과 객체 목록과 오류 목록을 반환한다."""
    rewrites = []
    errors = []
    for uploaded in uploaded_files or []:
        try:
            value = json.loads(uploaded.getvalue().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            errors.append(f"{uploaded.name}: JSON을 읽을 수 없습니다 ({error}).")
            continue
        if not isinstance(value, dict):
            errors.append(f"{uploaded.name}: rewrite 결과는 JSON 객체여야 합니다.")
            continue
        rewrites.append(value)
    return rewrites, errors


def _input_signature(checklist: dict, experience: dict, rewrites: list[dict]) -> str:
    """현재 입력을 받아 재시도 이력 비교용 정렬 JSON 문자열을 반환한다."""
    return json.dumps(
        {"checklist": checklist, "experience": experience, "rewrites": rewrites},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def render_result_screen(checklist: dict, experience: dict) -> None:
    """확정 checklist·experience를 받아 rewrite 업로드, 채점 결과와 attempt 이력을 표시한다."""
    st.header("4. 최종 결과와 점수")
    uploaded_files = st.file_uploader(
        "첨삭 결과 JSON 파일을 올려 주세요. 여러 스타일 결과를 함께 선택할 수 있습니다.",
        type=["json"],
        accept_multiple_files=True,
        key="rewrite_json_uploads",
    )
    rewrites, errors = _load_rewrite_uploads(uploaded_files)
    for error in errors:
        st.error(error)

    use_sample = st.checkbox("화면 흐름 확인용 샘플 첨삭 결과 사용", key="use_sample_rewrite")
    if use_sample:
        sample_rewrite = json.loads(REWRITE_SAMPLE_PATH.read_text(encoding="utf-8"))
        rewrites = [sample_rewrite]
        st.caption("저장소의 가짜 rewrite 샘플입니다. 실제 사용자 결과가 아닙니다.")
    else:
        st.session_state.pop("score_preview", None)
    rewrites.sort(key=lambda rewrite: STYLE_ORDER.get(_rewrite_style(rewrite), len(STYLE_ORDER)))

    if not rewrites:
        st.info("loop에서 받은 rewrite JSON을 올리면 원문·첨삭문과 항목별 점수를 확인할 수 있습니다.")
    history = st.session_state.setdefault("score_history", [])
    current_signature = _input_signature(checklist, experience, rewrites) if rewrites else None
    active_attempt_id = st.session_state.get("active_score_attempt_id")
    active_attempt = next(
        (entry for entry in history if entry["attempt_id"] == active_attempt_id),
        None,
    )
    if not use_sample and active_attempt is not None and current_signature != active_attempt["input_signature"]:
        st.warning("입력이 변경되었습니다 · 최신 결과를 보려면 다시 채점해 주세요.")

    if st.button("채점하고 결과 보기", key="score_rewrites", disabled=not rewrites or bool(errors)):
        styles = [_rewrite_style(rewrite) for rewrite in rewrites]
        batch_error = _style_batch_error(styles, is_first_attempt=not history, use_sample=use_sample)
        if batch_error:
            st.error(batch_error)
            return
        if active_attempt is not None and active_attempt["input_signature"] == current_signature:
            st.session_state.active_score_attempt_id = active_attempt["attempt_id"]
        else:
            number = max((entry["number"] for entry in history), default=0) + 1
            attempt_id = f"attempt-{uuid4().hex[:12]}"
            results = []
            try:
                for rewrite in rewrites:
                    candidate = deepcopy(rewrite)
                    candidate["attempt"] = number
                    candidate["attempt_id"] = attempt_id
                    results.append({
                        "rewrite": candidate,
                        "score": score_case(checklist, experience, candidate),
                    })
            except (KeyError, TypeError, ValueError) as error:
                st.error(f"채점하지 못했습니다: {error}")
                return
            entry = {
                "attempt_id": attempt_id,
                "number": number,
                "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "input_signature": current_signature,
                "results": results,
            }
            if use_sample:
                st.session_state.score_preview = entry
            else:
                history.append(entry)
                st.session_state.active_score_attempt_id = attempt_id
                active_attempt = entry

    active_attempt_id = st.session_state.get("active_score_attempt_id")
    active_attempt = next(
        (entry for entry in history if entry["attempt_id"] == active_attempt_id),
        None,
    )
    if use_sample and "score_preview" in st.session_state:
        _render_attempt_results(st.session_state.score_preview, experience)
    elif active_attempt is not None:
        _render_attempt_results(active_attempt, experience)
    if history:
        st.subheader("시도 이력")
        for entry in reversed(history):
            style_names = ", ".join(result["score"]["style_id"] for result in entry["results"])
            with st.expander(f"{entry['number']}차 · {style_names} · {entry['created_at']}"):
                for result in entry["results"]:
                    summary = ", ".join(
                        f"{item['item_id']} {item['score']['earned']}/{item['score']['max']}점 ({item['status']})"
                        for item in result["score"]["items"]
                    )
                    st.write(f"**{result['score']['style_id']}**: {summary}")
                    st.caption(f"품질 경고 {len(result['score']['issues'])}건")


def _rewrite_style(rewrite: dict) -> str:
    """rewrite 결과를 받아 한글 또는 영문 스타일 식별자를 반환한다."""
    style_names = {
        "성과 강조형": "achievement",
        "키워드 맞춤형": "keyword",
        "간결형": "concise",
    }
    value = rewrite.get("style_id", rewrite.get("style"))
    if not isinstance(value, str):
        return "unknown"
    return style_names.get(value, value)


def _style_batch_error(styles: list[str], is_first_attempt: bool, use_sample: bool) -> str | None:
    """스타일 목록과 attempt 유형을 받아 업로드 구성이 잘못됐으면 안내 문구를 반환한다."""
    if len(styles) != len(set(styles)):
        return "같은 스타일의 rewrite를 두 개 이상 선택했습니다."
    if use_sample:
        return None
    if is_first_attempt and set(styles) != set(STYLE_ORDER):
        return "첫 attempt에는 세 스타일(achievement, keyword, concise)의 rewrite가 모두 필요합니다."
    if not is_first_attempt and len(styles) != 1:
        return "재작업 attempt에는 사용자가 선택한 한 스타일의 rewrite만 올려 주세요."
    return None


def _render_attempt_results(attempt: dict, experience: dict) -> None:
    """한 attempt 결과와 경험 원문을 받아 스타일별 비교·상태·점수·feedback을 표시한다."""
    st.subheader(f"{attempt['number']}차 결과")
    for result in attempt["results"]:
        score = result["score"]
        rewrite = result["rewrite"]
        sentences = {sentence["item_id"]: sentence for sentence in rewrite.get("sentences", [])}
        experience_by_id = {row["item_id"]: row for row in experience["experiences"]}
        st.markdown(f"### {score['style_id']}")
        if score["needs_revision"]:
            st.warning("재검토가 필요한 항목 또는 품질 경고가 있습니다.")
        else:
            st.success("모든 항목이 충족되었고 품질 경고가 없습니다.")
        for item_score in score["items"]:
            item_id = item_score["item_id"]
            source_response = experience_by_id[item_id]
            sentence = sentences.get(item_id, {})
            source_text = source_response.get("text") or "경험 없음"
            output_text = sentence.get("text") or "첨삭 문장 없음"
            st.markdown(f"#### {item_id} · {item_score['status']} · {item_score['score']['earned']}/{item_score['score']['max']}점")
            original_column, rewrite_column = st.columns(2)
            with original_column:
                st.markdown("**원문 경험**")
                st.write(source_text)
            with rewrite_column:
                st.markdown("**첨삭 문장**")
                st.write(output_text)
            st.caption(item_score["reason"])
            numeric_check = next(
                (check for check in item_score["checks"] if check["code"] == "NUMERIC_EVIDENCE_PRESENT"),
                None,
            )
            if numeric_check:
                st.caption(f"수치 근거: {'있음' if numeric_check['result'] == 'pass' else '없음' if numeric_check['result'] == 'fail' else '해당 없음'} · {numeric_check['reason']}")
            for issue in score["issues"]:
                if issue["item_id"] == item_id:
                    st.warning(f"{issue['value']}: {issue['reason']}")
        with st.expander("다음 재작성에 전달할 feedback"):
            st.code(score["feedback"] or "추가 feedback 없음", language=None)


def main() -> None:
    """인수 없이 세로 한 열의 Streamlit 시작 화면을 그린다."""
    st.set_page_config(page_title="이력서 스터디: 입력과 체크리스트", layout="centered")
    st.title("이력서 입력과 체크리스트")
    st.write("지원 자료를 준비하고, 샘플로 체크리스트 편집 흐름을 확인해 보세요.")
    render_inputs()
    st.divider()
    render_checklist()


if __name__ == "__main__":
    main()
