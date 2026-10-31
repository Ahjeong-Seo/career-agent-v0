"""합의된 첨삭 결과 형식을 실제 JSON Schema 검증기로 확인한다."""

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "rewrite.json").read_text(encoding="utf-8"))
SAMPLE = json.loads((ROOT / "samples" / "rewrite.sample.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


class RewriteSchemaTests(unittest.TestCase):
    def test_schema_and_sample_are_valid(self):
        """스키마와 저장된 샘플을 받아 형식이 유효한지 확인하고 값을 반환하지 않는다."""
        Draft202012Validator.check_schema(SCHEMA)
        VALIDATOR.validate(SAMPLE)

    def test_every_top_level_field_is_required(self):
        """각 필수 키가 빠진 샘플을 받아 거부되는지 확인하고 값을 반환하지 않는다."""
        for field in ("schema_version", "case_id", "prompt_version", "attempt", "style", "revised_cv"):
            with self.subTest(field=field):
                payload = copy.deepcopy(SAMPLE)
                del payload[field]
                self.assertFalse(VALIDATOR.is_valid(payload))

    def test_wrong_top_level_types_are_rejected(self):
        """잘못된 자료형을 넣은 결과를 받아 거부 여부를 확인하고 값을 반환하지 않는다."""
        invalid_values = {
            "schema_version": [True, "1", 1.5, None],
            "case_id": [1, None],
            "prompt_version": [1, None],
            "attempt": [True, "1", 1.5, None],
            "style": [1, None],
            "revised_cv": [{}, None],
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    payload = copy.deepcopy(SAMPLE)
                    payload[field] = value
                    self.assertFalse(VALIDATOR.is_valid(payload))

    def test_attempt_limits_and_version(self):
        """생성 회차 및 스키마 버전 경곗값을 받아 검사하고 값을 반환하지 않는다."""
        for attempt in (1, 2, 3, 4):
            with self.subTest(attempt=attempt):
                payload = copy.deepcopy(SAMPLE)
                payload["attempt"] = attempt
                if attempt == 1:
                    # attempt==1은 샘플 그대로 유효
                    self.assertTrue(VALIDATOR.is_valid(payload))
                else:
                    # attempt>1은 revised_cv 1개, style 지정 필요
                    payload["style"] = "achievement"
                    payload["revised_cv"] = [payload["revised_cv"][0]]
                    self.assertTrue(VALIDATOR.is_valid(payload))
        for field, value in (("attempt", 0), ("attempt", 5), ("schema_version", 0)):
            with self.subTest(field=field, value=value):
                payload = copy.deepcopy(SAMPLE)
                payload[field] = value
                self.assertFalse(VALIDATOR.is_valid(payload))

    def test_style_enums(self):
        """합의한 style 열거값 및 잘못된 값을 받아 검사하고 값을 반환하지 않는다."""
        for style in ("achievement", "keyword", "concise"):
            with self.subTest(style=style):
                payload = copy.deepcopy(SAMPLE)
                # attempt>1일 때 각 스타일을 검사
                payload["attempt"] = 2
                payload["style"] = style
                payload["revised_cv"] = [payload["revised_cv"][0]]
                self.assertTrue(VALIDATOR.is_valid(payload))
        payload = copy.deepcopy(SAMPLE)
        payload["style"] = "성과 강조형"
        self.assertFalse(VALIDATOR.is_valid(payload))

    def test_attempt_1_requires_empty_style_and_three_revised_cv(self):
        """attempt==1일 때 style이 \"\"이고 revised_cv가 정확히 3개여야 하는 조건을 검사한다."""
        # style이 비어 있지 않으면 거부
        payload = copy.deepcopy(SAMPLE)
        payload["attempt"] = 1
        payload["style"] = "achievement"
        self.assertFalse(VALIDATOR.is_valid(payload))

        # revised_cv가 3개 미만이면 거부
        payload2 = copy.deepcopy(SAMPLE)
        payload2["attempt"] = 1
        payload2["style"] = ""
        payload2["revised_cv"] = payload2["revised_cv"][:2]
        self.assertFalse(VALIDATOR.is_valid(payload2))

        # revised_cv가 4개 이상이면 거부
        payload3 = copy.deepcopy(SAMPLE)
        payload3["attempt"] = 1
        payload3["style"] = ""
        payload3["revised_cv"].append(payload3["revised_cv"][0])
        self.assertFalse(VALIDATOR.is_valid(payload3))

    def test_attempt_gt1_requires_single_revised_cv_and_nonempty_style(self):
        """attempt>1일 때 revised_cv가 정확히 1개이고 style이 지정돼야 하는 조건을 검사한다."""
        # revised_cv 2개면 거부
        payload = copy.deepcopy(SAMPLE)
        payload["attempt"] = 2
        payload["style"] = "achievement"
        payload["revised_cv"] = payload["revised_cv"][:2]
        self.assertFalse(VALIDATOR.is_valid(payload))

    def test_nested_required_fields_and_types(self):
        """revised_cv 항목의 필수 키 및 자료형 오류를 받아 거부 여부를 확인하고 값을 반환하지 않는다."""
        invalid_type_values = {
            "attempt": "1",   # 문자열은 integer 타입에 거부돼야 한다
            "style": 1,       # 숫자는 string 타입에 거부돼야 한다
            "sentences": {},  # 객체는 array 타입에 거부돼야 한다
        }
        for field in ("attempt", "style", "sentences"):
            with self.subTest(field=field, error="missing"):
                payload = copy.deepcopy(SAMPLE)
                del payload["revised_cv"][0][field]
                self.assertFalse(VALIDATOR.is_valid(payload))
            with self.subTest(field=field, error="type"):
                payload = copy.deepcopy(SAMPLE)
                payload["revised_cv"][0][field] = invalid_type_values[field]
                self.assertFalse(VALIDATOR.is_valid(payload))

    def test_sentence_required_fields(self):
        """sentences 항목의 필수 키가 빠진 경우를 받아 거부 여부를 확인하고 값을 반환하지 않는다."""
        for field in ("item_id", "source", "text", "llm_opinion", "user_feedback"):
            with self.subTest(field=field):
                payload = copy.deepcopy(SAMPLE)
                del payload["revised_cv"][0]["sentences"][0][field]
                self.assertFalse(VALIDATOR.is_valid(payload))

    def test_unknown_fields_remain_compatible(self):
        """최상위와 중첩 객체에 모르는 키를 넣어 허용되는지 확인하고 값을 반환하지 않는다."""
        payload = copy.deepcopy(SAMPLE)
        payload["future_metadata"] = {"note": "새 필드는 소비 코드에서 무시"}
        payload["revised_cv"][0]["extra"] = "추가 정보"
        payload["revised_cv"][0]["sentences"][0]["extra"] = "추가 정보"
        self.assertTrue(VALIDATOR.is_valid(payload))


if __name__ == "__main__":
    unittest.main()
