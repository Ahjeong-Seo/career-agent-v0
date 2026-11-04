"""입력 원문 보존과 체크리스트 계약 및 화면 흐름 회귀 검증."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest

from app.frontend import (
    allowed_values,
    checklist_json,
    checklist_rows,
    mark_reviewed,
    merge_checklist_edits,
    prepare_job_text,
    prepare_resume_text,
    sample_draft_checklist,
    validate_checklist,
)
from tests.streamlit_support import streamlit_apptest_supported


ROOT = Path(__file__).resolve().parents[1]


class FrontendDataTests(unittest.TestCase):
    """순수 함수가 입력과 스키마 약속을 지키는지 검증한다."""

    def setUp(self):
        """인수 없이 저장소 샘플을 '확인 전 파싱 결과' 모양으로 읽어 각 테스트의 입력으로 쓴다."""
        raw = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))
        self.sample = sample_draft_checklist(raw)

    def test_txt_headings_and_original_whitespace_are_preserved(self):
        """입력 원문을 고정 제목 아래 두고 이력서는 그대로 반환하는지 확인한다."""
        self.assertEqual(prepare_job_text("회사\n 소개 ", "공고\n본문"), "회사정보\n회사\n 소개 \n\n채용공고\n공고\n본문\n")
        self.assertEqual(prepare_resume_text("  경험\n\n둘째 줄\n"), "  경험\n\n둘째 줄\n")
        self.assertEqual(prepare_job_text("", "공고 본문"), "채용공고\n공고 본문\n")

    def test_optional_company_section_is_omitted_when_blank(self):
        """회사정보가 공백이면 선택 섹션을 생략하고 채용공고만 반환한다."""
        self.assertEqual(prepare_job_text(" \n ", "채용 내용"), "채용공고\n채용 내용\n")

    def test_empty_inputs_cannot_be_prepared(self):
        """빈 입력을 받으면 TXT 생성을 거부하는지 확인한다."""
        for company, job in ((" ", "\n"), ("회사", "\n")):
            with self.assertRaises(ValueError):
                prepare_job_text(company, job)
        with self.assertRaises(ValueError):
            prepare_resume_text(" \n")

    def test_unedited_round_trip_and_metadata_preservation(self):
        """기존·추가 메타데이터를 가진 입력이 편집 전후 모두 보존되는지 확인한다."""
        self.sample["prompt_version"] = "checklist_v1"
        self.sample["items"][0]["source"] = {"section": "필수 역량"}
        before = deepcopy(self.sample)
        rows = checklist_rows(self.sample)
        self.assertEqual(merge_checklist_edits(self.sample, rows), before)
        rows[0]["text"] = "SQL 쿼리 작성"
        rows[0]["keywords"] = ["SQL", "JOIN, GROUP BY"]
        edited = merge_checklist_edits(self.sample, rows)
        self.assertEqual(edited["prompt_version"], "checklist_v1")
        self.assertEqual(edited["items"][0]["source"], before["items"][0]["source"])
        self.assertEqual(edited["items"][0]["keywords"], ["SQL", "JOIN, GROUP BY"])
        self.assertEqual(self.sample, before)
        self.assertEqual(json.loads(checklist_json(edited)), edited)

    def test_ids_and_item_count_cannot_change(self):
        """ID 변경 또는 항목 제거를 받으면 결과를 만들지 않는지 확인한다."""
        rows = checklist_rows(self.sample)
        rows[0]["id"] = "new-id"
        with self.assertRaisesRegex(ValueError, "id는 변경"):
            merge_checklist_edits(self.sample, rows)
        with self.assertRaises(ValueError):
            merge_checklist_edits(self.sample, rows[1:])

    def test_errors_identify_every_duplicate_and_missing_value(self):
        """중복 ID와 빠진 값을 받으면 해당 행을 모두 알리고 내보내기를 막는지 확인한다."""
        self.sample["items"][1]["id"] = "req-1"
        self.sample["items"][0]["text"] = ""
        self.sample["items"][2]["keywords"] = [""]
        errors = validate_checklist(self.sample)
        self.assertTrue(any("1번 항목 (req-1): ID가 중복" in error for error in errors))
        self.assertTrue(any("2번 항목 (req-1): ID가 중복" in error for error in errors))
        self.assertTrue(any("1번 항목 (req-1): text" in error for error in errors))
        self.assertTrue(any("3번 항목 (req-3): keywords" in error for error in errors))
        with self.assertRaises(ValueError):
            checklist_json(self.sample)

    def test_malformed_input_returns_errors_instead_of_crashing(self):
        """잘못된 입력 형식들을 받아 예외 대신 검증 오류 목록을 반환하는지 확인한다."""
        for invalid in (None, [], {}, {"items": [None]}):
            self.assertTrue(validate_checklist(invalid))

    def test_optional_values_may_be_empty_but_fields_must_exist(self):
        """선택 칸은 null·빈 목록이면 통과하고, 칸 자체가 없으면 막는지 확인한다 (칸은 항상 둔다)."""
        self.sample["job_title"] = None
        self.sample["company_values"] = []
        self.assertEqual(validate_checklist(self.sample), [])
        self.assertEqual(json.loads(checklist_json(self.sample)), self.sample)
        self.sample["job_title"] = 123
        self.assertTrue(any("job_title" in error for error in validate_checklist(self.sample)))
        del self.sample["job_title"]
        del self.sample["company_values"]
        errors = validate_checklist(self.sample)
        self.assertTrue(any("job_title, company_values 칸이 없습니다" in error for error in errors))

    def test_schema_version_and_reviewed_are_required(self):
        """schema_version·reviewed 칸이 없으면 파싱팀 스키마대로 내보내기를 막는지 확인한다."""
        del self.sample["schema_version"]
        del self.sample["reviewed"]
        errors = validate_checklist(self.sample)
        self.assertTrue(any("schema_version" in error and "칸이 없습니다" in error for error in errors))
        self.assertTrue(any("reviewed" in error and "칸이 없습니다" in error for error in errors))
        with self.assertRaises(ValueError):
            checklist_json(self.sample)

    def test_unknown_type_and_level_block_export(self):
        """합의된 유형·구분 외의 값을 받으면 내보내기를 막는지 확인한다."""
        self.sample["items"][0]["type"] = "알 수 없음"
        self.sample["items"][0]["level"] = "선택"
        errors = validate_checklist(self.sample)
        self.assertTrue(any("1번 항목 (req-1): type 값은 기술, 경력, 경험, 기타 중 하나" in error for error in errors))
        self.assertTrue(any("1번 항목 (req-1): level 값은 필수, 우대 중 하나" in error for error in errors))
        with self.assertRaises(ValueError):
            checklist_json(self.sample)

    def test_sample_becomes_unreviewed_draft(self):
        """샘플이 옛 모양이든 reviewed가 true든, 확인 전 초안(reviewed false, schema_version 있음)이 되는지 확인한다."""
        old_shape = {key: value for key, value in self.sample.items() if key not in ("schema_version", "reviewed")}
        draft = sample_draft_checklist(old_shape)
        self.assertEqual(draft["schema_version"], 1)
        self.assertIs(draft["reviewed"], False)
        self.assertNotIn("reviewed", old_shape)
        new_shape = dict(old_shape, schema_version=1, reviewed=True)
        self.assertIs(sample_draft_checklist(new_shape)["reviewed"], False)
        self.assertEqual(validate_checklist(draft), [])

    def test_type_and_level_can_be_edited_with_allowed_values(self):
        """유형·필수/우대는 고칠 수 있고, 허용값은 스키마에서 읽어 오는지 확인한다."""
        self.assertEqual(allowed_values("type"), ["기술", "경력", "경험", "기타"])
        self.assertEqual(allowed_values("level"), ["필수", "우대"])
        rows = checklist_rows(self.sample)
        rows[2]["type"] = "경험"
        rows[2]["level"] = "필수"
        edited = merge_checklist_edits(self.sample, rows)
        self.assertEqual((edited["items"][2]["type"], edited["items"][2]["level"]), ("경험", "필수"))
        self.assertEqual(validate_checklist(edited), [])

    def test_edits_are_trimmed_but_blank_values_are_reported(self):
        """앞뒤 공백은 지우고, 공백만 넣은 값은 지우지 않고 오류로 보여 주는지 확인한다."""
        rows = checklist_rows(self.sample)
        rows[0]["text"] = "  SQL 활용  "
        rows[0]["keywords"] = [" SQL ", " "]
        edited = merge_checklist_edits(self.sample, rows)
        self.assertEqual(edited["items"][0]["text"], "SQL 활용")
        self.assertEqual(edited["items"][0]["keywords"], ["SQL", ""])
        errors = validate_checklist(edited)
        self.assertTrue(any("1번 항목 (req-1): keywords 2번째 값이 비어 있습니다" in error for error in errors))

    def test_mark_reviewed_sets_true_without_changing_input(self):
        """확인 완료하면 reviewed만 true로 바뀐 복사본이 나오고 원본은 그대로인지 확인한다."""
        before = deepcopy(self.sample)
        reviewed = mark_reviewed(self.sample)
        self.assertIs(reviewed["reviewed"], True)
        self.assertEqual(self.sample, before)
        self.assertEqual({**reviewed, "reviewed": False}, before)
        self.assertEqual(json.loads(checklist_json(reviewed))["reviewed"], True)


@unittest.skipUnless(
    importlib.util.find_spec("streamlit") and streamlit_apptest_supported(),
    "Streamlit 미설치 또는 실행 환경에서 socketpair를 사용할 수 없습니다.",
)
class FrontendAppTests(unittest.TestCase):
    """사용자가 입력하고 샘플을 편집하는 화면 흐름을 검증한다."""

    def test_txt_downloads_require_preparation_and_invalidate_after_changes(self):
        """입력과 다운로드 준비를 실행해 준비본만 제공하고 수정 시 폐기하는지 확인한다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/main.py"), default_timeout=15).run()
        self.assertFalse(app.get("download_button"))
        app.text_area(key="job_posting").set_value("첫 공고")
        app.text_area(key="resume").set_value("첫 이력서").run()
        self.assertFalse(app.get("download_button"))
        app.button(key="prepare_prepared_job_text").click().run()
        app.button(key="prepare_prepared_resume_text").click().run()
        self.assertEqual(len(app.get("download_button")), 2)
        self.assertEqual(app.session_state["prepared_job_text"], "채용공고\n첫 공고\n")
        self.assertEqual(app.session_state["prepared_resume_text"], "첫 이력서")

        app.text_area(key="job_posting").set_value("바뀐 공고")
        app.text_area(key="resume").set_value("바뀐 이력서").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.get("download_button"))
        self.assertNotIn("prepared_job_text", app.session_state)
        self.assertNotIn("prepared_resume_text", app.session_state)
        self.assertTrue(any("입력이 바뀌었습니다" in item.value for item in app.info))
        app.button(key="prepare_prepared_job_text").click().run()
        self.assertEqual(app.session_state["prepared_job_text"], "채용공고\n바뀐 공고\n")

    def test_inputs_sample_and_validation_survive_rerun(self):
        """초기·입력·편집 상태를 실행하여 오류 차단과 세션 보존을 확인한다."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app/main.py"), default_timeout=15).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("column")), 0)
        self.assertEqual(len(app.dataframe), 0)
        app.text_area(key="job_posting").set_value("SQL 개발자를 찾습니다.")
        app.text_area(key="company_info").set_value("고객 중심 회사")
        app.text_area(key="resume").set_value("SQL로 데이터를 분석했습니다.")
        app.button(key="start_sample").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe), 1)
        self.assertEqual(app.session_state["resume"], "SQL로 데이터를 분석했습니다.")
        self.assertFalse(app.get("download_button"))

        app.session_state["checklist_editor"] = {
            "edited_rows": {0: {"text": "", "keywords": []}},
            "added_rows": [],
            "deleted_rows": [],
        }
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(app.button(key="confirm_checklist").disabled)
        self.assertTrue(app.error)
        self.assertEqual(app.session_state["checklist_draft"]["items"][0]["text"], "")

        app.session_state["checklist_editor"] = {
            "edited_rows": {
                0: {"text": "SQL 쿼리 작성", "keywords": ["SQL", "쿼리"]},
                2: {"level": "필수", "type": "경험"},
            },
            "added_rows": [],
            "deleted_rows": [],
        }
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertFalse(app.button(key="confirm_checklist").disabled)
        self.assertFalse(app.get("download_button"))
        self.assertIs(app.session_state["checklist_draft"]["reviewed"], False)
        app.button(key="confirm_checklist").click().run()
        self.assertEqual(len(app.get("download_button")), 1)
        confirmed = app.session_state["checklist_confirmed"]
        self.assertIs(confirmed["reviewed"], True)
        self.assertEqual(confirmed["schema_version"], 1)
        self.assertEqual(confirmed["items"][0]["keywords"], ["SQL", "쿼리"])
        self.assertEqual((confirmed["items"][2]["level"], confirmed["items"][2]["type"]), ("필수", "경험"))
        self.assertEqual(validate_checklist(confirmed), [])

        # 표와 상관없는 입력을 고쳐 화면이 다시 그려져도 확인 완료는 유지된다.
        app.text_area(key="company_info").set_value("변경한 회사정보").run()
        self.assertIn("checklist_confirmed", app.session_state)
        self.assertEqual(len(app.get("download_button")), 1)
        self.assertEqual(app.session_state["checklist_draft"]["items"][0]["text"], "SQL 쿼리 작성")
        self.assertEqual(app.session_state["resume"], "SQL로 데이터를 분석했습니다.")
        app.session_state["checklist_editor"] = {
            "edited_rows": {0: {"text": "다시 수정한 요구사항", "keywords": ["SQL"]}},
            "added_rows": [],
            "deleted_rows": [],
        }
        app.run()
        self.assertFalse(app.exception)
        self.assertNotIn("checklist_confirmed", app.session_state)
        self.assertFalse(app.get("download_button"))


if __name__ == "__main__":
    unittest.main()
