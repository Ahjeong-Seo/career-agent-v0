"""화면 채점 피드백을 루프 입력 JSON으로 연결하는지 검사한다."""

import json
from pathlib import Path
import unittest

from app.feedback_bridge import build_feedback_input


ROOT = Path(__file__).resolve().parents[1]


class FeedbackBridgeTests(unittest.TestCase):
    def setUp(self):
        self.initial = json.loads((ROOT / "samples/rewrite.sample.json").read_text(encoding="utf-8"))
        self.checklist = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))
        self.experience = json.loads((ROOT / "samples/experience.sample.json").read_text(encoding="utf-8"))

    def test_feedback_lines_fill_only_matching_checklist_items(self):
        """항목 ID가 맞는 줄은 user_feedback에 채우고 그 외 문장은 원문 목록으로 남긴다."""
        payload, unmatched, unknown = build_feedback_input(
            self.initial,
            self.checklist,
            self.experience,
            "achievement",
            "req-1: SQL 활용을 강조\n일반 의견은 자동 배정하지 않음\nreq-99: 없는 항목",
        )

        self.assertEqual(payload["user_feedback"], [{"req-1": "SQL 활용을 강조", "req-2": "", "req-3": ""}])
        self.assertEqual(unmatched, ["일반 의견은 자동 배정하지 않음", "req-99: 없는 항목"])
        self.assertEqual(unknown, ["req-99"])

    def test_duplicate_feedback_lines_are_preserved_in_order(self):
        """같은 항목에 대한 여러 줄 피드백을 입력 순서로 합친다."""
        payload, unmatched, unknown = build_feedback_input(
            self.initial,
            self.checklist,
            self.experience,
            "achievement",
            "req-1: SQL 활용\nreq-1: 결과를 먼저 써 주세요",
        )

        self.assertEqual(payload["user_feedback"][0]["req-1"], "SQL 활용\n결과를 먼저 써 주세요")
        self.assertEqual(unmatched, [])
        self.assertEqual(unknown, [])


if __name__ == "__main__":
    unittest.main()
