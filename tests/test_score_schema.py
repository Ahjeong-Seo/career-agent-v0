"""합의된 채점 결과 형식을 실제 JSON Schema 검증기로 확인한다."""

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "score.json").read_text(encoding="utf-8"))
SAMPLE = json.loads((ROOT / "samples" / "score.sample.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


class ScoreSchemaTests(unittest.TestCase):
    def test_schema_and_sample_are_valid(self):
        """스키마와 저장된 샘플을 받아 형식이 유효한지 확인하고 값을 반환하지 않는다."""
        Draft202012Validator.check_schema(SCHEMA)
        VALIDATOR.validate(SAMPLE)

    def test_every_top_level_field_is_required(self):
        """각 필수 키가 빠진 샘플을 받아 거부되는지 확인하고 값을 반환하지 않는다."""
        for field in (
            "schema_version", "case_id", "attempt", "style_id", "passed",
            "items", "made_up_numbers", "ai_phrases", "feedback",
        ):
            with self.subTest(field=field):
                payload = copy.deepcopy(SAMPLE)
                del payload[field]
                self.assertFalse(VALIDATOR.is_valid(payload))

    def test_wrong_top_level_types_are_rejected(self):
        """잘못된 자료형을 넣은 결과를 받아 거부 여부를 확인하고 값을 반환하지 않는다."""
        invalid_values = {
            "schema_version": [True, "1", 1.5, None],
            "case_id": [1, None],
            "attempt": [True, "1", 1.5, None],
            "style_id": [1, None],
            "passed": [0, 1, "false", None],
            "items": [{}, None],
            "made_up_numbers": [{}, None],
            "ai_phrases": [{}, None],
            "feedback": [[], None],
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    payload = copy.deepcopy(SAMPLE)
                    payload[field] = value
                    self.assertFalse(VALIDATOR.is_valid(payload))

    def test_nested_required_fields_and_types(self):
        """각 목록의 필수 키 및 자료형 오류를 받아 거부 여부를 확인하고 값을 반환하지 않는다."""
        required_fields = {
            "items": ("item_id", "status", "reason"),
            "made_up_numbers": ("item_id", "number", "reason"),
            "ai_phrases": ("item_id", "phrase"),
        }
        for collection, fields in required_fields.items():
            for field in fields:
                with self.subTest(collection=collection, field=field, error="missing"):
                    payload = copy.deepcopy(SAMPLE)
                    del payload[collection][0][field]
                    self.assertFalse(VALIDATOR.is_valid(payload))
                with self.subTest(collection=collection, field=field, error="type"):
                    payload = copy.deepcopy(SAMPLE)
                    payload[collection][0][field] = 1
                    self.assertFalse(VALIDATOR.is_valid(payload))
            with self.subTest(collection=collection, error="non_object"):
                payload = copy.deepcopy(SAMPLE)
                payload[collection] = ["항목"]
                self.assertFalse(VALIDATOR.is_valid(payload))

    def test_attempt_limits_and_version(self):
        """생성 회차 및 스키마 버전 경곗값을 받아 검사하고 값을 반환하지 않는다."""
        for attempt in (1, 2, 3, 4):
            with self.subTest(attempt=attempt):
                payload = copy.deepcopy(SAMPLE)
                payload["attempt"] = attempt
                self.assertTrue(VALIDATOR.is_valid(payload))
        for field, value in (("attempt", 0), ("attempt", 5), ("schema_version", 0)):
            with self.subTest(field=field, value=value):
                payload = copy.deepcopy(SAMPLE)
                payload[field] = value
                self.assertFalse(VALIDATOR.is_valid(payload))

    def test_style_and_status_enums(self):
        """합의한 스타일과 상태 및 잘못된 값을 받아 검사하고 값을 반환하지 않는다."""
        for style in ("achievement", "keyword", "concise"):
            with self.subTest(style=style):
                payload = copy.deepcopy(SAMPLE)
                payload["style_id"] = style
                self.assertTrue(VALIDATOR.is_valid(payload))
        for status in ("충족", "미충족", "경험 없음"):
            with self.subTest(status=status):
                payload = copy.deepcopy(SAMPLE)
                payload["items"][0]["status"] = status
                self.assertTrue(VALIDATOR.is_valid(payload))
        payload = copy.deepcopy(SAMPLE)
        payload["style_id"] = "성과 강조형"
        self.assertFalse(VALIDATOR.is_valid(payload))
        payload = copy.deepcopy(SAMPLE)
        payload["items"][0]["status"] = "통과"
        self.assertFalse(VALIDATOR.is_valid(payload))

    def test_unknown_fields_remain_compatible(self):
        """최상위와 중첩 객체에 모르는 키를 넣어 허용되는지 확인하고 값을 반환하지 않는다."""
        payload = copy.deepcopy(SAMPLE)
        payload["future_metadata"] = {"note": "새 필드는 소비 코드에서 무시"}
        for collection in ("items", "made_up_numbers", "ai_phrases"):
            payload[collection][0]["future_metadata"] = "추가 정보"
        self.assertTrue(VALIDATOR.is_valid(payload))

    def test_passed_requires_empty_feedback(self):
        """통과 결과의 피드백을 받아 빈 문자열 조건을 검사하고 값을 반환하지 않는다."""
        payload = copy.deepcopy(SAMPLE)
        payload["passed"] = True
        payload["made_up_numbers"] = []
        payload["ai_phrases"] = []
        payload["feedback"] = ""
        self.assertTrue(VALIDATOR.is_valid(payload))
        for feedback in ("수정 필요", " "):
            with self.subTest(feedback=feedback):
                payload["feedback"] = feedback
                self.assertFalse(VALIDATOR.is_valid(payload))

    def test_empty_issue_lists_are_valid(self):
        """오류가 없는 목록을 빈 배열로 받아 허용되는지 확인하고 값을 반환하지 않는다."""
        payload = copy.deepcopy(SAMPLE)
        payload["made_up_numbers"] = []
        payload["ai_phrases"] = []
        self.assertTrue(VALIDATOR.is_valid(payload))


if __name__ == "__main__":
    unittest.main()
