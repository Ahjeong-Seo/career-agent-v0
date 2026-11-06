"""경험 입력 화면의 저장 모양과 입력 유지를 검사한다."""

import importlib.util
import json
from pathlib import Path
import unittest

from app.experience_input import _experience_from_inputs
from tests.streamlit_support import streamlit_apptest_supported


ROOT = Path(__file__).resolve().parents[1]


class ExperienceDataTests(unittest.TestCase):
    """항목별 입력을 experience 모양으로 바꾸는 함수를 확인한다."""

    def test_original_text_is_kept_and_blank_items_are_left_out(self):
        """적은 글은 다듬지 않고 그대로 두고, 비어 있는 항목은 빼는지 확인한다."""
        checklist = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))

        experience = _experience_from_inputs(
            checklist, {"req-1": "  SQL로 분석했어요\n", "req-2": "   ", "req-3": ""}
        )

        self.assertEqual(
            experience,
            {
                "case_id": checklist["case_id"],
                "schema_version": 1,
                "experiences": [{"item_id": "req-1", "text": "  SQL로 분석했어요\n"}],
            },
        )

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "jsonschema가 필요합니다")
    def test_result_matches_parsing_experience_schema(self):
        """만든 experience가 파싱팀 스키마(schemas/parsing/experience.json)를 통과하는지 확인한다."""
        import jsonschema

        checklist = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas/parsing/experience.json").read_text(encoding="utf-8"))

        jsonschema.validate(_experience_from_inputs(checklist, {"req-1": "SQL로 분석"}), schema)


@unittest.skipUnless(
    importlib.util.find_spec("streamlit") and streamlit_apptest_supported(),
    "Streamlit AppTest를 실행할 수 없는 환경입니다",
)
class ExperienceAppTests(unittest.TestCase):
    """app/main.py에서 경험 입력 화면을 실제로 돌려 본다."""

    def _confirmed_app(self):
        """샘플 체크리스트를 확인 완료한 AppTest를 반환한다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/main.py"), default_timeout=15).run()
        app.button(key="start_sample").click().run()
        app.button(key="confirm_checklist").click().run()
        return app

    def test_guide_is_shown_before_checklist_is_confirmed(self):
        """체크리스트를 확인하기 전에는 경험 입력 대신 안내가 보이는지 확인한다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/main.py"), default_timeout=15).run()

        self.assertFalse(app.exception)
        self.assertTrue(any("체크리스트를 확정하면" in item.value for item in app.info))
        self.assertFalse([area for area in app.text_area if area.key.startswith("experience_text_")])

    def test_typed_experience_survives_checklist_edit(self):
        """경험을 적은 뒤 체크리스트를 고치고 다시 확인해도 적은 글이 남는지 확인한다."""
        app = self._confirmed_app()
        app.text_area(key="experience_text_case-01_req-1").set_value("SQL로 고객 데이터를 분석했습니다.")
        app.button(key="confirm_experience").click().run()
        self.assertIn("experience_confirmed", app.session_state)

        # 체크리스트 표를 고치면 체크리스트 확인과 경험 확인이 함께 풀린다.
        app.session_state["checklist_editor"] = {
            "edited_rows": {0: {"text": "SQL 쿼리 작성 능력"}},
            "added_rows": [],
            "deleted_rows": [],
        }
        app.run()
        self.assertFalse(app.exception)
        self.assertNotIn("checklist_confirmed", app.session_state)
        self.assertEqual(
            app.session_state["experience_confirmed"]["experiences"],
            [{"item_id": "req-1", "text": "SQL로 고객 데이터를 분석했습니다."}],
        )

        app.button(key="confirm_checklist").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(
            app.text_area(key="experience_text_case-01_req-1").value,
            "SQL로 고객 데이터를 분석했습니다.",
        )
        # 체크리스트 확인이 풀려도 항목 ID가 같은 경험과 그 확인 상태를 유지한다.
        self.assertEqual(
            app.session_state["experience_confirmed"]["experiences"],
            [{"item_id": "req-1", "text": "SQL로 고객 데이터를 분석했습니다."}],
        )
        self.assertEqual(
            app.session_state["experience_confirmed"]["experiences"],
            [{"item_id": "req-1", "text": "SQL로 고객 데이터를 분석했습니다."}],
        )


if __name__ == "__main__":
    unittest.main()
