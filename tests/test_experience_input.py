"""경험 입력 화면의 저장 모양과 입력 유지를 검사한다."""

import importlib.util
import json
from pathlib import Path
import unittest

from app.experience_input import _experience_from_inputs, required_years
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
                "schema_version": 2,
                "experiences": [{"item_id": "req-1", "text": "  SQL로 분석했어요\n", "years": None}],
            },
        )

    def test_years_are_saved_only_as_typed_numbers(self):
        """적은 연수만 정수로 저장하고, 비었거나 이상한 값은 null, 경험 글이 없으면 항목째 빠지는지 확인한다."""
        checklist = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))

        experience = _experience_from_inputs(
            checklist,
            {"req-1": "SQL로 분석", "req-2": "Python 2년 정도 사용", "req-3": ""},
            {"req-1": None, "req-2": 2, "req-3": 5},
        )

        self.assertEqual(
            experience["experiences"],
            [
                {"item_id": "req-1", "text": "SQL로 분석", "years": None},
                {"item_id": "req-2", "text": "Python 2년 정도 사용", "years": 2},
            ],
        )
        for bad in (True, 2.5, -1, 101, "2"):
            with self.subTest(bad=bad):
                row = _experience_from_inputs(checklist, {"req-2": "Python"}, {"req-2": bad})["experiences"][0]
                self.assertIsNone(row["years"])

    def test_required_years_reads_only_positive_integers(self):
        """체크리스트 years가 1 이상 정수일 때만 요구 연수로 보는지 확인한다."""
        self.assertEqual(required_years({"years": 3}), 3)
        for value in (0, None, True, "3", 2.5):
            with self.subTest(value=value):
                self.assertIsNone(required_years({"years": value}))
        self.assertIsNone(required_years({}))

    @unittest.skipUnless(importlib.util.find_spec("jsonschema"), "jsonschema가 필요합니다")
    def test_result_matches_parsing_experience_schema(self):
        """만든 experience가 파싱팀 스키마(schemas/parsing/experience.json)를 통과하는지 확인한다."""
        import jsonschema

        checklist = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas/parsing/experience.json").read_text(encoding="utf-8"))

        # 연수를 비운 항목(null)과 적은 항목(정수)이 모두 스키마를 통과해야 한다.
        jsonschema.validate(
            _experience_from_inputs(
                checklist, {"req-1": "SQL로 분석", "req-2": "Python 사용"}, {"req-2": 2}
            ),
            schema,
        )


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
            [{"item_id": "req-1", "text": "SQL로 고객 데이터를 분석했습니다.", "years": None}],
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
            [{"item_id": "req-1", "text": "SQL로 고객 데이터를 분석했습니다.", "years": None}],
        )
        self.assertEqual(
            app.session_state["experience_confirmed"]["experiences"],
            [{"item_id": "req-1", "text": "SQL로 고객 데이터를 분석했습니다.", "years": None}],
        )

    def test_years_box_only_for_items_with_required_years(self):
        """요구 연수가 있는 항목(샘플 req-2: Python 3년 이상)에만 연수 칸이 보이고, 처음엔 비어 있는지 확인한다."""
        app = self._confirmed_app()

        self.assertFalse(app.exception)
        years_keys = [box.key for box in app.number_input]
        self.assertEqual(years_keys, ["experience_years_case-01_req-2"])
        self.assertIsNone(app.number_input(key="experience_years_case-01_req-2").value)
        self.assertIn("요구 3년", app.number_input(key="experience_years_case-01_req-2").label)

    def test_typed_years_are_confirmed_and_survive_checklist_edit(self):
        """적은 연수가 경험 확인에 들어가고, 체크리스트를 고쳐 다시 확인해도 남는지 확인한다."""
        app = self._confirmed_app()
        app.text_area(key="experience_text_case-01_req-2").set_value("Python 2년 정도 사용")
        app.number_input(key="experience_years_case-01_req-2").set_value(2)
        app.button(key="confirm_experience").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(
            app.session_state["experience_confirmed"]["experiences"],
            [{"item_id": "req-2", "text": "Python 2년 정도 사용", "years": 2}],
        )

        app.session_state["checklist_editor"] = {
            "edited_rows": {0: {"text": "SQL 쿼리 작성 능력"}},
            "added_rows": [],
            "deleted_rows": [],
        }
        app.run()
        app.button(key="confirm_checklist").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.number_input(key="experience_years_case-01_req-2").value, 2)
        self.assertEqual(
            app.session_state["experience_confirmed"]["experiences"],
            [{"item_id": "req-2", "text": "Python 2년 정도 사용", "years": 2}],
        )

    def test_years_without_experience_text_are_not_saved(self):
        """경험 글 없이 연수만 적으면 안내가 보이고, 그 항목은 저장되지 않는지 확인한다."""
        app = self._confirmed_app()
        app.number_input(key="experience_years_case-01_req-2").set_value(4)
        app.run()
        self.assertTrue(any("경험 글을 적어야" in item.value for item in app.caption))

        app.button(key="confirm_experience").click().run()
        self.assertEqual(app.session_state["experience_confirmed"]["experiences"], [])


if __name__ == "__main__":
    unittest.main()
