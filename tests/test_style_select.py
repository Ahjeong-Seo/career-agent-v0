"""4단계 스타일 고르기 화면의 데이터 맞춰 보기와 화면 흐름을 검증한다."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from app.style_select import (
    check_first_attempt,
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

    def retry_app(self, first_score):
        """첫 채점 결과를 받아 선택 스타일의 재작성 화면을 그린 AppTest를 돌려준다."""
        from streamlit.testing.v1 import AppTest

        data = json.dumps(
            {"checklist": CHECKLIST, "experience": EXPERIENCE, "score": first_score},
            ensure_ascii=False,
        )
        script = """
import json
from app.style_select import render_retry_scoring
data = json.loads({data!r})
render_retry_scoring(data["checklist"], data["experience"], "concise", data["score"])
""".format(data=data)
        return AppTest.from_string(script, default_timeout=15).run()

    def retry_rewrite(self, attempt):
        """재작성 차수를 받아 채점에서 미통과하는 선택 스타일 rewrite JSON을 돌려준다."""
        return {
            "schema_version": 1,
            "case_id": "case-01",
            "prompt_version": "rewrite_v1",
            "attempt": attempt,
            "style": "concise",
            "sentences": [
                {
                    "item_id": "req-1",
                    "source": "SQL로 고객 데이터 뽑아서 대시보드 만듦",
                    "text": "업무를 진행했습니다.",
                    "llm_opinion": "업무를 간결하게 적었습니다.",
                    "user_feedback": "",
                },
                {
                    "item_id": "req-2",
                    "source": "Python으로 엑셀 정리 자동화, 2년 정도 사용",
                    "text": "업무를 진행했습니다.",
                    "llm_opinion": "업무를 간결하게 적었습니다.",
                    "user_feedback": "",
                },
            ],
        }

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

    def test_selected_style_feedback_toggle_edits_the_existing_feedback_text(self):
        """선택한 스타일의 기존 재작성 feedback 토글에서 feedback 문장을 직접 고친다."""
        app = self.app(
            [
                score_for(style_id, passed=False, feedback=f"{style_id} feedback")
                for style_id in ("achievement", "keyword", "concise")
            ]
        )

        app.radio(key="style_choice").set_value("concise").run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.text_area), 1)
        self.assertEqual(app.text_area[0].value, "concise feedback")
        app.text_area[0].set_value("수정한 feedback").run()
        self.assertEqual(app.text_area[0].value, "수정한 feedback")

    def test_passed_first_attempt_stops_retry_and_finishes(self):
        """1차 결과가 통과하면 재작성 없이 최종 결과로 끝난다."""
        from streamlit.testing.v1 import AppTest

        data = json.dumps(
            {"checklist": CHECKLIST, "experience": EXPERIENCE, "score": score_for("concise", passed=True)},
            ensure_ascii=False,
        )
        script = """
import json
from app.style_select import render_retry_scoring
data = json.loads({data!r})
render_retry_scoring(data["checklist"], data["experience"], "concise", data["score"])
""".format(data=data)
        app = AppTest.from_string(script, default_timeout=15).run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.file_uploader), 0)
        self.assertEqual(len(app.text_area), 0)
        self.assertTrue(any("1차 채점을 통과해 최종 결과로 확정했습니다." in item.value for item in app.success))

    def test_passed_retry_stops_retry_and_finishes(self):
        """재작성 결과가 통과하면 다음 차수 업로드 없이 최종 결과로 끝난다."""
        from streamlit.testing.v1 import AppTest

        passed_score = score_for("concise", attempt=2, passed=True)
        history = [{
            "input_signature": "current",
            "style_id": "concise",
            "attempt": 2,
            "rewrite": {
                "case_id": "case-01",
                "style_id": "concise",
                "attempt": 2,
                "sentences": [],
            },
            "score": passed_score,
        }]
        data = json.dumps(
            {
                "checklist": CHECKLIST,
                "experience": EXPERIENCE,
                "score": score_for("concise", passed=False),
                "history": history,
            },
            ensure_ascii=False,
        )
        script = """
import json
import streamlit as st
from app.style_select import _input_signature, render_retry_scoring
data = json.loads({data!r})
data['history'][0]['input_signature'] = _input_signature(data['checklist'], data['experience'])
st.session_state['rewrite_score_history'] = data['history']
render_retry_scoring(data['checklist'], data['experience'], 'concise', data['score'])
""".format(data=data)
        app = AppTest.from_string(script, default_timeout=15).run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.file_uploader), 0)
        self.assertEqual(len(app.text_area), 0)
        self.assertTrue(any("2차 결과로 최종 리포트를 생성합니다." in item.value for item in app.success))

    def test_unpassed_item_keeps_retry_open_even_if_aggregate_passes(self):
        """개별 항목이 미충족이면 집계 passed 값과 무관하게 재작성할 수 있다."""
        from streamlit.testing.v1 import AppTest

        score = score_for("concise", passed=True)
        score["items"][2]["status"] = "미충족"
        data = json.dumps(
            {"checklist": CHECKLIST, "experience": EXPERIENCE, "score": score},
            ensure_ascii=False,
        )
        script = """
import json
from app.style_select import render_retry_scoring
data = json.loads({data!r})
render_retry_scoring(data['checklist'], data['experience'], 'concise', data['score'])
""".format(data=data)
        app = AppTest.from_string(script, default_timeout=15).run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.file_uploader), 1)
        self.assertEqual(len(app.text_area), 1)
        self.assertFalse(any(button.key == "confirm_final_result" for button in app.button))

    def test_failed_attempt_feedback_is_editable_and_keeps_manual_upload(self):
        """기존 채점 feedback 문장을 토글 안에서 수정하고 다음 차수에선 새 feedback을 보여 준다."""
        app = self.retry_app(score_for("concise", passed=False, feedback="req-1: 키워드 보완"))

        self.assertFalse(app.exception)
        self.assertEqual(len(app.text_area), 1)
        self.assertEqual(app.text_area[0].label, "feedback")
        self.assertEqual(app.text_area[0].value, "req-1: 키워드 보완")
        self.assertEqual(len(app.file_uploader), 1)

        app.text_area[0].set_value("더 간결하게 써 주세요.").run()
        retry_rewrite = self.retry_rewrite(2)
        app.file_uploader(key="retry_rewrite_upload_2").set_value(
            ("retry.json", json.dumps(retry_rewrite, ensure_ascii=False).encode("utf-8"), "application/json")
        ).run()
        self.assertEqual(len(app.text_area), 2)
        app.text_area[1].set_value("3차 피드백").run()
        third_rewrite = self.retry_rewrite(3)
        app.file_uploader(key="retry_rewrite_upload_3").set_value(
            ("retry.json", json.dumps(third_rewrite, ensure_ascii=False).encode("utf-8"), "application/json")
        ).run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.text_area), 2)
        latest = max(app.session_state["rewrite_score_history"], key=lambda entry: entry["attempt"])
        self.assertEqual(app.text_area[0].value, "3차 피드백")
        self.assertEqual(latest["attempt"], 2)
        self.assertTrue(
            any("직전 차수에 입력한 feedback: 더 간결하게 써 주세요." in item.value for item in app.caption)
        )
        self.assertEqual(
            {uploader.key for uploader in app.file_uploader},
            {"retry_rewrite_upload_3", "retry_rewrite_upload_4"},
        )

    def test_feedback_and_upload_are_hidden_after_fourth_attempt(self):
        """4차 재작성 결과를 올리면 자동으로 최종 리포트를 만들고 입력란을 숨긴다."""
        app = self.retry_app(score_for("concise", passed=False))

        for attempt in (2, 3):
            retry_rewrite = self.retry_rewrite(attempt)
            app.file_uploader(key=f"retry_rewrite_upload_{attempt}").set_value(
                ("retry.json", json.dumps(retry_rewrite, ensure_ascii=False).encode("utf-8"), "application/json")
            ).run()
            next_rewrite = self.retry_rewrite(attempt + 1)
            app.file_uploader(key=f"retry_rewrite_upload_{attempt + 1}").set_value(
                ("retry.json", json.dumps(next_rewrite, ensure_ascii=False).encode("utf-8"), "application/json")
            ).run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.text_area), 0)
        self.assertEqual(len(app.file_uploader), 0)
        self.assertTrue(any("4차 결과로 최종 리포트를 생성합니다." in item.value for item in app.success))

    def test_retry_screen_shows_saved_sentence_and_feedback_history(self):
        """재작성 화면에는 각 차수의 문장과 이전 피드백을 이력으로 보여 준다."""
        from streamlit.testing.v1 import AppTest

        history = [
            {
                "input_signature": "current",
                "style_id": "concise",
                "attempt": 1,
                "rewrite": {
                    "case_id": "case-01",
                    "style_id": "concise",
                    "attempt": 1,
                    "sentences": [
                        {"item_id": "req-1", "text": "첫 차수 SQL 문장", "user_feedback": ""},
                    ],
                },
                "score": score_for("concise", passed=False),
            },
            {
                "input_signature": "current",
                "style_id": "concise",
                "attempt": 2,
                "rewrite": {
                    "case_id": "case-01",
                    "style_id": "concise",
                    "attempt": 2,
                    "old_revised_cv": [
                        {
                            "attempt": 1,
                            "sentences": [
                                {
                                    "item_id": "req-1",
                                    "text": "첫 차수 SQL 문장",
                                    "user_feedback": "더 짧게 써 주세요.",
                                },
                            ],
                        },
                    ],
                    "sentences": [
                        {"item_id": "req-1", "text": "두 번째로 고친 SQL 문장", "user_feedback": ""},
                    ],
                },
                "score": score_for("concise", attempt=2, passed=False),
            },
        ]
        data = json.dumps(
            {"checklist": CHECKLIST, "experience": EXPERIENCE, "score": score_for("concise", passed=False), "history": history},
            ensure_ascii=False,
        )
        script = """
import json
import streamlit as st
from app.style_select import _input_signature, render_retry_scoring
data = json.loads({data!r})
data['history'][0]['input_signature'] = _input_signature(data['checklist'], data['experience'])
data['history'][1]['input_signature'] = data['history'][0]['input_signature']
st.session_state['rewrite_score_history'] = data['history']
render_retry_scoring(data['checklist'], data['experience'], 'concise', data['score'])
""".format(data=data)
        app = AppTest.from_string(script, default_timeout=15).run()
        visible_text = "\n".join(
            item.value
            for item in app.get("markdown") + app.get("subheader") + app.get("caption") + app.get("write")
        )

        self.assertFalse(app.exception)
        self.assertIn("첫 차수 SQL 문장", visible_text)
        self.assertIn("더 짧게 써 주세요.", visible_text)
        self.assertIn("두 번째로 고친 SQL 문장", visible_text)


    def test_mismatched_score_blocks_choice(self):
        """짝이 안 맞는 score가 있으면 오류를 보여 주고 고르기를 막는다."""
        app = self.app([score_for("achievement"), score_for("keyword"), score_for("concise", case_id="case-99")])

        self.assertTrue(any("짝이 맞는 score가 없습니다" in error.value for error in app.error))
        self.assertEqual(len(app.radio), 0)

    def test_uploaded_first_attempt_with_wrong_source_is_rejected(self):
        """올린 첫 rewrite의 source가 경험 원문과 다르면 스타일 선택 전에 오류를 보여 준다."""
        from streamlit.testing.v1 import AppTest

        invalid = loop_output()
        invalid["revised_cv"][0]["sentences"][0]["source"] = "수정한 원문"
        data = json.dumps(
            {"checklist": CHECKLIST, "experience": EXPERIENCE, "loop": invalid, "scores": [
                score_for(style_id) for style_id in ("achievement", "keyword", "concise")
            ]},
            ensure_ascii=False,
        )
        script = """
import json
import streamlit as st
from app.style_select import render_style_step
data = json.loads({data!r})
st.session_state['experience_confirmed'] = data['experience']
render_style_step(data['checklist'])
""".format(data=data)
        app = AppTest.from_string(script, default_timeout=15).run()
        app.file_uploader(key="style_step_upload").set_value(
            ("rewrite.json", json.dumps(invalid, ensure_ascii=False).encode("utf-8"), "application/json")
        ).run()

        self.assertFalse(app.exception)
        self.assertTrue(any("source가 경험 입력 원문과 다릅니다" in error.value for error in app.error))
        self.assertEqual(len(app.radio), 0)

    def test_sample_experience_and_uploaded_validation_are_cached_across_reruns(self):
        """샘플 경험 로딩과 업로드 첫 결과 검사가 재실행 사이에 반복되지 않는지 확인한다."""
        from streamlit.testing.v1 import AppTest

        data = json.dumps({"checklist": CHECKLIST, "loop": loop_output()}, ensure_ascii=False)
        script = """
import json
import streamlit as st
import app.style_select as module
data = json.loads({data!r})
if not hasattr(module, '_test_orig_load'):
    module._test_orig_load = module.load_sample_experience
    module._test_orig_check = module.check_first_attempt
def count_sample_load():
    st.session_state['sample_load_count'] = st.session_state.get('sample_load_count', 0) + 1
    return module._test_orig_load()
def count_first_check(*args):
    st.session_state['first_check_count'] = st.session_state.get('first_check_count', 0) + 1
    return module._test_orig_check(*args)
module.load_sample_experience = count_sample_load
module.check_first_attempt = count_first_check
module.render_style_step(data['checklist'])
""".format(data=data)
        app = AppTest.from_string(script, default_timeout=15).run()
        app.file_uploader(key="style_step_upload").set_value(
            ("rewrite.json", json.dumps(loop_output(), ensure_ascii=False).encode("utf-8"), "application/json")
        ).run()
        app.run()

        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["sample_load_count"], 1)
        # 초기 샘플 한 번과 업로드 한 번만 검사하고, 같은 업로드 재실행에서는 재검사하지 않는다.
        self.assertEqual(app.session_state["first_check_count"], 2)

    def test_preview_runs_on_repository_samples(self):
        """미리보기(streamlit run app/style_select.py)가 지금 저장소 샘플로 오류 없이 세 스타일을 보여 준다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/style_select.py"), default_timeout=15).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 0)
        self.assertEqual(app.radio(key="style_choice").options, ["성과 강조형", "키워드 맞춤형", "간결형"])

    def test_main_flow_continues_from_checklist_to_style_choice(self):
        """app/main.py에서 체크리스트를 확정하고 경험을 입력한 뒤 스타일을 골라 계속할 수 있다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/main.py"), default_timeout=15).run()
        self.assertFalse(app.exception)
        self.assertTrue(any("2. 체크리스트 확인" in item.value for item in app.header))
        self.assertEqual(len(app.radio), 0)

        app.button(key="start_sample").click().run()
        app.button(key="confirm_checklist").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.radio), 0)

        app.text_area(key="experience_text_case-01_req-1").set_value(
            "SQL로 고객 데이터 뽑아서 대시보드 만듦. 매주 월요일 리포트, 마케팅팀 5명이 봄"
        )
        app.text_area(key="experience_text_case-01_req-2").set_value("Python으로 엑셀 정리 자동화 스크립트 작성, 2년 정도 사용")
        app.button(key="confirm_experience").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 0)

        app.text_area(key="experience_text_case-01_req-1").set_value("SQL로 고객 데이터를 분석했습니다.")
        app.text_area(key="experience_text_case-01_req-2").set_value("Python으로 엑셀 정리를 자동화했습니다.")
        app.button(key="confirm_experience").click().run()
        self.assertEqual(
            app.session_state["experience_confirmed"]["experiences"],
            [
                {"item_id": "req-1", "text": "SQL로 고객 데이터를 분석했습니다.", "years": None},
                {"item_id": "req-2", "text": "Python으로 엑셀 정리를 자동화했습니다.", "years": None},
            ],
        )
        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 0)

        entered_experience = {
            "req-1": "SQL로 고객 데이터를 분석했습니다.",
            "req-2": "Python으로 엑셀 정리를 자동화했습니다.",
        }
        rewrite_bundle = json.loads(
            (ROOT / "samples" / "rewrite.sample.json").read_text(encoding="utf-8")
        )
        for candidate in rewrite_bundle["revised_cv"]:
            for sentence in candidate["sentences"]:
                sentence["source"] = entered_experience[sentence["item_id"]]
                sentence["text"] = sentence["text"].replace("마케팅팀 5명", "마케팅팀").replace("5명이", "팀이")
        app.file_uploader(key="style_step_upload").set_value(
            (
                "rewrite.json",
                json.dumps(rewrite_bundle, ensure_ascii=False).encode("utf-8"),
                "application/json",
            )
        ).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 0)

        app.radio(key="style_choice").set_value("concise").run()
        app.button(key="confirm_style").click().run()
        self.assertEqual(app.session_state["selected_style_id"], "concise")
        self.assertTrue(any("다시 쓴 문장 채점" in item.value for item in app.header))
        self.assertFalse(any("최종 리포트" in item.value for item in app.header))

        history = app.session_state["rewrite_score_history"]
        self.assertEqual(len(history), 1)
        first_result = history[0]
        self.assertEqual(first_result["style_id"], "concise")
        self.assertEqual(first_result["attempt"], 1)
        self.assertEqual(first_result["rewrite"]["case_id"], "case-01")
        self.assertEqual(first_result["rewrite"]["style_id"], "concise")
        self.assertEqual(first_result["rewrite"]["attempt"], 1)
        self.assertEqual(first_result["rewrite"]["sentences"][0]["item_id"], "req-1")
        self.assertEqual(first_result["score"]["case_id"], first_result["rewrite"]["case_id"])
        self.assertEqual(first_result["score"]["style_id"], first_result["rewrite"]["style_id"])
        self.assertEqual(first_result["score"]["attempt"], first_result["rewrite"]["attempt"])

        app.run()
        self.assertEqual(len(app.session_state["rewrite_score_history"]), 1)

        retry_rewrite = {
            "schema_version": 1,
            "case_id": "case-01",
            "prompt_version": "rewrite_v1",
            "attempt": 2,
            "style": "concise",
            "sentences": [
                {
                    "item_id": "req-1",
                    "source": entered_experience["req-1"],
                    "text": "SQL로 고객 데이터 대시보드를 만들었습니다.",
                    "llm_opinion": "핵심 경험을 짧게 정리했습니다.",
                    "user_feedback": "",
                },
                {
                    "item_id": "req-2",
                    "source": entered_experience["req-2"],
                    "text": "Python으로 엑셀 정리 자동화 스크립트를 작성했습니다.",
                    "llm_opinion": "사용한 기술과 업무를 유지했습니다.",
                    "user_feedback": "",
                },
            ],
        }
        app.file_uploader(key="retry_rewrite_upload_2").set_value(
            ("retry.json", json.dumps(retry_rewrite, ensure_ascii=False).encode("utf-8"), "application/json")
        ).run()

        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 0)
        history = app.session_state["rewrite_score_history"]
        self.assertEqual(len(history), 2)
        retry_result = history[1]
        self.assertEqual(retry_result["style_id"], "concise")
        self.assertEqual(retry_result["attempt"], 2)
        self.assertEqual(retry_result["rewrite"]["case_id"], "case-01")
        self.assertEqual(retry_result["rewrite"]["style_id"], "concise")
        self.assertEqual(retry_result["rewrite"]["attempt"], 2)
        self.assertEqual(retry_result["rewrite"]["sentences"][0]["text"], "SQL로 고객 데이터 대시보드를 만들었습니다.")
        self.assertEqual(retry_result["score"]["case_id"], retry_result["rewrite"]["case_id"])
        self.assertEqual(retry_result["score"]["style_id"], retry_result["rewrite"]["style_id"])
        self.assertEqual(retry_result["score"]["attempt"], retry_result["rewrite"]["attempt"])
        self.assertTrue(any("최종 리포트" in item.value for item in app.header))


class RetryUploadProgressionTests(unittest.TestCase):
    def test_unsubmitted_failed_preview_exposes_next_attempt_upload(self):
        """미저장 2차 미리보기가 미통과면 3차 파일도 바로 올릴 수 있다."""
        from app.style_select import render_retry_scoring

        uploaded_rewrite = {
            "schema_version": 1,
            "case_id": "case-01",
            "prompt_version": "rewrite_v1",
            "attempt": 2,
            "style_id": "concise",
            "sentences": [],
        }
        uploaded = MagicMock()
        uploaded.getvalue.return_value = json.dumps(uploaded_rewrite, ensure_ascii=False).encode("utf-8")
        fake_st = MagicMock()
        fake_st.session_state = {}
        fake_st.file_uploader.side_effect = lambda *args, **kwargs: (
            uploaded if kwargs["key"] == "retry_rewrite_upload_2" else None
        )
        second_score = score_for("concise", attempt=2, passed=False)

        with (
            patch("app.style_select.st", fake_st),
            patch("app.style_select.score_if_available", return_value=[second_score]),
        ):
            render_retry_scoring(CHECKLIST, EXPERIENCE, "concise", score_for("concise", passed=False))

        upload_keys = [call.kwargs["key"] for call in fake_st.file_uploader.call_args_list]
        self.assertEqual(upload_keys, ["retry_rewrite_upload_2", "retry_rewrite_upload_3"])

    def test_selecting_next_attempt_saves_the_previous_preview(self):
        """3차 파일을 선택하면 저장하지 않았던 2차 미리보기를 이력에 저장한다."""
        from app.style_select import render_retry_scoring

        def uploaded_for(attempt):
            payload = {
                "schema_version": 1,
                "case_id": "case-01",
                "prompt_version": "rewrite_v1",
                "attempt": attempt,
                "style_id": "concise",
                "sentences": [],
            }
            result = MagicMock()
            result.getvalue.return_value = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            return result

        fake_st = MagicMock()
        fake_st.session_state = {}
        fake_st.file_uploader.side_effect = lambda *args, **kwargs: {
            "retry_rewrite_upload_2": uploaded_for(2),
            "retry_rewrite_upload_3": uploaded_for(3),
        }[kwargs["key"]]
        second_score = score_for("concise", attempt=2, passed=False)

        with (
            patch("app.style_select.st", fake_st),
            patch("app.style_select.score_if_available", return_value=[second_score]),
            patch("app.style_select.save_attempt_result") as save_attempt,
        ):
            render_retry_scoring(CHECKLIST, EXPERIENCE, "concise", score_for("concise", passed=False))

        save_attempt.assert_called_once()
        self.assertEqual(save_attempt.call_args.args[2]["attempt"], 2)

    def test_saving_unpassed_attempt_finishes_retry_flow(self):
        """미통과여도 차수 결과 저장 버튼을 누르면 재작성 흐름이 완료된다."""
        from app.style_select import render_retry_scoring

        payload = {
            "schema_version": 1,
            "case_id": "case-01",
            "prompt_version": "rewrite_v1",
            "attempt": 2,
            "style_id": "concise",
            "sentences": [],
        }
        uploaded = MagicMock()
        uploaded.getvalue.return_value = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        fake_st = MagicMock()
        fake_st.session_state = {}
        fake_st.file_uploader.side_effect = lambda *args, **kwargs: (
            uploaded if kwargs["key"] == "retry_rewrite_upload_2" else None
        )
        fake_st.button.side_effect = lambda *args, **kwargs: kwargs.get("key") == "save_retry_score"
        failed_second_score = score_for("concise", attempt=2, passed=False)

        with (
            patch("app.style_select.st", fake_st),
            patch("app.style_select.score_if_available", return_value=[failed_second_score]),
        ):
            render_retry_scoring(CHECKLIST, EXPERIENCE, "concise", score_for("concise", passed=False))
            fake_st.file_uploader.side_effect = lambda *args, **kwargs: None
            completed = render_retry_scoring(
                CHECKLIST, EXPERIENCE, "concise", score_for("concise", passed=False)
            )

        self.assertTrue(completed)


    def test_passed_attempt_stops_and_becomes_the_final_result(self):
        """통과한 재작성은 저장 버튼이나 추가 업로드 없이 최종 결과가 된다."""
        from app.style_select import render_retry_scoring

        payload = {
            "schema_version": 1,
            "case_id": "case-01",
            "prompt_version": "rewrite_v1",
            "attempt": 2,
            "style_id": "concise",
            "sentences": [],
        }
        uploaded = MagicMock()
        uploaded.getvalue.return_value = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        fake_st = MagicMock()
        fake_st.session_state = {}
        fake_st.file_uploader.side_effect = lambda *args, **kwargs: (
            uploaded if kwargs["key"] == "retry_rewrite_upload_2" else None
        )

        with (
            patch("app.style_select.st", fake_st),
            patch("app.style_select.score_if_available", return_value=[score_for("concise", attempt=2, passed=True)]),
        ):
            render_retry_scoring(
                CHECKLIST, EXPERIENCE, "concise", score_for("concise", passed=False)
            )
            fake_st.file_uploader.side_effect = lambda *args, **kwargs: None
            completed = render_retry_scoring(
                CHECKLIST, EXPERIENCE, "concise", score_for("concise", passed=False)
            )

        self.assertTrue(completed)
        self.assertEqual([call.kwargs["key"] for call in fake_st.file_uploader.call_args_list], ["retry_rewrite_upload_2"])
        self.assertTrue(fake_st.session_state["rewrite_score_history"][0]["finalized"])


if __name__ == "__main__":
    unittest.main()
