import io
import json
import unittest
from unittest.mock import patch

from app.main import ask_rewrite_again, main


class MainFlowTests(unittest.TestCase):
    def test_continue_answer_ignores_terminal_residue(self):
        """Esc 제어 코드와 인코딩 불가 문자가 섞인 선택을 받아 계속 여부를 돌려준다."""
        with patch("sys.stdin", io.StringIO("\x1b[2K\udcffn\n")), patch(
            "sys.stderr", new_callable=io.StringIO
        ) as progress:
            answer = ask_rewrite_again()
        self.assertFalse(answer)
        self.assertNotIn("y 또는 n으로 입력해 주세요.", progress.getvalue())

    def test_prints_sentences_then_final_json(self):
        """두 재작성 결과를 받아 문장을 먼저 보이고 마지막 JSON만 돌려준다."""
        first = {
            "attempt": 2,
            "revised_cv": [{"sentences": [{"item_id": "req-1", "text": "첫 문장"}]}],
        }
        final = {
            "attempt": 3,
            "revised_cv": [{"sentences": [{"item_id": "req-1", "text": "최종 문장"}]}],
        }
        with patch("sys.argv", ["main.py"]), patch("sys.stdin", io.StringIO("y\nn\n")), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as output, patch("sys.stderr", new_callable=io.StringIO) as progress, patch(
            "app.main.data_input", return_value={}
        ), patch("app.main.revise_cv", return_value={}), patch(
            "app.main.rewrite_cv", side_effect=[first, final]
        ) as rewrite:
            status = main()

        self.assertEqual(status, 0)
        self.assertEqual(rewrite.call_count, 2)
        self.assertEqual(json.loads(output.getvalue()), final)
        self.assertEqual(output.getvalue().count('"attempt"'), 1)
        self.assertIn("첫 문장", progress.getvalue())
        self.assertIn("최종 문장", progress.getvalue())
        self.assertIn("피드백 1/3 반영 결과", progress.getvalue())
        self.assertIn("피드백 2/3 반영 결과", progress.getvalue())
        self.assertEqual(progress.getvalue().count("피드백을 더 반영할까요?"), 2)

    def test_allows_three_feedback_rounds_after_first_revision(self):
        """최초 첨삭 뒤 피드백 세 번을 받아 세 번째 결과의 JSON을 돌려준다."""
        results = [
            {
                "attempt": attempt,
                "revised_cv": [{"sentences": [{"item_id": "req-1", "text": f"문장 {attempt}"}]}],
            }
            for attempt in (2, 3, 4)
        ]
        with patch("sys.argv", ["main.py"]), patch("sys.stdin", io.StringIO("y\ny\n")), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as output, patch("sys.stderr", new_callable=io.StringIO) as progress, patch(
            "app.main.data_input", return_value={}
        ), patch("app.main.revise_cv", return_value={}), patch(
            "app.main.rewrite_cv", side_effect=results
        ) as rewrite:
            status = main()

        self.assertEqual(status, 0)
        self.assertEqual(rewrite.call_count, 3)
        self.assertEqual(json.loads(output.getvalue()), results[-1])
        self.assertIn("피드백 3/3 반영 결과", progress.getvalue())
        self.assertEqual(progress.getvalue().count("피드백을 더 반영할까요?"), 2)


if __name__ == "__main__":
    unittest.main()
