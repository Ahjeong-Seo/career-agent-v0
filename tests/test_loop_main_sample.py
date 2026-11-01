"""loop_main의 샘플 실행이 터미널 입력 없이 첫 재작성을 끝내는지 검사한다."""

import io
import json
import unittest
from unittest.mock import patch

from loop.loop_main import load_sample_input, main
from loop.revise_cv import revise_cv
from loop.rewrite_cv import getUserFeedback, rewrite_cv


class LoopMainSampleTests(unittest.TestCase):
    def test_missing_middle_experience_gets_blank_sentence(self):
        """1·3번 경험만 있으면 첫 결과의 2번 문장을 빈칸으로 둔다."""
        sample = load_sample_input()
        sample["answers"]["req-2"] = ""
        sample["answers"]["req-3"] = "대용량 데이터를 처리했습니다."
        sentences = [
            {"item_id": item_id, "text": text, "llm_opinion": "원문을 유지했습니다."}
            for item_id, text in sample["answers"].items()
            if text
        ]
        with patch("loop.revise_cv.call_llm", return_value={"sentences": sentences}), patch(
            "sys.stderr", new_callable=io.StringIO
        ):
            result = revise_cv(sample, auto_select=True)

        rows = result["revised_cv"][0]["sentences"]
        self.assertEqual([row["item_id"] for row in rows], ["req-1", "req-2", "req-3"])
        self.assertEqual(rows[1]["source"], "")
        self.assertEqual(rows[1]["text"], "")
        self.assertEqual(rows[2]["source"], sample["answers"]["req-3"])

    def test_no_experiences_keep_all_items_blank(self):
        """경험이 하나도 없어도 모든 항목을 빈 문장으로 돌려준다."""
        sample = load_sample_input()
        sample["answers"] = {item_id: "" for item_id in sample["answers"]}
        with patch("loop.revise_cv.call_llm") as first_llm, patch("loop.rewrite_cv.call_llm") as retry_llm:
            first = revise_cv(sample, auto_select=True)
            next_result = rewrite_cv(first, feedback={})

        first_llm.assert_not_called()
        retry_llm.assert_not_called()
        for result in (first, next_result):
            rows = result["revised_cv"][0]["sentences"]
            self.assertEqual([row["item_id"] for row in rows], ["req-1", "req-2", "req-3"])
            self.assertTrue(all(row["text"] == "" and row["source"] == "" for row in rows))

    def test_feedback_skips_blank_experience(self):
        """가운데 항목에 경험이 없으면 그 항목의 피드백을 묻지 않는다."""
        rows = [
            {"item_id": "req-1", "source": "첫 경험", "text": "첫 문장"},
            {"item_id": "req-2", "source": "", "text": ""},
            {"item_id": "req-3", "source": "셋째 경험", "text": "셋째 문장"},
        ]
        with patch("sys.stdin", io.StringIO("첫 피드백\n셋째 피드백\n")), patch(
            "sys.stderr", new_callable=io.StringIO
        ) as progress:
            feedback = getUserFeedback(rows)

        self.assertEqual(feedback, {"req-1": "첫 피드백", "req-3": "셋째 피드백"})
        self.assertNotIn("[req-2]", progress.getvalue())

    def test_first_result_uses_rewrite_result_shape(self):
        """첫 생성의 입력 근거·결과·횟수가 재작성과 같은 칸에 담기는지 검사한다."""
        sample = load_sample_input()
        sentences = [
            {"item_id": item_id, "text": text, "llm_opinion": "원문을 유지했습니다."}
            for item_id, text in sample["answers"].items()
            if text
        ]
        with patch("loop.revise_cv.call_llm", return_value={"sentences": sentences}) as llm_calls, patch(
            "sys.stderr", new_callable=io.StringIO
        ) as progress:
            result = revise_cv(sample, auto_select=True)

        self.assertEqual(
            set(result),
            {"case_id", "prompt_version", "attempt", "style_id", "requirements",
             "experiences", "user_feedback", "old_revised_cv", "revised_cv"},
        )
        self.assertEqual(result["attempt"], 0)
        self.assertEqual(result["prompt_version"], "rewrite_v1")
        self.assertEqual(result["style_id"], "achievement")
        self.assertEqual(result["case_id"], sample["case"]["case_id"])
        self.assertEqual(result["requirements"]["items"], sample["case"]["items"])
        self.assertEqual(
            result["experiences"],
            [{"item_id": item_id, "text": text} for item_id, text in sample["answers"].items() if text],
        )
        self.assertEqual(result["user_feedback"], [])
        self.assertEqual(result["old_revised_cv"], [])
        self.assertEqual(result["revised_cv"][0]["attempt"], 0)
        self.assertEqual(result["revised_cv"][0]["style_id"], result["style_id"])
        self.assertEqual(result["revised_cv"][0]["sentences"][0]["source"], sample["answers"]["req-1"])
        self.assertEqual(result["revised_cv"][0]["sentences"][0]["llm_opinion"], "원문을 유지했습니다.")
        self.assertEqual(result["revised_cv"][0]["sentences"][0]["user_feedback"], "")
        self.assertIn("성과 강조형", progress.getvalue())
        self.assertEqual(llm_calls.call_count, 3)
        prompt, schema = llm_calls.call_args_list[0].args
        self.assertIn("작성 스타일: 성과 강조형", prompt)
        self.assertIn('"keywords"', prompt)
        self.assertIn("llm_opinion", schema["properties"]["sentences"]["items"]["required"])

    def test_attempt_increases_once_per_feedback_round(self):
        """첫 생성 0회에서 피드백 세 번을 반영하면 1·2·3회가 되는지 검사한다."""
        sample = load_sample_input()
        sentences = [
            {"item_id": item_id, "text": text, "llm_opinion": "원문을 유지했습니다."}
            for item_id, text in sample["answers"].items()
            if text
        ]
        with patch("loop.revise_cv.call_llm", return_value={"sentences": sentences}), patch(
            "loop.rewrite_cv.call_llm", return_value={"sentences": sentences}
        ), patch("sys.stderr", new_callable=io.StringIO):
            result = revise_cv(sample, auto_select=True)
            attempts = [result["attempt"]]
            for number in range(1, 4):
                result = rewrite_cv(result, feedback={"req-1": f"피드백 {number}", "req-2": ""})
                attempts.append(result["attempt"])
                self.assertEqual(result["revised_cv"][0]["attempt"], number)
            with self.assertRaisesRegex(ValueError, "최대 3번"):
                rewrite_cv(result, feedback={"req-1": "추가 피드백"})

        self.assertEqual(attempts, [0, 1, 2, 3])
        self.assertEqual([row["attempt"] for row in result["old_revised_cv"]], [0, 1, 2])
        self.assertEqual(len(result["user_feedback"]), 3)

    def test_sample_runs_first_rewrite_without_terminal_input(self):
        """샘플 입력을 받아 자동 스타일·빈 피드백으로 attempt 1 결과를 돌려준다."""
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
        self.assertEqual(result["attempt"], 1)
        self.assertEqual(result["requirements"]["items"], sample["case"]["items"])
        self.assertEqual(result["experiences"][0]["text"], sample["answers"]["req-1"])
        self.assertEqual(result["old_revised_cv"][0]["attempt"], 0)
        self.assertEqual(result["old_revised_cv"][0]["sentences"][0]["source"], sample["answers"]["req-1"])
        self.assertEqual(result["user_feedback"], [{"req-1": "", "req-2": ""}])
        self.assertEqual(first_calls.call_count, 3)
        rewrite_calls.assert_called_once()

    def test_rewrite_error_outputs_json_with_first_result(self):
        """재작성 항목 ID가 틀리면 오류 원인과 첫 생성 결과를 JSON으로 돌려준다."""
        sample = load_sample_input()
        first_sentences = [
            {"item_id": item_id, "text": text, "llm_opinion": "원문을 유지했습니다."}
            for item_id, text in sample["answers"].items()
            if text
        ]
        wrong_sentences = [{"item_id": "req-999", "text": "잘못된 항목", "llm_opinion": "오류 확인용"}]
        with patch("sys.argv", ["loop_main.py", "--sample"]), patch(
            "sys.stdin", io.StringIO("")
        ), patch("sys.stdout", new_callable=io.StringIO) as output, patch(
            "sys.stderr", new_callable=io.StringIO
        ), patch("loop.revise_cv.call_llm", return_value={"sentences": first_sentences}), patch(
            "loop.rewrite_cv.call_llm", return_value={"sentences": wrong_sentences}
        ):
            status = main()

        payload = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["stage"], "rewrite_cv")
        self.assertEqual(payload["error"]["type"], "ValueError")
        self.assertIn("req-999", payload["error"]["message"])
        self.assertIn("req-1", payload["error"]["message"])
        self.assertIn("req-2", payload["error"]["message"])
        self.assertEqual(payload["result"]["attempt"], 0)
        self.assertEqual(payload["result"]["revised_cv"][0]["sentences"][0]["item_id"], "req-1")

    def test_sample_ignores_generated_text_for_no_experience(self):
        """재작성 답변에 경험 없는 3번 문장이 있어도 결과에는 빈칸으로 둔다."""
        sample = load_sample_input()
        first_sentences = [
            {"item_id": item_id, "text": text, "llm_opinion": "원문을 유지했습니다."}
            for item_id, text in sample["answers"].items()
            if text
        ]
        rewrite_sentences = first_sentences + [
            {"item_id": "req-3", "text": "만들지 않은 경험", "llm_opinion": "잘못 생성됨"}
        ]
        with patch("sys.argv", ["loop_main.py", "--sample"]), patch(
            "sys.stdin", io.StringIO("")
        ), patch("sys.stdout", new_callable=io.StringIO) as output, patch(
            "sys.stderr", new_callable=io.StringIO
        ), patch("loop.revise_cv.call_llm", return_value={"sentences": first_sentences}), patch(
            "loop.rewrite_cv.call_llm", return_value={"sentences": rewrite_sentences}
        ) as retry_llm:
            status = main()

        result = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        first_rows = result["old_revised_cv"][0]["sentences"]
        next_rows = result["revised_cv"][0]["sentences"]
        self.assertEqual([row["item_id"] for row in next_rows], ["req-1", "req-2", "req-3"])
        self.assertEqual(first_rows[2]["text"], "")
        self.assertEqual(next_rows[2]["source"], "")
        self.assertEqual(next_rows[2]["text"], "")
        self.assertEqual(next_rows[2]["llm_opinion"], "")
        self.assertIn("`experiences`에 없는 item_id", retry_llm.call_args.args[0])

    def test_input_error_outputs_json_with_null_result(self):
        """입력을 읽지 못한 경우에도 실패 단계와 원인을 JSON으로 돌려준다."""
        with patch("sys.argv", ["loop_main.py", "--sample"]), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as output, patch("loop.loop_main.load_sample_input", side_effect=ValueError("샘플 입력 오류")):
            status = main()

        payload = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(payload["stage"], "input")
        self.assertEqual(payload["error"]["message"], "샘플 입력 오류")
        self.assertIsNone(payload["result"])


if __name__ == "__main__":
    unittest.main()
