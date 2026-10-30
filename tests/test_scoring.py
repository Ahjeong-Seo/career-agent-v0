"""기존 score 계약에 맞는 규칙 채점을 검사한다."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from scoring.score import score_case


ROOT = Path(__file__).resolve().parents[1]


class ScoreCaseTests(unittest.TestCase):
    """가짜 체크리스트·경험·rewrite를 채점해 계약과 판정 규칙을 검사한다."""

    def setUp(self):
        """저장소의 샘플 파일을 읽어 독립적인 테스트 입력을 준비한다."""
        self.checklist = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))
        self.experience = json.loads((ROOT / "samples/experience.sample.json").read_text(encoding="utf-8"))
        self.experience["schema_version"] = 1
        self.rewrite = json.loads((ROOT / "samples/rewrite.sample.json").read_text(encoding="utf-8"))
        self.rewrite["style_id"] = "achievement"

    def test_score_matches_existing_schema_and_finds_made_up_number_and_ai_phrase(self):
        """샘플을 채점해 현재 score 스키마 필드만 출력하고 숫자·AI 표현을 찾는다."""
        result = score_case(self.checklist, self.experience, self.rewrite)
        schema = json.loads((ROOT / "schemas/score.json").read_text(encoding="utf-8"))

        self.assertTrue(Draft202012Validator(schema).is_valid(result))
        self.assertFalse(result["passed"])
        self.assertEqual(result["made_up_numbers"][0]["number"], "3")
        self.assertEqual(result["ai_phrases"][0]["phrase"], "적극적으로 기여")
        self.assertNotIn("score", result)
        self.assertNotIn("checks", result)
        self.assertNotIn("issues", result)

    def test_required_missing_keyword_fails_but_career_years_are_not_judged(self):
        """키워드 누락은 미충족으로 보고 경력 연수는 판정하지 않는다."""
        experience = deepcopy(self.experience)
        rewrite = deepcopy(self.rewrite)
        rewrite["sentences"][1]["text"] = "Excel 업무 자동화"
        result = score_case(self.checklist, experience, rewrite)

        self.assertFalse(result["passed"])
        self.assertEqual(result["items"][1]["status"], "미충족")
        self.assertIn("연수 미확인", result["items"][1]["reason"])

    def test_missing_experience_with_sentence_fails_and_adds_feedback(self):
        """경험이 없는 항목에 문장이 있으면 경험 없음으로 표시하고 삭제 feedback을 만든다."""
        experience = {"case_id": "case-01", "experiences": []}
        rewrite = {
            "case_id": "case-01",
            "style_id": "concise",
            "attempt": 1,
            "sentences": [{"item_id": "req-1", "source": "", "text": "SQL 활용"}],
        }
        result = score_case(self.checklist, experience, rewrite)

        self.assertFalse(result["passed"])
        self.assertEqual(result["items"][0]["status"], "경험 없음")
        self.assertIn("경험 없는 항목의 문장 삭제", result["feedback"])

    def test_rewrite_source_must_match_experience(self):
        """rewrite.source와 경험 원문이 다르면 채점을 중단한다."""
        rewrite = deepcopy(self.rewrite)
        rewrite["sentences"][0]["source"] = "다른 원문"
        with self.assertRaisesRegex(ValueError, "source와 experience.text"):
            score_case(self.checklist, self.experience, rewrite)

    def test_experience_free_item_cannot_claim_a_source(self):
        """경험 데이터가 없는 항목에는 rewrite.source도 둘 수 없다."""
        experience = {"case_id": "case-01", "experiences": []}
        rewrite = {
            "case_id": "case-01",
            "style_id": "concise",
            "attempt": 1,
            "sentences": [{"item_id": "req-1", "source": "SQL 경험", "text": "SQL"}],
        }
        with self.assertRaisesRegex(ValueError, "경험 입력이 없는 항목"):
            score_case(self.checklist, experience, rewrite)

    def test_successful_result_has_empty_feedback(self):
        """필수 키워드가 있고 숫자·AI 표현이 없으면 통과와 빈 feedback을 반환한다."""
        checklist = deepcopy(self.checklist)
        checklist["items"] = checklist["items"][:1]
        experience = {"case_id": "case-01", "experiences": [{"item_id": "req-1", "text": "SQL 쿼리 작성"}]}
        rewrite = {
            "case_id": "case-01",
            "style_id": "keyword",
            "attempt": 1,
            "sentences": [{"item_id": "req-1", "source": "SQL 쿼리 작성", "text": "SQL 쿼리 작성"}],
        }
        result = score_case(checklist, experience, rewrite)
        self.assertTrue(result["passed"])
        self.assertEqual(result["feedback"], "")

    def test_advisory_item_warnings_are_shown_but_do_not_change_pass(self):
        """우대 항목 경고는 결과에 남기되 통과 계산에는 넣지 않는다."""
        checklist = deepcopy(self.checklist)
        checklist["items"] = [checklist["items"][0], checklist["items"][2]]
        experience = {
            "case_id": "case-01",
            "experiences": [
                {"item_id": "req-1", "text": "SQL 쿼리 작성"},
                {"item_id": "req-3", "text": "데이터 분석"},
            ],
        }
        rewrite = {
            "case_id": "case-01",
            "style_id": "achievement",
            "attempt": 1,
            "sentences": [
                {"item_id": "req-1", "source": "SQL 쿼리 작성", "text": "SQL 쿼리 작성"},
                {"item_id": "req-3", "source": "데이터 분석", "text": "대용량 데이터 100명, 적극적으로 기여"},
            ],
        }
        result = score_case(checklist, experience, rewrite)
        self.assertTrue(result["passed"])
        self.assertEqual(result["made_up_numbers"][0]["number"], "100")
        self.assertEqual(result["ai_phrases"][0]["phrase"], "적극적으로 기여")


if __name__ == "__main__":
    unittest.main()
