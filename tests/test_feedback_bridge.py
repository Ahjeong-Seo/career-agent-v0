"""화면 의견을 새 feedback_input 계약으로 묶는지 검사한다."""

import json
from pathlib import Path
import unittest

from unittest.mock import patch

from app.feedback_bridge import build_feedback_input, has_rewrite_feedback, run_feedback_rewrite
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


class RunFeedbackRewriteTests(unittest.TestCase):
    """화면이 부르는 재작성 실행 함수가 결과와 오류를 문장으로 돌려주는지 검사한다."""

    def setUp(self):
        initial = json.loads((ROOT / "samples/rewrite.sample.json").read_text(encoding="utf-8"))
        checklist = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))
        experience = json.loads((ROOT / "samples/experience.sample.json").read_text(encoding="utf-8"))
        self.make_payload = lambda user_feedback, score_text: build_feedback_input(
            initial, checklist, experience, "achievement", user_feedback, score_text
        )[0]
        self.no_user_feedback = [
            {"item_id": item_id, "given": False, "text": None} for item_id in ("req-1", "req-2", "req-3")
        ]

    def test_returns_next_attempt_when_score_feedback_exists(self):
        payload = self.make_payload(self.no_user_feedback, "req-1: 키워드 보완")
        answer = {"sentences": [{"item_id": "req-1", "text": "SQL로 대시보드를 만들었습니다.", "llm_opinion": "반영"}]}
        with patch("loop.retry_rewrite.call_llm", return_value=answer):
            result, errors = run_feedback_rewrite(payload)
        self.assertEqual(errors, [])
        self.assertEqual(result["attempt"], 2)
        self.assertEqual(result["score_feedback"], [])

    def test_nothing_to_rewrite_becomes_error_message(self):
        payload = self.make_payload(self.no_user_feedback, "")
        with patch("loop.retry_rewrite.call_llm") as call_llm:
            result, errors = run_feedback_rewrite(payload)
        call_llm.assert_not_called()
        self.assertIsNone(result)
        self.assertIn("다시 쓸 항목이 없습니다", errors[0])

    def test_codex_failure_becomes_error_message(self):
        payload = self.make_payload(self.no_user_feedback, "req-1: 키워드 보완")
        with patch("loop.retry_rewrite.call_llm", side_effect=RuntimeError("Codex 호출이 두 번 실패했습니다")):
            result, errors = run_feedback_rewrite(payload)
        self.assertIsNone(result)
        self.assertEqual(errors, ["Codex 호출이 두 번 실패했습니다"])


if __name__ == "__main__":
    unittest.main()
