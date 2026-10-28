"""결과 화면에서 첫 세 스타일과 이후 단일 스타일 규칙을 검사한다."""

import unittest

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.main import _build_experience_payload, _style_batch_error


class RewriteBatchTests(unittest.TestCase):
    def test_first_attempt_requires_all_styles_once(self):
        """첫 attempt에 세 스타일이 모두 한 번씩 있어야 채점을 허용한다."""
        self.assertIsNone(_style_batch_error(["achievement", "keyword", "concise"], True, False))
        self.assertIn("세 스타일", _style_batch_error(["achievement"], True, False))
        self.assertIn("같은 스타일", _style_batch_error(["achievement", "achievement", "keyword"], True, False))

    def test_retry_requires_one_style(self):
        """재작업에서는 한 rewrite만 허용하고 세 rewrite 묶음을 거부한다."""
        self.assertIsNone(_style_batch_error(["concise"], False, False))
        self.assertIn("한 스타일", _style_batch_error(["achievement", "keyword", "concise"], False, False))

    def test_sample_preview_can_show_one_style(self):
        """명시적으로 선택한 화면 확인용 샘플은 한 스타일이어도 허용한다."""
        self.assertIsNone(_style_batch_error(["achievement"], True, True))

    def test_experience_payload_matches_github_main_record_shape(self):
        """경험 있는 항목만 공식 schema의 item_id·text 레코드로 내보낸다."""
        root = Path(__file__).resolve().parents[1]
        schema = json.loads((root / "schemas/parsing/experience.json").read_text(encoding="utf-8-sig"))
        payload = _build_experience_payload("case-01", [{"item_id": "req-1", "text": "SQL로 집계했습니다."}])
        sample = json.loads((root / "samples/experience.sample.json").read_text(encoding="utf-8-sig"))

        Draft202012Validator(schema).validate(payload)
        Draft202012Validator(schema).validate(sample)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["experiences"], [{"item_id": "req-1", "text": "SQL로 집계했습니다."}])


if __name__ == "__main__":
    unittest.main()
