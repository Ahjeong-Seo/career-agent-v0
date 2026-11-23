"""화면 의견을 새 feedback_input 계약으로 묶는지 검사한다."""

import json
from pathlib import Path
import unittest

from app.feedback_bridge import build_feedback_input, has_rewrite_feedback
from app.style_select import rewrites_by_style


ROOT = Path(__file__).resolve().parents[1]


class FeedbackBridgeTests(unittest.TestCase):
    def setUp(self):
        self.initial = json.loads((ROOT / "samples/rewrite.sample.json").read_text(encoding="utf-8"))
        self.checklist = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))
        self.experience = json.loads((ROOT / "samples/experience.sample.json").read_text(encoding="utf-8"))
        self.user_feedback = [
            {"item_id": "req-1", "given": True, "text": "SQL을 강조해 주세요."},
            {"item_id": "req-2", "given": False, "text": None},
            {"item_id": "req-3", "given": False, "text": None},
        ]

    def test_user_and_score_feedback_are_separate_and_unknown_lines_are_reported(self):
        payload, unmatched, unknown = build_feedback_input(
            self.initial, self.checklist, self.experience, "achievement", self.user_feedback,
            "req-1: 키워드 보완\nreq-3: 경험 없는 항목 의견\n일반 메모\nreq-99: 없는 항목",
        )
        self.assertEqual(payload["user_feedback"], self.user_feedback)
        self.assertEqual(payload["score_feedback"], [{"item_id": "req-1", "text": "키워드 보완"}])
        self.assertEqual(unmatched, ["일반 메모", "req-99: 없는 항목"])
        self.assertEqual(unknown, ["req-99"])

    def test_duplicate_score_lines_are_merged_in_order(self):
        payload, unmatched, unknown = build_feedback_input(
            self.initial, self.checklist, self.experience, "achievement", self.user_feedback,
            "req-1: 첫 의견\nreq-1: 둘째 의견",
        )
        self.assertEqual(payload["score_feedback"], [{"item_id": "req-1", "text": "첫 의견\n둘째 의견"}])
        self.assertEqual(unmatched, [])
        self.assertEqual(unknown, [])

    def test_score_feedback_alone_can_start_a_retry(self):
        payload, _, _ = build_feedback_input(
            self.initial, self.checklist, self.experience, "achievement",
            [{"item_id": "req-1", "given": False, "text": None},
             {"item_id": "req-2", "given": False, "text": None},
             {"item_id": "req-3", "given": False, "text": None}],
            "req-1: 키워드 보완",
        )
        self.assertTrue(has_rewrite_feedback(payload))

    def test_retry_result_uses_common_feedback_input_preparation(self):
        """재작성 결과도 공통 입력 준비 함수를 거쳐 양쪽 의견을 분리한다."""
        previous_output = json.loads(
            (ROOT / "samples/feedback_output.sample.json").read_text(encoding="utf-8")
        )
        current = rewrites_by_style(previous_output)[0]

        payload, _, _ = build_feedback_input(
            current, self.checklist, self.experience, "achievement", self.user_feedback,
            "req-1: 채점 의견",
        )

        self.assertEqual(payload["attempt"], 2)
        self.assertEqual(payload["old_revised_cv"], previous_output["old_revised_cv"])
        self.assertEqual(payload["revised_cv"][0]["attempt"], 2)
        self.assertEqual(payload["score_feedback"], [{"item_id": "req-1", "text": "채점 의견"}])

    def test_no_opinions_do_not_start_a_retry(self):
        payload, _, _ = build_feedback_input(
            self.initial, self.checklist, self.experience, "achievement",
            [{"item_id": "req-1", "given": False, "text": None},
             {"item_id": "req-2", "given": False, "text": None},
             {"item_id": "req-3", "given": False, "text": None}], "",
        )
        self.assertFalse(has_rewrite_feedback(payload))


if __name__ == "__main__":
    unittest.main()
