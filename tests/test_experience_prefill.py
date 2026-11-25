"""공고 분석 → 체크리스트 확인 → 경험 초안으로 미리 채우기 → experience.json 저장 흐름을 검사한다 (C안).

AI를 부르는 파싱 함수는 정해진 결과를 돌려주는 가짜 함수로 바꾸고, 케이스 폴더는 임시 폴더를 쓴다.
"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.parsing_bridge import keywords_missing, prefill_from_draft
from tests.streamlit_support import streamlit_apptest_supported


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CHECKLIST = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))


def _draft(case_id="case-01", req1="고객 데이터로 대시보드를 만들었습니다", req2="Python 자동화 2년", req2_years=2, req3=None):
    """테스트용 경험 초안(experience_draft.json 모양)을 돌려준다."""
    return {
        "case_id": case_id,
        "schema_version": 1,
        "prompt_version": "parsing_experience_draft_v1",
        "experiences": [
            {"item_id": "req-1", "text": req1, "years": None},
            {"item_id": "req-2", "text": req2, "years": req2_years},
            {"item_id": "req-3", "text": req3, "years": None},
        ],
    }


class PrefillFunctionTests(unittest.TestCase):
    """초안 → 입력란 값 바꾸기와 키워드 검사를 확인한다."""

    def test_prefill_uses_text_and_only_positive_years_for_required_items(self):
        """글은 null이 아닌 것만, 연수는 요구 연수가 있는 항목의 1 이상만 채운다. 0은 빈칸(미확인)."""
        checklist = deepcopy(SAMPLE_CHECKLIST)
        texts, years = prefill_from_draft(_draft(), checklist)
        self.assertEqual(texts, {"req-1": "고객 데이터로 대시보드를 만들었습니다", "req-2": "Python 자동화 2년"})
        self.assertEqual(years, {"req-2": 2})

        _, years = prefill_from_draft(_draft(req2_years=0), checklist)
        self.assertEqual(years, {})

        draft = _draft()
        draft["experiences"][0]["years"] = 5  # req-1은 요구 연수가 없다
        _, years = prefill_from_draft(draft, checklist)
        self.assertNotIn("req-1", years)

    def test_prefill_ignores_draft_of_other_case(self):
        """초안의 case_id가 체크리스트와 다르면 아무것도 채우지 않는다."""
        self.assertEqual(prefill_from_draft(_draft(case_id="case-99"), SAMPLE_CHECKLIST), ({}, {}))
        self.assertEqual(prefill_from_draft(None, SAMPLE_CHECKLIST), ({}, {}))

    def test_keywords_missing_matches_scoring_rule(self):
        """채점과 같이 영어 대소문자를 무시하고 키워드가 글에 그대로 있는지 본다."""
        self.assertTrue(keywords_missing("고객 데이터로 대시보드", ["SQL"]))
        self.assertFalse(keywords_missing("sql로 데이터를 뽑았습니다", ["SQL"]))
        self.assertFalse(keywords_missing("", ["SQL"]))
        self.assertFalse(keywords_missing("아무 글", []))


@unittest.skipUnless(
    importlib.util.find_spec("streamlit") and streamlit_apptest_supported(),
    "Streamlit AppTest를 실행할 수 없는 환경입니다",
)
class PrefillAppTests(unittest.TestCase):
    """app/main.py를 실제로 돌려 C안 흐름을 확인한다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # 루프(loop.initial_rewrite)도 <ROOT>/data/cases를 읽으므로 같은 모양으로 둔다.
        self.cases_dir = Path(self.tmp.name) / "data" / "cases"
        self.cases_dir.mkdir(parents=True)
        self.confirmed_calls = []
        self.next_draft = _draft()
        self.regenerated_draft = None
        patches = [
            patch("parsing.common.CASES_DIR", self.cases_dir),
            patch("parsing.parser_pipeline.run_pipeline_from_text", side_effect=self._fake_start),
            patch(
                "parsing.parser_pipeline.run_pipeline_from_confirmed_checklist",
                side_effect=self._fake_confirmed,
            ),
            patch("parsing.experience_parser.generate_experience_draft", side_effect=self._fake_regenerate),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.tmp.cleanup)

    def _fake_start(self, job_text, resume_text, case_id=None):
        """가짜 run_pipeline_from_text: 케이스 폴더를 만들고 샘플 체크리스트를 저장한다."""
        number = len(list(self.cases_dir.iterdir())) + 1
        case_id = f"case-{number:02d}"
        case_dir = self.cases_dir / case_id
        case_dir.mkdir()
        checklist = deepcopy(SAMPLE_CHECKLIST)
        checklist["case_id"] = case_id
        path = case_dir / "checklist.json"
        path.write_text(json.dumps(checklist, ensure_ascii=False), encoding="utf-8")
        return case_id, {"checklist": path}, []

    def _fake_confirmed(self, job_text, resume_text, confirmed_checklist, case_id=None):
        """가짜 run_pipeline_from_confirmed_checklist: 넘겨받은 값을 기록하고 초안을 저장한다."""
        self.confirmed_calls.append((job_text, resume_text, deepcopy(confirmed_checklist), case_id))
        draft = deepcopy(self.next_draft)
        draft["case_id"] = case_id
        path = self.cases_dir / case_id / "experience_draft.json"
        path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        return case_id, {"experience_draft": path}, []

    def _fake_regenerate(self, case_id, *, overwrite=False):
        """가짜 generate_experience_draft: 미리 정해 둔 새 초안을 돌려준다."""
        draft = deepcopy(self.regenerated_draft)
        draft["case_id"] = case_id
        return draft, self.cases_dir / case_id / "experience_draft.json"

    def _analyzed_and_confirmed_app(self):
        """공고·이력서를 넣고 분석한 뒤 체크리스트까지 확인한 AppTest를 돌려준다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/main.py"), default_timeout=15).run()
        app.text_area(key="job_posting").set_value("데이터 분석가 채용\nSQL 활용 능력")
        app.text_area(key="resume").set_value("이력서 원문").run()
        app.button(key="analyze_inputs").click().run()
        self.assertFalse(app.exception)
        app.button(key="confirm_checklist").click().run()
        self.assertFalse(app.exception)
        return app

    def test_analyze_builds_checklist_from_inputs(self):
        """분석하기를 누르면 파싱 결과 체크리스트를 확인 전 상태로 보여 준다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/main.py"), default_timeout=15).run()
        self.assertTrue(app.button(key="analyze_inputs").disabled)
        app.text_area(key="job_posting").set_value("데이터 분석가 채용")
        app.text_area(key="resume").set_value("이력서 원문").run()
        self.assertFalse(app.button(key="analyze_inputs").disabled)
        app.button(key="analyze_inputs").click().run()

        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["active_case"]["case_id"], "case-01")
        self.assertIs(app.session_state["checklist_original"]["reviewed"], False)
        self.assertEqual(app.session_state["checklist_original"]["case_id"], "case-01")
        self.assertEqual(len(app.dataframe), 1)

    def test_confirm_fetches_draft_with_same_inputs_and_prefills(self):
        """확인 완료하면 처음과 같은 공고·이력서로 초안을 받아 입력란을 미리 채운다."""
        app = self._analyzed_and_confirmed_app()

        job_text, resume_text, confirmed, case_id = self.confirmed_calls[-1]
        self.assertEqual(case_id, "case-01")
        self.assertEqual(job_text, app.session_state["active_case"]["job_text"])
        self.assertEqual(resume_text, "이력서 원문")
        self.assertIs(confirmed["reviewed"], True)

        self.assertEqual(app.text_area(key="experience_text_case-01_req-1").value, "고객 데이터로 대시보드를 만들었습니다")
        self.assertEqual(app.text_area(key="experience_text_case-01_req-3").value, "")
        self.assertEqual(app.number_input(key="experience_years_case-01_req-2").value, 2)
        # req-1 초안에는 키워드 SQL이 없어서 확인 안내가 나온다.
        self.assertTrue(any("키워드(SQL)" in item.value for item in app.warning))
        self.assertTrue(any("맞는 경험을 못 찾았어요" in item.value for item in app.caption))

    def test_zero_years_in_draft_stays_blank(self):
        """초안 연수 0은 '못 찾음'으로 보고 연수 칸을 비워 둔다."""
        self.next_draft = _draft(req2_years=0)
        app = self._analyzed_and_confirmed_app()
        self.assertIsNone(app.number_input(key="experience_years_case-01_req-2").value)

    def test_confirm_experience_saves_file_without_empty_items(self):
        """경험 입력 확인을 누르면 빈 항목을 뺀 experience.json을 케이스 폴더에 저장한다."""
        app = self._analyzed_and_confirmed_app()
        app.text_area(key="experience_text_case-01_req-1").set_value("SQL로 고객 데이터를 뽑아 대시보드를 만들었습니다")
        app.button(key="confirm_experience").click().run()
        self.assertFalse(app.exception)

        saved = json.loads((self.cases_dir / "case-01" / "experience.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual(
            saved["experiences"],
            [
                {"item_id": "req-1", "text": "SQL로 고객 데이터를 뽑아 대시보드를 만들었습니다", "years": None},
                {"item_id": "req-2", "text": "Python 자동화 2년", "years": 2},
            ],
        )
        self.assertTrue(any("experience.json에 저장했어요" in item.value for item in app.caption))

    def test_saved_experience_makes_first_three_styles_from_case_folder(self):
        """경험을 저장한 뒤 '첫 문장 3종 만들기'를 누르면 케이스 폴더 파일로 3종을 만들어 스타일을 고를 수 있다."""
        def fake_llm(prompt, schema):
            entries = json.loads(prompt.split("입력 데이터: ", 1)[1])
            return {"sentences": [
                {"item_id": entry["item_id"], "text": f"{entry['item_id']} 첨삭 문장", "llm_opinion": "원문 유지"}
                for entry in entries
            ]}

        app = self._analyzed_and_confirmed_app()
        app.text_area(key="experience_text_case-01_req-1").set_value("SQL로 고객 데이터를 뽑아 대시보드를 만들었습니다")
        app.button(key="confirm_experience").click().run()
        self.assertFalse(app.exception)
        self.assertIn("첫 문장 3종 만들기", [button.label for button in app.button])
        self.assertEqual(len(app.radio), 0)

        with patch("loop.initial_rewrite.ROOT", Path(self.tmp.name)), patch(
            "loop.initial_rewrite.call_llm", side_effect=fake_llm
        ) as call_llm, patch("sys.stderr"):
            app.button(key="generate_first_rewrite_case-01").click().run()

        self.assertFalse(app.exception)
        self.assertEqual(call_llm.call_count, 3)
        saved = json.loads((self.cases_dir / "case-01" / "rewrite.json").read_text(encoding="utf-8"))
        self.assertEqual([row["style"] for row in saved["revised_cv"]], ["achievement", "keyword", "concise"])
        self.assertEqual(len(app.radio), 1)

    def test_regenerate_fills_only_empty_boxes(self):
        """초안 다시 만들기는 빈 입력란만 채우고, 사용자가 적은 칸은 그대로 둔다."""
        app = self._analyzed_and_confirmed_app()
        app.text_area(key="experience_text_case-01_req-1").set_value("")
        app.text_area(key="experience_text_case-01_req-3").set_value("내가 직접 적은 대용량 처리 경험")
        app.run()
        self.regenerated_draft = _draft(req1="새 초안 글", req3="초안이 찾은 글")
        app.button(key="regenerate_draft_case-01").click().run()

        self.assertFalse(app.exception)
        self.assertEqual(app.text_area(key="experience_text_case-01_req-1").value, "새 초안 글")
        self.assertEqual(app.text_area(key="experience_text_case-01_req-3").value, "내가 직접 적은 대용량 처리 경험")

    def test_new_analysis_resets_checklist_and_experience(self):
        """다시 분석하면 새 케이스로 시작하고, 확인한 체크리스트와 경험을 지운다."""
        app = self._analyzed_and_confirmed_app()
        app.button(key="confirm_experience").click().run()
        self.assertIn("experience_confirmed", app.session_state)

        app.button(key="analyze_inputs").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["active_case"]["case_id"], "case-02")
        self.assertNotIn("checklist_confirmed", app.session_state)
        self.assertNotIn("experience_confirmed", app.session_state)

    def test_sample_flow_does_not_prefill_or_save(self):
        """샘플로 시작하면 초안을 받지 않고 experience.json도 저장하지 않는다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/main.py"), default_timeout=15).run()
        app.button(key="start_sample").click().run()
        app.button(key="confirm_checklist").click().run()
        app.text_area(key="experience_text_case-01_req-1").set_value("SQL 경험")
        app.button(key="confirm_experience").click().run()

        self.assertFalse(app.exception)
        self.assertEqual(self.confirmed_calls, [])
        self.assertEqual(list(self.cases_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
