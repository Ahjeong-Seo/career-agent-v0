"""화면 채점 피드백을 루프 입력 JSON으로 연결하는지 검사한다."""

import json
from pathlib import Path
import unittest

from app.feedback_bridge import build_feedback_input, has_rewrite_feedback


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

    def test_retry_input_uses_the_current_attempt_and_keeps_earlier_history(self):
        """재작성 차수의 다음 입력은 첫 생성이 아니라 현재 결과와 앞선 이력을 사용한다."""
        first_payload, _, _ = build_feedback_input(
            self.initial, self.checklist, self.experience, "achievement", ""
        )
        first_revision = first_payload["revised_cv"][0]
        second_revision = {**first_revision, "attempt": 2}
        third_revision = {**first_revision, "attempt": 3}
        current_rewrite = {
            "schema_version": 1,
            "case_id": first_payload["case_id"],
            "prompt_version": "rewrite_retry_v2",
            "attempt": 3,
            "style_id": "achievement",
            "requirements": first_payload["requirements"],
            "experiences": first_payload["experiences"],
            "user_feedback": first_payload["user_feedback"],
            "old_revised_cv": [first_revision, second_revision],
            "style": "achievement",
            "sentences": third_revision["sentences"],
        }

        payload, unmatched, unknown = build_feedback_input(
            current_rewrite, self.checklist, self.experience, "achievement", "req-2: SQL 강조"
        )

        self.assertEqual(payload["attempt"], 3)
        self.assertEqual([row["attempt"] for row in payload["old_revised_cv"]], [1, 2])
        self.assertEqual(payload["revised_cv"][0]["attempt"], 3)
        self.assertEqual(payload["user_feedback"][0]["req-2"], "SQL 강조")
        self.assertEqual(unmatched, [])
        self.assertEqual(unknown, [])

    def test_only_feedback_for_experienced_items_can_start_a_retry(self):
        """경험 항목에 연결된 의견이 있을 때만 재작성을 시작할 수 있다."""
        empty_payload, _, _ = build_feedback_input(
            self.initial, self.checklist, self.experience, "achievement", ""
        )
        mapped_payload, _, _ = build_feedback_input(
            self.initial, self.checklist, self.experience, "achievement", "req-1: 한 항목 의견"
        )

        self.assertFalse(has_rewrite_feedback(empty_payload))
        self.assertTrue(has_rewrite_feedback(mapped_payload))


if __name__ == "__main__":
    unittest.main()
