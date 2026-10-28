"""공식과 v0 체크리스트 스키마 및 샘플이 동일한 계약을 따르는지 검사한다."""

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "parsing" / "checklist.json"
SCHEMA_V0_PATH = ROOT / "schemas" / "parsing" / "checklist.v0.json"
SAMPLE_PATH = ROOT / "samples" / "checklist.sample.json"
SAMPLE_V0_PATH = ROOT / "samples" / "checklist.sample.v0.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
SAMPLE = json.loads(SAMPLE_PATH.read_text(encoding="utf-8-sig"))


class ChecklistSchemaTests(unittest.TestCase):
    def test_schema_and_samples_are_identical_and_valid(self):
        """두 계약 파일과 두 샘플이 동일하고 JSON Schema를 통과하는지 확인한다."""
        schema_v0 = json.loads(SCHEMA_V0_PATH.read_text(encoding="utf-8-sig"))
        sample_v0 = json.loads(SAMPLE_V0_PATH.read_text(encoding="utf-8-sig"))
        self.assertEqual(json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig")), schema_v0)
        self.assertEqual(SAMPLE, sample_v0)
        Draft202012Validator.check_schema(SCHEMA)
        Draft202012Validator(SCHEMA).validate(SAMPLE)

    def test_required_fields_and_item_values(self):
        """필수 필드 누락 및 합의되지 않은 항목 유형·구분을 거부하는지 확인한다."""
        validator = Draft202012Validator(SCHEMA)
        for field in SCHEMA["required"]:
            payload = json.loads(json.dumps(SAMPLE))
            del payload[field]
            self.assertFalse(validator.is_valid(payload), field)
        for key, value in (("type", "기타사항"), ("level", "선택")):
            payload = json.loads(json.dumps(SAMPLE))
            payload["items"][0][key] = value
            self.assertFalse(validator.is_valid(payload), key)


if __name__ == "__main__":
    unittest.main()
