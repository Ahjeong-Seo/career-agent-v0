"""터미널 입력의 잘못된 UTF-8 문자가 첨삭 실행을 중단하지 않는지 확인한다."""

import io
import unittest
from unittest.mock import patch

import run


class InputEncodingTest(unittest.TestCase):
    def test_bad_character_in_last_item_is_reentered(self):
        """마지막 항목의 잘못된 문자를 다시 입력받아 정상 원문을 돌려준다."""
        user_input = io.StringIO("\n\n\udce3\n실제 대용량 데이터 처리 경험\n1\n")
        messages = io.StringIO()
        answer = {"sentences": [{"item_id": "req-3", "text": "대용량 데이터 처리 경험"}]}

        with (
            patch("sys.stdin", user_input),
            patch("sys.stderr", messages),
            patch.object(
                run,
                "call_llm",
                side_effect=lambda prompt, schema: (prompt.encode("utf-8"), answer)[1],
            ),
        ):
            result = run.run(run.DEFAULT_CASE)

        self.assertEqual(result["sentences"][0]["source"], "실제 대용량 데이터 처리 경험")
        self.assertIn("인코딩", messages.getvalue())


if __name__ == "__main__":
    unittest.main()
