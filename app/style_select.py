"""4단계 스타일 고르기 화면: 첫 생성 3종을 나란히 보여 주고, 이어서 다듬을 스타일 하나를 고른다.

app/main.py가 2단계 다음에 render_style_step()을 부른다. 이 화면만 따로 띄울 수도 있다:
streamlit run app/style_select.py
"""

from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
# 임시: 루프 PR #12의 samples/rewrite.sample.json(세 스타일 묶음) 사본. #12가 머지되면 이 파일은 지운다.
PREVIEW_REWRITE_PATH = ROOT / "app" / "preview_rewrite.sample.json"
# 3단계 경험 입력 화면(PR #15)이 확정한 experience를 넣어 두는 세션 키
EXPERIENCE_KEY = "experience_confirmed"

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
    """score 하나를 받아 채점 코드가 적은 통과 여부를 돌려준다. 적힌 게 없으면 None.

    칸 이름(passed / needs_revision)을 아직 정하는 중이라 둘 다 읽는다.
    통과 판정은 채점 코드의 몫이라 화면은 다시 계산하지 않는다.
    """
    if isinstance(score.get("passed"), bool):
        return score["passed"]
    if isinstance(score.get("needs_revision"), bool):
        return not score["needs_revision"]
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
        if item.get("level") == "필수" and item.get("id") in entered
    ]
    statuses = {row.get("item_id"): row.get("status") for row in score.get("items", []) if isinstance(row, dict)}
    issues = {"지어낸 숫자": 0, "AI 표현": 0}
    for issue in score.get("issues", []):
        name = ISSUE_LABELS.get(issue.get("code") if isinstance(issue, dict) else None, "품질 경고")
        issues[name] = issues.get(name, 0) + 1
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
) -> str | None:
    """4단계 화면을 그린다.

    확정 체크리스트, 경험 입력, 첫 생성 스타일별 rewrite 3개, (있으면) 짝이 되는 score 3개를 받는다.
    heading이 False면 제목을 그리지 않는다(부르는 쪽이 이미 그렸을 때).
    사용자가 "계속"을 누르면 고른 style_id를 세션에 넣고 돌려준다. 아직 안 눌렀으면 None.
    """
    if heading:
        st.header("4. 스타일 고르기")
    st.caption("같은 경험으로 세 스타일을 써 봤어요. 고른 스타일로만 다듬기를 이어가요.")

    errors = check_first_attempt(checklist, experience, rewrites)
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

    _render_comparison(checklist, experience, ordered, paired)

    selected = st.session_state.get(SELECTED_STYLE_KEY)
    if selected is not None and selected != choice:
        # 계속을 누른 뒤 라디오를 바꾸면 고른 것을 풀고 다시 누르게 한다.
        st.session_state.pop(SELECTED_STYLE_KEY, None)
        selected = None
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
                text = sentences[rewrite["style_id"]].get(item_id, {}).get("text")
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
                    for issue in score.get("issues", []):
                        if issue.get("item_id") == item_id:
                            name = ISSUE_LABELS.get(issue.get("code"), "품질 경고")
                            st.warning(f"{name}: {issue.get('value')}")
                if sentence.get("llm_opinion"):
                    with st.expander("고친 이유"):
                        st.write(sentence["llm_opinion"])
        st.divider()


def load_sample_checklist() -> dict[str, Any]:
    """인수 없이 저장소 체크리스트 샘플을 읽어 돌려준다. 미리보기에서 2단계를 건너뛸 때 쓴다."""
    return json.loads((SAMPLES / "checklist.sample.json").read_text(encoding="utf-8"))


def load_sample_experience() -> dict[str, Any]:
    """인수 없이 저장소 경험 입력 샘플을 읽어 돌려준다. 샘플이 옛 모양이라 schema_version이 없으면 1로 채운다."""
    experience = json.loads((SAMPLES / "experience.sample.json").read_text(encoding="utf-8"))
    experience.setdefault("schema_version", 1)
    return experience


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


def render_style_step(checklist: dict[str, Any] | None) -> str | None:
    """app/main.py가 2단계 다음에 부르는 4단계 연결부.

    2단계에서 확정한 체크리스트(아직이면 None)를 받아 4단계 화면을 그리고, 고른 style_id(아직이면 None)를 돌려준다.
    아직 연결되지 않은 단계는 임시로 채운다.
    - 3단계 경험 입력: 세션에 확정한 경험(experience_confirmed)이 있으면 그것, 없으면 저장소 샘플
    - 루프 첫 생성: 사용자가 올린 루프 결과 JSON, 없으면 샘플(세 스타일 묶음)
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
    notes = st.expander("아직 연결되지 않은 단계는 임시 데이터로 채웠어요")
    with notes:
        uploaded = st.file_uploader(
            "루프 첫 생성 결과 JSON 올리기 (올리지 않으면 샘플을 씁니다)",
            type=["json"],
            key="style_step_upload",
        )
    try:
        if experience is None:
            experience = load_sample_experience()
            experience_note = "3단계 경험 입력: 저장소 샘플(samples/experience.sample.json)"
        else:
            experience_note = "3단계 경험 입력: 이번 세션에서 확정한 경험"
        if uploaded is not None:
            rewrites = rewrites_by_style(json.loads(uploaded.getvalue().decode("utf-8")))
            rewrite_note = f"루프 첫 생성: 올린 파일({uploaded.name})"
        else:
            rewrites, rewrite_path = load_sample_rewrites()
            rewrite_note = f"루프 첫 생성: 샘플({rewrite_path})"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        st.error(f"4단계에 넣을 데이터를 읽지 못했습니다: {error}")
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
        if uploaded is None and EXPERIENCE_KEY in st.session_state:
            st.caption("샘플 첨삭은 샘플 경험에 맞춰 쓴 글이라, 직접 적은 경험과는 원문이 달라 오류가 나요. 루프 결과 JSON을 올려 주세요.")

    return render_style_select(checklist, experience, rewrites, scores, heading=False)


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
