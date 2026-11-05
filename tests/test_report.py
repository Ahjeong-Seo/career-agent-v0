"""최종 리포트에서 이력 전체를 중복 없이 표시하는 사용자 흐름을 검사한다."""

import importlib.util
import json
from pathlib import Path
import unittest

from tests.streamlit_support import streamlit_apptest_supported


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    importlib.util.find_spec("streamlit") and streamlit_apptest_supported(),
    "Streamlit AppTest를 실행할 수 없는 환경입니다",
)
class ReportAppTests(unittest.TestCase):
    """리포트의 공개 화면 경계로 첫 결과가 이력에도 포함된 경우를 확인한다."""

    def test_history_with_first_attempt_does_not_duplicate_report_attempt(self):
        """attempt 1을 별도 인자와 이력에 함께 전달해도 2차 결과 리포트를 만든다."""
        from streamlit.testing.v1 import AppTest

        rewrite_one = {
            "case_id": "case-01",
            "style_id": "achievement",
            "attempt": 1,
            "sentences": [{"item_id": "req-1", "text": "첫 문장", "source": "SQL 경험"}],
        }
        score_one = {
            "case_id": "case-01",
            "style_id": "achievement",
            "attempt": 1,
            "passed": False,
            "items": [{"item_id": "req-1", "status": "미충족", "reason": "재작성 필요"}],
            "made_up_numbers": [],
            "ai_phrases": [],
            "feedback": "다시 써 주세요",
        }
        rewrite_two = {**rewrite_one, "attempt": 2, "sentences": [{"item_id": "req-1", "text": "두 번째 문장", "source": "SQL 경험"}]}
        score_two = {**score_one, "attempt": 2, "passed": True, "items": [{"item_id": "req-1", "status": "충족", "reason": "SQL 포함"}], "feedback": ""}
        payload = {
            "checklist": {"case_id": "case-01", "reviewed": True, "items": [{"id": "req-1", "text": "SQL 분석", "level": "필수", "type": "기술"}]},
            "experience": {"case_id": "case-01", "schema_version": 1, "experiences": [{"item_id": "req-1", "text": "SQL 경험"}]},
            "first_rewrite": rewrite_one,
            "first_score": score_one,
            "history": [
                {"style_id": "achievement", "attempt": 1, "rewrite": rewrite_one, "score": score_one},
                {"style_id": "achievement", "attempt": 2, "rewrite": rewrite_two, "score": score_two},
            ],
        }
        script = """
import json
from app.report import render_report
data = json.loads({payload!r})
render_report(data["checklist"], data["experience"], "achievement", data["first_rewrite"], data["first_score"], data["history"])
""".format(payload=json.dumps(payload, ensure_ascii=False))
        app = AppTest.from_string(script, default_timeout=15).run()

        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertTrue(any("최종 결과: 통과 · 2차" in item.value for item in app.success))
        self.assertTrue(any("1차 시도" == item.value for item in app.subheader))
        self.assertTrue(any("2차 시도" == item.value for item in app.subheader))
        self.assertEqual(sum(item.value.count("첫 문장") for item in app.markdown), 1)
        self.assertEqual(sum(item.value.count("두 번째 문장") for item in app.markdown), 1)


if __name__ == "__main__":
    unittest.main()
