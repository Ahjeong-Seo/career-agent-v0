"""loop_main의 샘플 실행이 터미널 입력 없이 첫 재작성을 끝내는지 검사한다."""

import io
import json
import unittest
from unittest.mock import patch

from loop.loop_main import load_sample_input, main
from loop.revise_cv import revise_cv


class LoopMainSampleTests(unittest.TestCase):
    def test_first_result_uses_rewrite_result_shape(self):
        """첫 생성의 입력 근거·결과·횟수가 재작성과 같은 칸에 담기는지 검사한다."""
        sample = load_sample_input()
        sentences = [
            {"item_id": item_id, "text": text}
            for item_id, text in sample["answers"].items()
            if text
        ]
        with patch("loop.revise_cv.call_llm", return_value={"sentences": sentences}), patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            result = revise_cv(sample, auto_select=True)

        self.assertEqual(
            set(result),
            {"case_id", "prompt_version", "attempt", "style_id", "requirements",
             "experiences", "user_feedback", "old_revised_cv", "revised_cv"},
        )
        self.assertEqual(result["attempt"], 1)
        self.assertEqual(result["case_id"], sample["case"]["case_id"])
        self.assertEqual(result["requirements"]["items"], sample["case"]["items"])
        self.assertEqual(
            result["experiences"],
            [{"item_id": item_id, "text": text} for item_id, text in sample["answers"].items() if text],
        )
        self.assertEqual(result["user_feedback"], [])
        self.assertEqual(result["old_revised_cv"], [])
        self.assertEqual(result["revised_cv"][0]["attempt"], 1)
        self.assertEqual(result["revised_cv"][0]["style_id"], result["style_id"])
        self.assertEqual(result["revised_cv"][0]["sentences"][0]["source"], sample["answers"]["req-1"])

    def test_sample_runs_first_rewrite_without_terminal_input(self):
        """샘플 입력을 받아 자동 스타일·빈 피드백으로 attempt 2 결과를 돌려준다."""
        sample = load_sample_input()
        sentences = [
            {"item_id": item_id, "text": text}
            for item_id, text in sample["answers"].items()
            if text
        ]

        def fake_call_llm(prompt, schema):
            """프롬프트와 스키마를 받아 샘플 경험에 근거한 가짜 LLM 결과를 돌려준다."""
            required = schema["properties"]["sentences"]["items"]["required"]
            if "llm_opinion" in required:
                return {
                    "sentences": [
                        {**sentence, "llm_opinion": "원문을 유지했습니다."}
                        for sentence in sentences
                    ]
                }
            return {"sentences": sentences}

        with patch("sys.argv", ["loop_main.py", "--sample"]), patch(
            "sys.stdin", io.StringIO("")
        ), patch("sys.stdout", new_callable=io.StringIO) as output, patch(
            "sys.stderr", new_callable=io.StringIO
        ), patch("loop.revise_cv.call_llm", side_effect=fake_call_llm) as first_calls, patch(
            "loop.rewrite_cv.call_llm", side_effect=fake_call_llm
        ) as rewrite_calls:
            status = main()

        result = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(result["case_id"], sample["case"]["case_id"])
        self.assertEqual(result["attempt"], 2)
        self.assertEqual(result["requirements"]["items"], sample["case"]["items"])
        self.assertEqual(result["experiences"][0]["text"], sample["answers"]["req-1"])
        self.assertEqual(result["old_revised_cv"][0]["attempt"], 1)
        self.assertEqual(result["old_revised_cv"][0]["sentences"][0]["source"], sample["answers"]["req-1"])
        self.assertEqual(result["user_feedback"], [{"req-1": "", "req-2": ""}])
        self.assertEqual(first_calls.call_count, 3)
        rewrite_calls.assert_called_once()


if __name__ == "__main__":
    unittest.main()
