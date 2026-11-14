"""최종 리포트의 차수 선택과 표시용 집계를 검사한다."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

from app.report import _build_report_data, _final_sentences_text, _sample_report_inputs
from tests.streamlit_support import streamlit_apptest_supported


ROOT = Path(__file__).resolve().parents[1]


class ReportDataTests(unittest.TestCase):
    """report data helper가 올바른 attempt와 metric을 고르는지 확인한다."""

    def setUp(self) -> None:
        """여러 리포트 테스트에서 함께 쓸 체크리스트와 입력 데이터를 준비한다."""
        self.checklist = {
            "case_id": "case-01",
            "reviewed": True,
            "items": [
                {"id": "req-1", "text": "SQL", "level": "필수", "type": "기술"},
                {"id": "req-2", "text": "기타", "level": "필수", "type": "기타"},
                {"id": "req-3", "text": "경험 없음", "level": "필수", "type": "경험"},
                {"id": "req-4", "text": "우대", "level": "우대", "type": "기술"},
            ],
        }
        self.experience = {
            "case_id": "case-01",
            "schema_version": 1,
            "experiences": [{"item_id": "req-1", "text": "SQL로 분석"}],
        }
        self.first_rewrite = self._rewrite(1, "SQL로 분석")
        self.first_score = self._score(1, False, 1, 1)

    def _rewrite(self, attempt: int, text: str) -> dict:
        """시도 번호와 문장을 받아 테스트용 rewrite를 반환한다."""
        return {
            "case_id": "case-01",
            "style_id": "achievement",
            "attempt": attempt,
            "sentences": [
                {"item_id": "req-1", "source": "SQL로 분석", "text": text}
            ],
        }

    def _score(
        self, attempt: int, passed: bool, made_up_count: int, ai_phrase_count: int
    ) -> dict:
        """시도 번호·통과값·경고 개수를 받아 테스트용 score를 반환한다."""
        return {
            "case_id": "case-01",
            "style_id": "achievement",
            "attempt": attempt,
            "passed": passed,
            "items": [
                {"item_id": "req-1", "status": "충족", "reason": "SQL 포함"},
                {"item_id": "req-2", "status": "미충족", "reason": "키워드 없음"},
                {"item_id": "req-3", "status": "경험 없음", "reason": "경험 없음"},
                {"item_id": "req-4", "status": "경험 없음", "reason": "경험 없음"},
            ],
            "made_up_numbers": [
                {"item_id": "req-1", "number": str(index), "reason": "숫자"}
                for index in range(made_up_count)
            ],
            "ai_phrases": [
                {"item_id": "req-1", "phrase": str(index)}
                for index in range(ai_phrase_count)
            ],
            "feedback": "",
        }

    def _build(self, retries: list[dict]) -> dict:
        """테스트 데이터와 재작성 이력을 받아 report model을 반환한다."""
        return _build_report_data(
            self.checklist,
            self.experience,
            "achievement",
            self.first_rewrite,
            self.first_score,
            retries,
        )

    def test_first_passing_attempt_becomes_final_and_metrics_use_assessable_required(self):
        """처음 통과한 차수와 평가 대상 필수 항목 기준 집계를 확인한다."""
        attempt_two = {"rewrite": self._rewrite(2, "SQL로 분석 개선"), "score": self._score(2, True, 0, 0)}
        attempt_three = {"rewrite": self._rewrite(3, "SQL로 분석 완료"), "score": self._score(3, True, 0, 0)}

        report = self._build([attempt_two, attempt_three])

        self.assertEqual(report["final"]["attempt"], 2)
        self.assertTrue(report["final"]["score"]["passed"])
        self.assertEqual(report["rewrite_count"], 1)
        self.assertEqual(report["first"]["metrics"]["required_met"], 1)
        self.assertEqual(report["first"]["metrics"]["required_total"], 1)
        self.assertEqual(report["first"]["metrics"]["made_up_numbers"], 1)
        self.assertEqual(report["first"]["metrics"]["ai_phrases"], 1)
        self.assertEqual(
            [item["id"] for item in report["missing_experiences"]],
            ["req-3", "req-4"],
        )

    def test_last_attempt_becomes_final_when_no_attempt_passes(self):
        """통과한 차수가 없으면 가장 마지막 차수를 고르는지 확인한다."""
        attempt_two = {"rewrite": self._rewrite(2, "SQL로 분석 개선"), "score": self._score(2, False, 0, 0)}

        report = self._build([attempt_two])

        self.assertEqual(report["final"]["attempt"], 2)
        self.assertFalse(report["final"]["score"]["passed"])

    def test_mismatched_rewrite_and_score_attempt_fails(self):
        """rewrite와 score의 차수가 다르면 리포트 생성을 멈추는지 확인한다."""
        attempt_two = {"rewrite": self._rewrite(2, "SQL로 분석 개선"), "score": self._score(3, True, 0, 0)}

        with self.assertRaisesRegex(ValueError, "attempt가 일치"):
            self._build([attempt_two])

    def test_only_selected_case_and_style_are_included(self):
        """선택하지 않은 스타일의 이력을 최종 결과에 섞지 않는지 확인한다."""
        other_style_rewrite = deepcopy(self._rewrite(2, "다른 스타일"))
        other_style_score = deepcopy(self._score(2, True, 0, 0))
        other_style_rewrite["style_id"] = "concise"
        other_style_score["style_id"] = "concise"

        report = self._build([{"rewrite": other_style_rewrite, "score": other_style_score}])

        self.assertEqual(report["final"]["attempt"], 1)

    def test_sample_preview_uses_a_failing_first_attempt_and_passing_retry(self):
        """저장소 샘플 미리보기가 실패한 첫 차수와 통과한 재작성을 보여 주는지 확인한다."""
        arguments = _sample_report_inputs()
        report = _build_report_data(*arguments)

        self.assertFalse(report["first"]["score"]["passed"])
        self.assertTrue(report["final"]["score"]["passed"])
        self.assertEqual(report["final"]["attempt"], 2)
        self.assertEqual(report["first"]["metrics"]["made_up_numbers"], 1)
        self.assertEqual(report["final"]["metrics"]["made_up_numbers"], 0)
        self.assertTrue(all(row["first_text"] for row in report["sentences"] if row["source"]))

    def test_without_retry_first_sentence_is_the_final_sentence(self):
        """재작성이 없으면 첫 문장과 최종 문장이 같은 값으로 한 번만 표시될 수 있다."""
        arguments = list(_sample_report_inputs())
        arguments[5] = []
        report = _build_report_data(*arguments)
        self.assertEqual(report["first"]["attempt"], report["final"]["attempt"])
        for row in report["sentences"]:
            self.assertEqual(row["first_text"], row["text"])

    def test_download_text_contains_only_nonempty_final_sentences_in_order(self):
        """TXT 내보내기에 문장만 순서대로 들어가고 빈 항목은 빠지는지 확인한다."""
        report = {
            "sentences": [
                {"item_id": "req-1", "item_text": "첫 항목", "text": "첫 번째 문장입니다."},
                {"item_id": "req-2", "item_text": "빈 항목", "text": ""},
                {"item_id": "req-3", "item_text": "공백 항목", "text": "   "},
                {"item_id": "req-4", "item_text": "두 번째 항목", "text": "두 번째 문장입니다."},
            ]
        }

        self.assertEqual(
            _final_sentences_text(report),
            "req-1. 첫 항목 : 첫 번째 문장입니다.\nreq-4. 두 번째 항목 : 두 번째 문장입니다.\n",
        )

    def test_download_text_leaves_out_sentences_for_items_without_experience(self):
        """경험 없음 항목에 문장이 있으면(지어낸 경험) TXT에 넣지 않는지 확인한다."""
        rewrite = self._rewrite(2, "SQL로 분석")
        rewrite["sentences"].append({"item_id": "req-3", "source": "", "text": "AWS 서버 10대를 운영했습니다."})

        report = self._build([{"rewrite": rewrite, "score": self._score(2, False, 0, 0)}])

        self.assertIn("AWS 서버 10대를 운영했습니다.", [row["text"] for row in report["sentences"]])
        self.assertEqual(_final_sentences_text(report), "req-1. SQL : SQL로 분석\n")

    def test_same_attempt_twice_fails_with_clear_message(self):
        """같은 attempt가 두 번 들어오면 무엇을 넘겨야 하는지 알려 주며 멈추는지 확인한다."""
        attempt_two = {"rewrite": self._rewrite(2, "SQL로 분석 개선"), "score": self._score(2, True, 0, 0)}

        with self.assertRaisesRegex(ValueError, r"같은 attempt\(2\)"):
            self._build([attempt_two, deepcopy(attempt_two)])

    def test_history_including_first_attempt_does_not_duplicate_it(self):
        """첫 결과가 포함된 전체 이력을 받아도 attempt 1은 한 번만 리포트에 둔다."""
        attempt_two = {
            "rewrite": self._rewrite(2, "SQL로 분석 개선"),
            "score": self._score(2, True, 0, 0),
        }
        first_attempt = {
            "rewrite": deepcopy(self.first_rewrite),
            "score": deepcopy(self.first_score),
        }

        report = self._build([first_attempt, attempt_two])

        self.assertEqual([row["attempt"] for row in report["attempts"]], [1, 2])
        self.assertEqual(report["final"]["attempt"], 2)

    def test_input_signature_keeps_only_history_for_current_input(self):
        """경험을 고친 뒤 다시 채점해 생긴 옛 이력은 input_signature로 거르는지 확인한다."""
        old = {
            "input_signature": "old",
            "rewrite": self._rewrite(2, "옛 경험으로 쓴 문장"),
            "score": self._score(2, False, 1, 0),
        }
        new = {
            "input_signature": "new",
            "rewrite": self._rewrite(2, "SQL로 분석 개선"),
            "score": self._score(2, True, 0, 0),
        }

        report = _build_report_data(
            self.checklist,
            self.experience,
            "achievement",
            self.first_rewrite,
            self.first_score,
            [old, new],
            input_signature="new",
        )

        self.assertEqual(report["final"]["attempt"], 2)
        self.assertEqual(report["final"]["rewrite"]["sentences"][0]["text"], "SQL로 분석 개선")


@unittest.skipUnless(
    importlib.util.find_spec("streamlit") and streamlit_apptest_supported(),
    "Streamlit AppTest를 실행할 수 없는 환경입니다",
)
class ReportAppTests(unittest.TestCase):
    """최종 리포트 화면을 실제로 그려 본다."""

    def test_sample_preview_runs(self):
        """streamlit run app/report.py 미리보기가 오류 없이 통과 결과를 그리는지 확인한다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/report.py"), default_timeout=15).run()

        self.assertFalse(app.exception)
        self.assertTrue(any("통과" in item.value for item in app.success))
        self.assertFalse(app.warning)

    def test_warning_is_shown_when_final_attempt_did_not_pass(self):
        """마지막까지 통과하지 못하면 TXT 다운로드 앞에 경고를 띄우는지 확인한다."""
        from streamlit.testing.v1 import AppTest

        script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from app.report import _sample_report_inputs, render_report
checklist, experience, style_id, first_rewrite, first_score, _ = _sample_report_inputs()
render_report(checklist, experience, style_id, first_rewrite, first_score, [])
"""
        app = AppTest.from_string(script, default_timeout=15).run()

        self.assertFalse(app.exception)
        self.assertTrue(any("통과하지 못한 결과" in item.value for item in app.warning))

    def test_report_shows_first_and_final_sentence_comparison(self):
        """리포트가 중간 차수 없이 원문·첫 문장·최종 문장을 표시하는지 확인한다."""
        from streamlit.testing.v1 import AppTest

        script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from app.report import _sample_report_inputs, render_report
render_report(*_sample_report_inputs())
"""
        app = AppTest.from_string(script, default_timeout=15).run()
        visible_text = "\n".join(
            item.value
            for item in (
                app.get("markdown")
                + app.get("subheader")
                + app.get("caption")
                + app.get("success")
                + app.get("warning")
            )
        )

        self.assertFalse(app.exception)
        self.assertIn("원문 · 첫 문장 · 최종 문장", visible_text)
        self.assertIn("첫 문장", visible_text)
        self.assertIn("최종 문장", visible_text)
        self.assertIn("상태:", visible_text)
        self.assertIn("이유:", visible_text)
        self.assertIn("1차 → 최종 변화", visible_text)
        self.assertIn("보완할 경험", visible_text)
        self.assertNotIn("차수별 rewrite와 score", visible_text)

    def test_download_button_receives_item_labeled_final_text(self):
        """실제 리포트 화면이 항목별 최종 문장을 다운로드 데이터로 전달하는지 확인한다."""
        from streamlit.testing.v1 import AppTest

        script = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
import app.report as report
def capture_download(label, data, **kwargs):
    st.session_state['download_payload'] = data
report.st.download_button = capture_download
report.render_report(*report._sample_report_inputs())
"""
        app = AppTest.from_string(script, default_timeout=15).run()

        self.assertFalse(app.exception)
        payload = app.session_state["download_payload"]
        self.assertTrue(payload.endswith("\n"))
        self.assertTrue(all(line.startswith("req-") and " : " in line for line in payload.splitlines()))
        self.assertEqual(
            [line.split(".", 1)[0] for line in payload.splitlines()],
            sorted(
                (line.split(".", 1)[0] for line in payload.splitlines()),
                key=lambda item_id: int(item_id.removeprefix("req-")),
            ),
        )


if __name__ == "__main__":
    unittest.main()
