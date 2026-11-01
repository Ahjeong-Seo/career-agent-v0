import io
import unittest
from unittest.mock import patch

from app.loop.data_input import ask_experiences
from app.loop.rewrite_cv import getUserFeedback


class TerminalInputTests(unittest.TestCase):
    def test_feedback_ignores_escape_and_invalid_byte(self):
        """Esc와 잘못된 바이트가 섞인 피드백을 받아 정상 문장만 돌려준다."""
        sentences = [{"item_id": "req-1", "source": "원문", "text": "초안"}]
        with patch("sys.stdin", io.StringIO("\x1b\udcff수정 피드백\n")), patch(
            "sys.stderr", new_callable=io.StringIO
        ) as error_output:
            result = getUserFeedback(sentences)
        self.assertEqual(result, {"req-1": "수정 피드백"})
        self.assertNotIn("인코딩 오류", error_output.getvalue())

    def test_experience_ignores_terminal_escape_sequence(self):
        """터미널 제어 코드가 섞인 경험을 받아 실제 경험 텍스트만 돌려준다."""
        items = [{"id": "req-1", "text": "SQL", "level": "필수"}]
        with patch("sys.stdin", io.StringIO("\x1b[2K\udcffSQL 사용\n")), patch(
            "sys.stderr", new_callable=io.StringIO
        ) as error_output:
            result = ask_experiences(items)
        self.assertEqual(result, {"req-1": "SQL 사용"})
        self.assertNotIn("인코딩 오류", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
