"""확인된 체크리스트 파이프라인의 파일 저장 결과를 검사한다."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from parsing.parser_pipeline import run_pipeline_from_confirmed_checklist


class ConfirmedChecklistPipelineTests(unittest.TestCase):
    """확인된 체크리스트와 경험 초안의 저장 흐름을 확인한다."""

    def test_saves_reviewed_checklist_and_experience_draft(self):
        """reviewed=true 체크리스트와 경험 초안을 같은 케이스 폴더에 저장한다."""
        checklist = {
            "schema_version": 2,
            "case_id": "case-99",
            "job_title": "개발자",
            "company_values": [],
            "reviewed": True,
            "items": [
                {
                    "id": "req-1",
                    "text": "Python 개발 경험",
                    "keywords": ["Python"],
                    "type": "기술",
                    "level": "필수",
                    "years": None,
                }
            ],
        }
        draft = {
            "case_id": "case-99",
            "schema_version": 1,
            "prompt_version": "parsing_experience_draft_v1",
            "experiences": [
                {"item_id": "req-1", "text": "Python 자동화 작업", "years": None}
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory)
            with (
                patch("parsing.parser_pipeline.get_case_directory", return_value=case_dir),
                patch("parsing.experience_parser.get_case_directory", return_value=case_dir),
                patch("parsing.experience_parser.parse_experience", return_value=draft),
                patch("parsing.experience_parser._record_prompt_version"),
            ):
                case_id, output_paths, errors = run_pipeline_from_confirmed_checklist(
                    "채용공고\nPython 개발 경험",
                    "Python 자동화 작업",
                    checklist,
                    case_id="case-99",
                )

            self.assertEqual(errors, [])
            self.assertEqual(case_id, "case-99")
            self.assertEqual(
                set(output_paths),
                {"job_txt", "resume_txt", "checklist", "experience_draft"},
            )

            saved_checklist = json.loads(
                (case_dir / "checklist.json").read_text(encoding="utf-8")
            )
            saved_draft = json.loads(
                (case_dir / "experience_draft.json").read_text(encoding="utf-8")
            )
            self.assertTrue(saved_checklist["reviewed"])
            self.assertEqual(saved_checklist["case_id"], "case-99")
            self.assertEqual(saved_draft, draft)
            self.assertEqual(output_paths["experience_draft"], case_dir / "experience_draft.json")


if __name__ == "__main__":
    unittest.main()
