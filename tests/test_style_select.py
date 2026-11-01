"""4단계 스타일 고르기 화면의 데이터 맞춰 보기와 화면 흐름을 검증한다."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest

from app.style_select import (
    check_first_attempt,
    experience_from_rewrite,
    pair_scores,
    rewrites_by_style,
    score_passed,
    style_summary,
)
from tests.streamlit_support import streamlit_apptest_supported


ROOT = Path(__file__).resolve().parents[1]

CHECKLIST = {
    "schema_version": 1,
    "case_id": "case-01",
    "job_title": "데이터 분석가",
    "company_values": [],
    "reviewed": True,
    "items": [
        {"id": "req-1", "text": "SQL 활용 능력", "keywords": ["SQL"], "type": "기술", "level": "필수"},
        {"id": "req-2", "text": "Python 3년 이상", "keywords": ["Python", "파이썬"], "type": "경력", "level": "필수"},
        {"id": "req-3", "text": "대용량 데이터 처리 경험", "keywords": ["대용량"], "type": "기술", "level": "우대"},
    ],
}
EXPERIENCE = {
    "schema_version": 1,
    "case_id": "case-01",
    "experiences": [
        {"item_id": "req-1", "text": "SQL로 고객 데이터 뽑아서 대시보드 만듦"},
        {"item_id": "req-2", "text": "Python으로 엑셀 정리 자동화, 2년 정도 사용"},
    ],
}


def loop_output() -> dict:
    """인수 없이 루프팀 PR #12 모양(revised_cv에 세 스타일 묶음)의 첫 생성 결과를 만들어 돌려준다."""
    def sentences(suffix: str) -> list[dict]:
        return [
            {"item_id": "req-1", "source": "SQL로 고객 데이터 뽑아서 대시보드 만듦", "text": f"SQL로 대시보드를 만들었습니다{suffix}", "llm_opinion": "이유", "user_feedback": ""},
            {"item_id": "req-2", "source": "Python으로 엑셀 정리 자동화, 2년 정도 사용", "text": f"약 2년간 Python으로 자동화했습니다{suffix}", "llm_opinion": "이유", "user_feedback": ""},
        ]

    return {
        "schema_version": 1,
        "case_id": "case-01",
        "prompt_version": "rewrite_v1",
        "attempt": 1,
        "style": "",
        "revised_cv": [
            {"attempt": 1, "style": "achievement", "sentences": sentences(".")},
            {"attempt": 1, "style": "keyword", "sentences": sentences("!")},
            {"attempt": 1, "style": "concise", "sentences": sentences("~")},
        ],
    }


def score_for(style_id: str, **overrides) -> dict:
    """style_id를 받아 그 스타일의 첫 생성과 짝이 되는 최소 score를 만들어 돌려준다."""
    score = {
        "schema_version": 1,
        "case_id": "case-01",
        "style_id": style_id,
        "attempt": 1,
        "passed": True,
        "items": [
            {"item_id": "req-1", "status": "충족", "reason": "'SQL' 키워드가 결과 문안에 있습니다."},
            {"item_id": "req-2", "status": "충족", "reason": "'Python' 키워드가 결과 문안에 있습니다. 연수 미확인."},
            {"item_id": "req-3", "status": "경험 없음", "reason": "확정한 경험 입력에 이 항목이 없습니다."},
        ],
        "made_up_numbers": [],
        "ai_phrases": [],
        "feedback": "",
    }
    score.update(overrides)
    return score


class SplitRewritesTests(unittest.TestCase):
    """루프 결과를 스타일별 rewrite로 나누는지 검증한다."""

    def test_bundle_is_split_into_three_styles_with_pair_keys(self):
        """revised_cv 묶음을 스타일마다 나누고 case_id·style_id·attempt를 채우며 원본은 건드리지 않는다."""
        original = loop_output()
        before = deepcopy(original)
        rewrites = rewrites_by_style(original)

        self.assertEqual([rewrite["style_id"] for rewrite in rewrites], ["achievement", "keyword", "concise"])
        for rewrite in rewrites:
            self.assertEqual(rewrite["case_id"], "case-01")
            self.assertEqual(rewrite["attempt"], 1)
            self.assertEqual(rewrite["prompt_version"], "rewrite_v1")
            self.assertEqual(len(rewrite["sentences"]), 2)
            self.assertNotIn("revised_cv", rewrite)
        self.assertEqual(original, before)

    def test_single_style_with_korean_name_is_one_rewrite(self):
        """sentences가 바로 있는 스타일 하나짜리는 한 개로 담고 한글 이름을 style_id로 바꾼다."""
        single = {"case_id": "case-01", "style": "성과 강조형", "attempt": 2, "sentences": []}
        rewrites = rewrites_by_style(single)

        self.assertEqual(len(rewrites), 1)
        self.assertEqual(rewrites[0]["style_id"], "achievement")
        self.assertEqual(rewrites[0]["attempt"], 2)

    def test_sample_rewrites_have_three_styles(self):
        """루프 샘플은 저장소 어느 모양이든 세 스타일로 나뉘어 나온다 (옛 모양이면 PR #12 사본을 쓴다)."""
        from app.style_select import load_sample_rewrites

        rewrites, path = load_sample_rewrites()
        self.assertEqual(sorted(rewrite["style_id"] for rewrite in rewrites), ["achievement", "concise", "keyword"])
        self.assertTrue(path.endswith(".json"))

    def test_non_object_is_rejected(self):
        """JSON 객체가 아니거나 revised_cv가 목록이 아니면 이유와 함께 멈춘다."""
        with self.assertRaises(ValueError):
            rewrites_by_style([])
        with self.assertRaises(ValueError):
            rewrites_by_style({"revised_cv": {}})

    def test_experience_evidence_must_be_an_exact_part_of_resume(self):
        """rewrite.source를 항목별로 입력하지 않고 resume 원문에 실제로 있는지 확인한다."""
        rewrite = rewrites_by_style(loop_output())[0]
        experience = experience_from_rewrite(
            rewrite,
            "경력 요약\nSQL로 고객 데이터 뽑아서 대시보드 만듦\nPython으로 엑셀 정리 자동화, 2년 정도 사용",
        )
        self.assertEqual([row["item_id"] for row in experience["experiences"]], ["req-1", "req-2"])
        with self.assertRaisesRegex(ValueError, "이력서 원문에 없습니다"):
            experience_from_rewrite(rewrite, "resume에 source가 없음")


class CheckFirstAttemptTests(unittest.TestCase):
    """AGENTS.md에서 코드로 맞춰 보라고 한 것들을 잡는지 검증한다."""

    def test_valid_first_attempt_has_no_errors(self):
        """세 스타일이 한 번씩 있고 키가 모두 맞으면 오류가 없다."""
        self.assertEqual(check_first_attempt(CHECKLIST, EXPERIENCE, rewrites_by_style(loop_output())), [])

    def test_missing_and_duplicate_styles_are_reported(self):
        """빠진 스타일과 두 번 나온 스타일을 이름으로 알려 준다."""
        rewrites = rewrites_by_style(loop_output())
        errors = check_first_attempt(CHECKLIST, EXPERIENCE, [rewrites[0], rewrites[0]])
        joined = "\n".join(errors)

        self.assertIn("성과 강조형 결과가 2개", joined)
        self.assertIn("빠진 스타일: 키워드 맞춤형, 간결형", joined)

    def test_case_id_attempt_item_and_source_mismatches_are_reported(self):
        """case_id·attempt 불일치, 체크리스트에 없는 item_id, source 불일치를 각각 알려 준다."""
        rewrites = rewrites_by_style(loop_output())
        rewrites[0]["case_id"] = "case-99"
        rewrites[1]["attempt"] = 2
        rewrites[2]["sentences"][0]["item_id"] = "req-9"
        rewrites[2]["sentences"][1]["source"] = "다듬은 원문"
        joined = "\n".join(check_first_attempt(CHECKLIST, EXPERIENCE, rewrites))

        self.assertIn("성과 강조형: case_id(case-99)", joined)
        self.assertIn("키워드 맞춤형: 첫 생성인데 attempt가 2", joined)
        self.assertIn("간결형: 체크리스트에 없는 item_id입니다 (req-9)", joined)
        self.assertIn("간결형 req-2: source가 경험 입력 원문과 다릅니다", joined)

    def test_sentence_for_item_without_experience_is_not_a_file_error(self):
        """경험 없는 항목에 문장이 있는 건 채점이 잡을 일이라 파일 오류로 보지 않는다."""
        rewrites = rewrites_by_style(loop_output())
        rewrites[0]["sentences"].append({"item_id": "req-3", "source": "", "text": "대용량 처리 경험"})
        self.assertEqual(check_first_attempt(CHECKLIST, EXPERIENCE, rewrites), [])


class ScoreTests(unittest.TestCase):
    """score 짝짓기와 카드 요약을 검증한다."""

    def test_scores_pair_by_case_style_and_attempt(self):
        """case_id + style_id + attempt가 같은 score끼리 짝짓고, 짝이 없으면 알려 준다."""
        rewrites = rewrites_by_style(loop_output())
        paired, errors = pair_scores(rewrites, [score_for("achievement"), score_for("keyword"), score_for("concise", attempt=2)])

        self.assertEqual(set(paired), {"achievement", "keyword"})
        self.assertEqual(len(errors), 1)
        self.assertIn("간결형: 짝이 맞는 score가 없습니다", errors[0])

    def test_passed_reads_contract_field(self):
        """통과 여부는 score 계약의 passed 칸에서만 읽는다."""
        self.assertTrue(score_passed({"passed": True}))
        self.assertIsNone(score_passed({"needs_revision": True}))
        self.assertIsNone(score_passed({}))

    def test_summary_counts_required_items_with_experience_and_issue_kinds(self):
        """경험을 적은 필수 항목만 세고, 경고는 종류별로 센다. 우대·경험 없음 항목은 빼고 센다."""
        score = score_for(
            "achievement",
            items=[
                {"item_id": "req-1", "status": "충족"},
                {"item_id": "req-2", "status": "미충족"},
                {"item_id": "req-3", "status": "경험 없음"},
            ],
            made_up_numbers=[{"item_id": "req-1", "number": "3", "reason": "근거 없음"}],
            ai_phrases=[{"item_id": "req-2", "phrase": "적극적으로 기여"}],
            passed=False,
        )
        summary = style_summary(CHECKLIST, EXPERIENCE, score)

        self.assertEqual((summary["required_met"], summary["required_total"]), (1, 2))
        self.assertEqual(summary["issues"], {"지어낸 숫자": 1, "AI 표현": 1})
        self.assertFalse(summary["passed"])


@unittest.skipUnless(
    importlib.util.find_spec("streamlit") and streamlit_apptest_supported(),
    "Streamlit 미설치 또는 실행 환경에서 socketpair를 사용할 수 없습니다.",
)
class StyleSelectAppTests(unittest.TestCase):
    """4단계 화면을 실제로 그려 보고 고르기 흐름을 검증한다."""

    SCRIPT = """
import json
from app.style_select import render_style_select, rewrites_by_style
data = json.loads({data!r})
render_style_select(data["checklist"], data["experience"], rewrites_by_style(data["loop"]), data["scores"])
"""

    def app(self, scores):
        """채점 결과(없으면 None)를 받아 화면 스크립트를 만들고 한 번 그린 AppTest를 돌려준다."""
        from streamlit.testing.v1 import AppTest

        data = json.dumps(
            {"checklist": CHECKLIST, "experience": EXPERIENCE, "loop": loop_output(), "scores": scores},
            ensure_ascii=False,
        )
        return AppTest.from_string(self.SCRIPT.format(data=data), default_timeout=15).run()

    def test_choose_style_then_continue(self):
        """스타일을 고르기 전엔 버튼이 꺼져 있고, 고른 뒤 계속을 누르면 그 style_id가 세션에 남는다."""
        app = self.app([score_for(style_id) for style_id in ("achievement", "keyword", "concise")])

        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 0)
        self.assertTrue(app.button(key="confirm_style").disabled)

        app.radio(key="style_choice").set_value("keyword").run()
        self.assertEqual(app.button(key="confirm_style").label, "키워드 맞춤형으로 계속")
        app.button(key="confirm_style").click().run()

        self.assertEqual(app.session_state["selected_style_id"], "keyword")
        self.assertIn("키워드 맞춤형으로 이어서", app.success[0].value)

    def test_without_scores_keeps_preview_component_usable(self):
        """채점 결과를 전달하지 않은 단독 화면에서도 문장 미리보기가 가능하다."""
        app = self.app(None)

        self.assertFalse(app.exception)
        self.assertEqual(len(app.info), 1)

    def test_mismatched_score_blocks_choice(self):
        """짝이 안 맞는 score가 있으면 오류를 보여 주고 고르기를 막는다."""
        app = self.app([score_for("achievement"), score_for("keyword"), score_for("concise", case_id="case-99")])

        self.assertTrue(any("짝이 맞는 score가 없습니다" in error.value for error in app.error))
        self.assertEqual(len(app.radio), 0)

    def test_preview_runs_on_repository_samples(self):
        """미리보기(streamlit run app/style_select.py)가 지금 저장소 샘플로 오류 없이 세 스타일을 보여 준다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/style_select.py"), default_timeout=15).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 0)
        self.assertEqual(app.radio(key="style_choice").options, ["성과 강조형", "키워드 맞춤형", "간결형"])

    def test_main_flow_continues_from_checklist_to_style_choice(self):
        """app/main.py에서 2단계 체크리스트를 확정하면 4단계가 이어지고, 스타일을 골라 계속할 수 있다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/main.py"), default_timeout=15).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("체크리스트를 확정하면" in item.value for item in app.info))
        self.assertEqual(len(app.radio), 0)

        app.button(key="start_sample").click().run()
        app.button(key="confirm_checklist").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 0)

        app.radio(key="style_choice").set_value("concise").run()
        app.button(key="confirm_style").click().run()
        self.assertEqual(app.session_state["selected_style_id"], "concise")


if __name__ == "__main__":
    unittest.main()
