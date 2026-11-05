"""선택한 스타일의 rewrite·score 이력으로 최종 리포트를 그린다."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.style_select import style_label  # noqa: E402


def _pair_attempt(
    rewrite: dict[str, Any],
    score: dict[str, Any],
    case_id: str,
    style_id: str,
) -> dict[str, Any]:
    """rewrite와 score를 받아 case·style·차수가 맞는 시도 객체를 반환한다."""
    rewrite_key = (
        rewrite.get("case_id"),
        rewrite.get("style_id"),
        rewrite.get("attempt"),
    )
    score_key = (
        score.get("case_id"),
        score.get("style_id"),
        score.get("attempt"),
    )
    if rewrite_key != score_key:
        raise ValueError("rewrite와 score의 case_id, style_id, attempt가 일치해야 합니다.")
    if rewrite_key[:2] != (case_id, style_id):
        raise ValueError("리포트 입력의 case_id와 style_id가 선택한 값과 일치해야 합니다.")
    attempt = rewrite_key[2]
    if not isinstance(attempt, int) or isinstance(attempt, bool) or not 1 <= attempt <= 4:
        raise ValueError("attempt는 1부터 4까지의 정수여야 합니다.")
    if not isinstance(score.get("passed"), bool):
        raise ValueError("score.passed는 true 또는 false여야 합니다.")
    return {"attempt": attempt, "rewrite": rewrite, "score": score}


def _score_metrics(
    checklist: dict[str, Any], experience: dict[str, Any], score: dict[str, Any]
) -> dict[str, int]:
    """체크리스트·경험·score를 받아 리포트에 표시할 항목 수를 반환한다."""
    # "평가 대상 필수"는 AGENTS.md 통과 규칙과 같다: 필수 + 기타가 아님 + 경험을 입력함.
    # 통과 규칙이 바뀌면 scoring/score.py와 함께 이 부분도 맞춘다. passed는 여기서 다시 계산하지 않는다.
    experience_by_id = {
        row.get("item_id"): row.get("text", "")
        for row in experience.get("experiences", [])
        if isinstance(row, dict)
    }
    score_by_id = {
        row.get("item_id"): row
        for row in score.get("items", [])
        if isinstance(row, dict)
    }
    required_ids = {
        item.get("id")
        for item in checklist.get("items", [])
        if isinstance(item, dict)
        and item.get("level") == "필수"
        and item.get("type") != "기타"
        and isinstance(experience_by_id.get(item.get("id")), str)
        and experience_by_id[item.get("id")].strip()
    }
    return {
        "required_met": sum(
            score_by_id.get(item_id, {}).get("status") == "충족"
            for item_id in required_ids
        ),
        "required_total": len(required_ids),
        "made_up_numbers": len(score.get("made_up_numbers", [])),
        "ai_phrases": len(score.get("ai_phrases", [])),
    }


def _build_report_data(
    checklist: dict[str, Any],
    experience: dict[str, Any],
    selected_style_id: str,
    first_rewrite: dict[str, Any],
    first_score: dict[str, Any],
    retry_history: list[dict[str, Any]],
    input_signature: str | None = None,
) -> dict[str, Any]:
    """최종 리포트 입력을 받아 짝이 맞는 시도와 화면 표시용 요약을 반환한다.

    retry_history는 다시 쓴 문장 채점 이력(rewrite_score_history) 모양이다.
    경험을 고친 뒤 다시 채점하면 같은 attempt가 두 번 생기므로, input_signature를 주면
    그 값이 같은 이력만 쓴다. 이력 항목에 input_signature가 없으면 거르지 않는다.
    """
    case_id = checklist.get("case_id")
    if experience.get("case_id") != case_id:
        raise ValueError("checklist와 experience의 case_id가 일치해야 합니다.")
    if checklist.get("reviewed") is not True:
        raise ValueError("최종 리포트에는 확인 완료한 checklist가 필요합니다.")

    attempts = [_pair_attempt(first_rewrite, first_score, case_id, selected_style_id)]
    if attempts[0]["attempt"] != 1:
        raise ValueError("첫 rewrite와 score의 attempt는 1이어야 합니다.")

    for entry in retry_history:
        if not isinstance(entry, dict):
            raise ValueError("재작성 이력의 각 항목은 객체여야 합니다.")
        if (
            input_signature is not None
            and "input_signature" in entry
            and entry["input_signature"] != input_signature
        ):
            continue
        rewrite = entry.get("rewrite")
        score = entry.get("score")
        if not isinstance(rewrite, dict) or not isinstance(score, dict):
            if entry.get("style_id") == selected_style_id:
                raise ValueError("선택한 스타일의 재작성 이력에는 rewrite와 score가 모두 필요합니다.")
            continue

        rewrite_key = (
            rewrite.get("case_id"),
            rewrite.get("style_id"),
            rewrite.get("attempt"),
        )
        score_key = (
            score.get("case_id"),
            score.get("style_id"),
            score.get("attempt"),
        )
        if rewrite_key != score_key:
            raise ValueError("rewrite와 score의 case_id, style_id, attempt가 일치해야 합니다.")
        if rewrite.get("case_id") != case_id or rewrite.get("style_id") != selected_style_id:
            continue
        attempts.append(_pair_attempt(rewrite, score, case_id, selected_style_id))

    attempts.sort(key=lambda row: row["attempt"])
    attempt_numbers = [row["attempt"] for row in attempts]
    duplicated = sorted({number for number in attempt_numbers if attempt_numbers.count(number) > 1})
    if duplicated:
        raise ValueError(
            f"같은 attempt({', '.join(map(str, duplicated))})가 두 번 이상 있습니다. "
            "지금 입력의 이력만 넘기거나 input_signature를 함께 넘겨 주세요."
        )
    if attempt_numbers != list(range(1, len(attempt_numbers) + 1)):
        raise ValueError("재작성 attempt는 1부터 빠짐없이 이어져야 합니다.")

    final_attempt = next(
        (attempt for attempt in attempts if attempt["score"]["passed"] is True),
        attempts[-1],
    )
    first_attempt = attempts[0]
    experience_by_id = {
        row.get("item_id"): row.get("text", "")
        for row in experience.get("experiences", [])
        if isinstance(row, dict)
    }
    final_sentences = {
        row.get("item_id"): row
        for row in final_attempt["rewrite"].get("sentences", [])
        if isinstance(row, dict)
    }
    final_score_items = {
        row.get("item_id"): row
        for row in final_attempt["score"].get("items", [])
        if isinstance(row, dict)
    }
    sentence_rows = []
    missing_experiences = []
    for item in checklist.get("items", []):
        item_id = item.get("id")
        score_item = final_score_items.get(item_id, {})
        sentence = final_sentences.get(item_id, {})
        if score_item.get("status") == "경험 없음":
            missing_experiences.append(item)
        sentence_rows.append(
            {
                "item_id": item_id,
                "item_text": item.get("text", ""),
                "source": experience_by_id.get(item_id, ""),
                "text": sentence.get("text", ""),
                "status": score_item.get("status", "판정 없음"),
                "reason": score_item.get("reason", ""),
            }
        )

    return {
        "case_id": case_id,
        "style_id": selected_style_id,
        "first": {
            **first_attempt,
            "metrics": _score_metrics(checklist, experience, first_attempt["score"]),
        },
        "final": {
            **final_attempt,
            "metrics": _score_metrics(checklist, experience, final_attempt["score"]),
        },
        "rewrite_count": max(0, final_attempt["attempt"] - 1),
        "sentences": sentence_rows,
        "missing_experiences": missing_experiences,
    }


def _final_sentences_text(report: dict[str, Any]) -> str:
    """리포트 데이터를 받아 최종 문장만 순서대로 담은 TXT 문자열을 반환한다.

    "경험 없음" 항목의 문장은 지어낸 경험이므로 넣지 않는다.
    """
    sentences = [
        row.get("text", "")
        for row in report.get("sentences", [])
        if isinstance(row.get("text"), str)
        and row["text"].strip()
        and row.get("status") != "경험 없음"
    ]
    return "\n".join(sentences) + ("\n" if sentences else "")


def render_report(
    checklist: dict[str, Any],
    experience: dict[str, Any],
    selected_style_id: str,
    first_rewrite: dict[str, Any],
    first_score: dict[str, Any],
    retry_history: list[dict[str, Any]],
    input_signature: str | None = None,
) -> None:
    """체크리스트·경험·선택 스타일의 rewrite와 score 이력을 받아 최종 리포트를 그린다.

    input_signature를 주면 그 값이 같은 재작성 이력만 쓴다(_build_report_data 참고).
    """
    try:
        report = _build_report_data(
            checklist,
            experience,
            selected_style_id,
            first_rewrite,
            first_score,
            retry_history,
            input_signature,
        )
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        st.error(f"최종 리포트를 만들 수 없습니다: {error}")
        return

    st.header("최종 리포트")
    style_name = style_label(report["style_id"])
    st.caption(f"케이스 {report['case_id']} · 선택 스타일 {style_name}")
    if report["final"]["score"]["passed"] is True:
        st.success(f"최종 결과: 통과 · {report['final']['attempt']}차")
    else:
        st.warning(f"최종 결과: 미통과 · {report['final']['attempt']}차")

    st.subheader("최종 문장")
    for row in report["sentences"]:
        st.markdown(f"**{row['item_id']} · {row['item_text']}**")
        left, right = st.columns(2)
        with left:
            st.caption("원문 경험")
            st.write(row["source"] or "경험 없음")
        with right:
            st.caption("최종 문장")
            st.write(row["text"] or "문장 없음")
        st.caption(f"상태: {row['status']} · 이유: {row['reason'] or '기록 없음'}")

    final_text = _final_sentences_text(report)
    if report["final"]["score"]["passed"] is not True:
        st.warning(
            "통과하지 못한 결과입니다. 지어낸 숫자나 AI 표현이 남아 있을 수 있으니 "
            "위 상태와 이유를 확인한 뒤 쓰세요. 경험 없음 항목의 문장은 TXT에 넣지 않습니다."
        )
    st.download_button(
        "최종 문장 TXT 다운로드",
        data=final_text,
        file_name="최종_이력서_문장.txt",
        mime="text/plain; charset=utf-8",
        disabled=not bool(final_text),
        on_click="ignore",
    )

    first_metrics = report["first"]["metrics"]
    final_metrics = report["final"]["metrics"]
    st.subheader("1차 → 최종 변화")
    st.write(
        "평가 대상 필수 충족: "
        f"{first_metrics['required_met']} / {first_metrics['required_total']} → "
        f"{final_metrics['required_met']} / {final_metrics['required_total']}"
    )
    st.write(
        "지어낸 숫자: "
        f"{first_metrics['made_up_numbers']} → {final_metrics['made_up_numbers']}"
    )
    st.write(
        "AI 표현: "
        f"{first_metrics['ai_phrases']} → {final_metrics['ai_phrases']}"
    )
    st.write(f"다시 쓴 횟수: 0 → {report['rewrite_count']}")

    st.subheader("보완할 경험")
    if report["missing_experiences"]:
        for item in report["missing_experiences"]:
            st.write(f"- {item['id']} · {item['text']}")
    else:
        st.write("경험 없음으로 판정된 항목이 없습니다.")


def _sample_report_inputs() -> tuple[Any, ...]:
    """저장소 샘플을 받아 통과 전후를 보여 주는 가짜 리포트 인자 묶음을 반환한다."""
    from scoring.score import score_case

    checklist = json.loads((SAMPLES / "checklist.sample.json").read_text(encoding="utf-8"))
    checklist["reviewed"] = True
    experience = json.loads((SAMPLES / "experience.sample.json").read_text(encoding="utf-8"))
    rewrite_bundle = json.loads((SAMPLES / "rewrite.sample.json").read_text(encoding="utf-8"))
    candidate = next(
        row for row in rewrite_bundle["revised_cv"] if row.get("style") == "achievement"
    )
    base_rewrite = {
        "schema_version": rewrite_bundle["schema_version"],
        "case_id": rewrite_bundle["case_id"],
        "prompt_version": rewrite_bundle["prompt_version"],
        "attempt": 1,
        "style_id": candidate["style"],
        "sentences": deepcopy(candidate["sentences"]),
    }

    first_rewrite = deepcopy(base_rewrite)
    for sentence in first_rewrite["sentences"]:
        if sentence["item_id"] == "req-2":
            sentence["text"] = "3년간 Python으로 엑셀 정리 자동화에 적극적으로 기여했습니다."
    first_score = score_case(checklist, experience, first_rewrite)

    final_rewrite = deepcopy(base_rewrite)
    final_rewrite["attempt"] = 2
    final_score = score_case(checklist, experience, final_rewrite)
    return (
        checklist,
        experience,
        "achievement",
        first_rewrite,
        first_score,
        [{"rewrite": final_rewrite, "score": final_score}],
    )


if __name__ == "__main__":
    st.set_page_config(page_title="최종 리포트 미리보기", layout="wide")
    st.caption("저장소 샘플로 구성한 최종 리포트 미리보기입니다.")
    render_report(*_sample_report_inputs())
