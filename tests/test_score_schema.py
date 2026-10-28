"""합의된 항목별 채점 결과 계약을 JSON Schema 검증기로 확인한다."""

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "score.json").read_text(encoding="utf-8-sig"))
SAMPLE = json.loads((ROOT / "samples" / "score.sample.json").read_text(encoding="utf-8-sig"))
CHECKLIST = json.loads((ROOT / "samples" / "checklist.sample.json").read_text(encoding="utf-8-sig"))
VALIDATOR = Draft202012Validator(SCHEMA)


class ScoreSchemaTests(unittest.TestCase):
    def test_schema_and_sample_are_valid(self):
        """스키마와 저장된 샘플이 유효한지 검사한다."""
        Draft202012Validator.check_schema(SCHEMA)
        VALIDATOR.validate(SAMPLE)

    def test_required_fields_and_types(self):
        """필수 필드가 빠지거나 점수 자료형이 잘못되면 거부한다."""
        for field in SCHEMA["required"]:
            payload = copy.deepcopy(SAMPLE)
            del payload[field]
            self.assertFalse(VALIDATOR.is_valid(payload), field)
        for value in (-1, 11, True, "10"):
            payload = copy.deepcopy(SAMPLE)
            payload["items"][0]["score"]["earned"] = value
            self.assertFalse(VALIDATOR.is_valid(payload))

    def test_status_and_style_values(self):
        """상태와 스타일은 현재 합의된 허용값만 통과한다."""
        for status in ("충족", "미충족", "경험 없음"):
            payload = copy.deepcopy(SAMPLE)
            payload["items"][0]["status"] = status
            self.assertTrue(VALIDATOR.is_valid(payload))
        payload = copy.deepcopy(SAMPLE)
        payload["items"][0]["status"] = "통과"
        self.assertFalse(VALIDATOR.is_valid(payload))
        payload = copy.deepcopy(SAMPLE)
        payload["style_id"] = "unknown"
        self.assertFalse(VALIDATOR.is_valid(payload))

    def test_attempt_has_no_unapproved_upper_limit(self):
        """정책 합의 전 attempt 상한 없이 양의 정수 번호를 허용한다."""
        for value in (1, 4, 5, 100):
            payload = copy.deepcopy(SAMPLE)
            payload["attempt"] = value
            self.assertTrue(VALIDATOR.is_valid(payload))
        payload["attempt"] = 0
        self.assertFalse(VALIDATOR.is_valid(payload))

    def test_issue_list_and_unknown_fields(self):
        """이슈가 비어도 유효하고 미래 필드도 허용한다."""
        payload = copy.deepcopy(SAMPLE)
        payload["issues"] = []
        payload["future_field"] = True
        self.assertTrue(VALIDATOR.is_valid(payload))

    def test_item_points_follow_checklist_level_and_status(self):
        """항목 점수는 checklist 등급과 상태에 따라 필수 10점·우대 5점으로 정한다."""
        levels = {item["id"]: item["level"] for item in CHECKLIST["items"]}
        for item in SAMPLE["items"]:
            expected_max = 10 if levels[item["item_id"]] == "필수" else 5
            self.assertEqual(item["score"]["max"], expected_max)
            expected_earned = expected_max if item["status"] == "충족" else 0
            self.assertEqual(item["score"]["earned"], expected_earned)

    def test_score_has_no_total_or_per_item_deductions(self):
        """결과는 항목별 점수와 단일 issues 목록만 사용하고 총점·감점 필드를 두지 않는다."""
        self.assertNotIn("total_score", SAMPLE)
        self.assertNotIn("summary", SAMPLE)
        self.assertIn("issues", SAMPLE)
        for item in SAMPLE["items"]:
            self.assertNotIn("deductions", item)


if __name__ == "__main__":
    unittest.main()
