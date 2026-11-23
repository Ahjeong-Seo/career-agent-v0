"""feedback_loop가 새 계약을 준비하고 기준 재작성 함수에 위임하는지 확인한다."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.style_select import rewrites_by_style
from loop.feedback_loop import main, prepare_feedback_input, rewrite_with_feedback


ROOT = Path(__file__).resolve().parents[1]


class FeedbackLoopTests(unittest.TestCase):
    def setUp(self):
        self.initial = json.loads((ROOT / "samples/rewrite.sample.json").read_text(encoding="utf-8"))
        self.checklist = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))
        self.experience = json.loads((ROOT / "samples/experience.sample.json").read_text(encoding="utf-8"))
        self.data = prepare_feedback_input(self.initial, self.checklist, self.experience, "achievement")

    def test_prepare_feedback_input_lists_every_item_and_empty_score_feedback(self):
        self.assertEqual(self.data["schema_version"], 2)
        self.assertEqual(
            self.data["user_feedback"],
            [{"item_id": item["id"], "given": False, "text": None} for item in self.checklist["items"]],
        )
        self.assertEqual(self.data["score_feedback"], [])

    def test_prepare_feedback_input_accepts_flat_first_attempt_rewrite(self):
        """화면에서 받는 1차 단일 스타일 결과를 다음 입력 기본 객체로 바꾼다."""
        current = rewrites_by_style(self.initial)[0]

        data = prepare_feedback_input(current, self.checklist, self.experience, current["style_id"])

        self.assertEqual(data["attempt"], 1)
        self.assertEqual(data["style_id"], current["style_id"])
        self.assertEqual(data["revised_cv"][0]["sentences"], current["sentences"])

    def test_prepare_feedback_input_from_retry_result_preserves_history_and_resets_feedback(self):
        """재작성 결과를 다음 입력으로 바꾸며 이력을 보존하고 회차 의견을 초기화한다."""
        previous = json.loads((ROOT / "samples/feedback_output.sample.json").read_text(encoding="utf-8"))

        data = prepare_feedback_input(previous, self.checklist, self.experience, "achievement")

        self.assertEqual(data["attempt"], 2)
        self.assertEqual(data["style_id"], "achievement")
        self.assertEqual(data["old_revised_cv"], previous["old_revised_cv"])
        self.assertEqual(data["revised_cv"], previous["revised_cv"])
        self.assertEqual(
            data["user_feedback"],
            [{"item_id": item["id"], "given": False, "text": None} for item in self.checklist["items"]],
        )
        self.assertEqual(data["score_feedback"], [])

    def test_user_and_score_feedback_are_passed_separately_and_history_is_kept(self):
        data = {**self.data, "user_feedback": [
            {"item_id": "req-1", "given": True, "text": "SQL 의견"},
            {"item_id": "req-2", "given": False, "text": None},
            {"item_id": "req-3", "given": False, "text": None},
        ], "score_feedback": [{"item_id": "req-1", "text": "채점 의견"}]}
        answer = {"sentences": [{"item_id": "req-1", "text": "SQL 문장", "llm_opinion": "반영"}]}
        with patch("loop.retry_rewrite.call_llm", return_value=answer) as call_llm:
            result = rewrite_with_feedback(data)
        prompt = call_llm.call_args.args[0]
        self.assertIn('"user_feedback": "SQL 의견"', prompt)
        self.assertIn('"score_feedback": "채점 의견"', prompt)
        self.assertEqual(result["old_revised_cv"][0]["sentences"][0]["user_feedback"], "SQL 의견")
        self.assertEqual(result["user_feedback"][0], {"item_id": "req-1", "given": False, "text": None})
        self.assertEqual(result["revised_cv"][0]["sentences"][1]["text"], data["revised_cv"][0]["sentences"][1]["text"])

    def test_score_feedback_alone_starts_retry(self):
        data = {**self.data, "score_feedback": [{"item_id": "req-1", "text": "SQL 채점 의견"}]}
        answer = {"sentences": [{"item_id": "req-1", "text": "SQL 문장", "llm_opinion": "반영"}]}
        with patch("loop.retry_rewrite.call_llm", return_value=answer) as call_llm:
            result = rewrite_with_feedback(data)
        call_llm.assert_called_once()
        self.assertEqual(result["attempt"], 2)

    def test_no_feedback_returns_none_without_advancing_attempt(self):
        with patch("loop.retry_rewrite.call_llm") as call_llm:
            self.assertIsNone(rewrite_with_feedback(self.data))
        call_llm.assert_not_called()
        self.assertEqual(self.data["attempt"], 1)

    def test_attempt_four_cannot_be_rewritten(self):
        data = {**self.data, "attempt": 4}
        data["revised_cv"] = [{**data["revised_cv"][0], "attempt": 4}]
        with self.assertRaisesRegex(ValueError, "최대 attempt 4"):
            rewrite_with_feedback(data, {"req-1": "추가 의견"})

    def test_cli_does_not_write_output_when_feedback_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / "feedback_input.json"
            output_path = Path(temporary) / "feedback_output.json"
            input_path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            with patch("sys.argv", ["feedback_loop.py", str(input_path), "--output", str(output_path)]):
                self.assertEqual(main(), 0)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
