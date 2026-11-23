"""첫 첨삭을 피드백 입력으로 바꾸고 재작성 회차를 제한하는지 검사한다."""

import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from loop.feedback_loop import main, prepare_feedback_input, rewrite_with_feedback


ROOT = Path(__file__).resolve().parents[1]


class FeedbackLoopTests(unittest.TestCase):
    def setUp(self):
        """샘플 파일을 읽어 첫 첨삭과 입력 데이터를 테스트 객체에 저장한다."""
        self.initial = json.loads((ROOT / "samples" / "rewrite.sample.json").read_text(encoding="utf-8"))
        self.checklist = json.loads((ROOT / "samples" / "checklist.sample.json").read_text(encoding="utf-8"))
        self.experience = json.loads((ROOT / "samples" / "experience.sample.json").read_text(encoding="utf-8"))
        self.data = prepare_feedback_input(
            self.initial, self.checklist, self.experience, "achievement"
        )
        self.answer = {"sentences": [
            {"item_id": "req-1", "text": self.experience["experiences"][0]["text"], "llm_opinion": "원문을 유지했습니다."}
        ]}

    def test_retry_contract_rewrites_only_feedback_items_and_preserves_history_order(self):
        """기존 함수가 기준 재작성 계약을 사용하고 피드백 있는 항목만 다시 쓴다."""
        data = {**self.data, "user_feedback": [{"req-1": "SQL 활용 강조", "req-2": "", "req-3": ""}]}
        answer = {"sentences": [self.answer["sentences"][0]]}
        with patch("loop.retry_rewrite.call_llm", return_value=answer) as llm:
            result = rewrite_with_feedback(data)

        self.assertEqual(set(result), set(expected))
        self.assertEqual(result["attempt"], expected["attempt"])
        self.assertEqual(result["style_id"], expected["style_id"])
        self.assertEqual(result["revised_cv"][0]["style"], "achievement")
        previous = deepcopy(data["revised_cv"][0])
        feedback = {entry["item_id"]: entry["text"] for entry in data["user_feedback"] if entry["given"]}
        for sentence in previous["sentences"]:
            sentence["user_feedback"] = feedback.get(sentence["item_id"], "")
        self.assertEqual(result["old_revised_cv"][0], previous)
        self.assertEqual(result["user_feedback"], [
            {"item_id": item["id"], "given": False, "text": None}
            for item in data["requirements"]["items"]
        ])
        self.assertEqual(
            set(result["revised_cv"][0]["sentences"][0]),
            set(expected["revised_cv"][0]["sentences"][0]),
        )
        self.assertIn(data["user_feedback"][0]["text"], llm.call_args.args[0])
        self.assertEqual(result["revised_cv"][0]["sentences"][1], data["revised_cv"][0]["sentences"][1])

    def test_blank_feedback_skips_rewrite(self):
        """빈 피드백 입력을 받아 재작성 없이 None을 돌려주는지 확인한다."""
        with patch("loop.feedback_loop.call_llm") as llm:
            self.assertIsNone(rewrite_with_feedback(self.data))
            self.assertIsNone(rewrite_with_feedback(self.data, {"req-1": "  "}))

        self.assertEqual(self.data["attempt"], 1)
        llm.assert_not_called()

    def test_given_false_keeps_previous_sentence(self):
        """given이 거짓인 항목을 받아 LLM에서 빼고 이전 문장을 그대로 돌려준다."""
        data = deepcopy(self.data)
        data["user_feedback"][0].update(given=True, text="SQL 문장을 줄여 주세요.")
        data["user_feedback"][1]["text"] = "이 의견은 사용하지 마세요."
        previous = deepcopy(data["revised_cv"][0]["sentences"][1])

        with patch("loop.feedback_loop.call_llm", return_value=self.answer) as llm:
            result = rewrite_with_feedback(data)

        self.assertNotIn("이 의견은 사용하지 마세요.", llm.call_args.args[0])
        self.assertEqual(result["revised_cv"][0]["sentences"][1], previous)

    def test_blank_feedback_does_not_write_output_file(self):
        """빈 피드백 파일을 받아 재작성 결과 파일을 만들지 않고 종료 코드를 돌려준다."""
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / "feedback_input.json"
            output_path = Path(temporary) / "feedback_output.json"
            input_path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            with patch("sys.argv", ["feedback_loop.py", str(input_path), "--output", str(output_path)]), patch(
                "loop.feedback_loop.call_llm"
            ) as llm:
                status = main()

            self.assertEqual(status, 0)
            self.assertFalse(output_path.exists())
            llm.assert_not_called()

    def test_stops_before_fifth_attempt(self):
        """세 번 피드백을 반영한 뒤 추가 요청은 LLM 호출 전에 거절한다."""
        with patch("loop.retry_rewrite.call_llm", return_value=self.answer) as llm:
            result = self.data
            for number in range(2, 5):
                result = rewrite_with_feedback(result, {"req-1": f"의견 {number}", "req-2": f"의견 {number}"})
                self.assertEqual(result["attempt"], number)
            with self.assertRaisesRegex(ValueError, "최대 재작성 차수는 4차"):
                rewrite_with_feedback(result, {"req-1": "추가 의견", "req-2": "추가 의견"})
        self.assertEqual(llm.call_count, 3)

    def test_blank_llm_sentence_skips_only_that_item(self):
        """빈 답변의 req만 제외하고 다른 req의 첨삭 결과를 돌려준다."""
        answer = {"sentences": [dict(row) for row in self.answer["sentences"]]}
        answer["sentences"][0]["text"] = ""
        answer["sentences"][0]["llm_opinion"] = ""
        with patch("loop.feedback_loop.call_llm", return_value=answer):
            result = rewrite_with_feedback(self.data, {"req-1": "첫 의견"})
        self.assertEqual(
            [row["item_id"] for row in result["revised_cv"][0]["sentences"]], ["req-2"]
        )
        self.assertEqual(
            result["revised_cv"][0]["sentences"][1]["text"],
            self.data["revised_cv"][0]["sentences"][1]["text"],
        )

    def test_empty_feedback_preserves_sentence_and_advances_attempt(self):
        """터미널에서 피드백을 비워 두면 문장을 보존하고 attempt만 하나 올린다."""
        with patch("sys.stdin", io.StringIO("\n\n")), patch("sys.stderr", new_callable=io.StringIO), patch(
            "loop.retry_rewrite.call_llm"
        ) as llm:
            result = rewrite_with_feedback(self.data)
        llm.assert_not_called()
        self.assertEqual(result["attempt"], 2)
        self.assertEqual(
            [row["text"] for row in result["revised_cv"][0]["sentences"]],
            [row["text"] for row in self.data["revised_cv"][0]["sentences"]],
        )

    def test_legacy_newest_first_history_is_normalized_before_retry(self):
        """이전 feedback_loop가 저장한 최신순 이력을 차수순으로 바꿔 기준 함수에 넘긴다."""
        data = json.loads(json.dumps(self.data))
        first = json.loads(json.dumps(data["revised_cv"][0]))
        second = json.loads(json.dumps(first))
        second["attempt"] = 2
        data["attempt"] = 3
        data["revised_cv"][0]["attempt"] = 3
        data["old_revised_cv"] = [second, first]
        with patch("loop.retry_rewrite.call_llm", return_value=self.answer):
            result = rewrite_with_feedback(
                data, {"req-1": "SQL 보완", "req-2": "엑셀 보완"}
            )
        self.assertEqual([row["attempt"] for row in result["old_revised_cv"]], [1, 2, 3])

    def test_case_id_reads_and_writes_case_feedback_files(self):
        """case_id를 받아 해당 폴더의 피드백 입력을 읽고 출력 파일을 돌려준다."""
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "data" / "cases" / "case01"
            case_dir.mkdir(parents=True)
            data = {**self.data, "case_id": "case01", "user_feedback": [{"item_id": "req-1", "given": True, "text": "SQL 경험 강조"}]}
            (case_dir / "feedback_input.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with patch("sys.argv", ["feedback_loop.py", "case01"]), patch(
                "sys.stdin", io.StringIO("")
            ), patch("sys.stderr", new_callable=io.StringIO), patch(
                "loop.initial_rewrite.ROOT", Path(temporary)
            ), patch("loop.feedback_loop.call_llm", return_value=self.answer):
                status = main()

            output_path = case_dir / "feedback_output.json"
            self.assertEqual(status, 0)
            self.assertTrue(output_path.is_file())
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["case_id"], "case01")
            self.assertEqual(result["attempt"], 2)

    def test_case_id_must_match_feedback_input(self):
        """폴더 이름과 입력 case_id가 다르면 출력 파일을 만들지 않는다."""
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "data" / "cases" / "case01"
            case_dir.mkdir(parents=True)
            (case_dir / "feedback_input.json").write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            with patch("sys.argv", ["feedback_loop.py", "case01"]), patch(
                "sys.stderr", new_callable=io.StringIO
            ) as error, patch("loop.initial_rewrite.ROOT", Path(temporary)), patch(
                "loop.feedback_loop.call_llm"
            ) as llm:
                status = main()
            self.assertEqual(status, 1)
            self.assertIn("case_id", error.getvalue())
            self.assertFalse((case_dir / "feedback_output.json").exists())
            llm.assert_not_called()

    def test_json_path_still_writes_result_to_stdout(self):
        """JSON 파일 경로를 받아 별도 출력 경로가 없으면 결과 JSON을 표준 출력으로 돌려준다."""
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / "feedback_input.json"
            data = {**self.data, "user_feedback": [{"item_id": "req-1", "given": True, "text": "SQL 경험 강조"}]}
            input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with patch("sys.argv", ["feedback_loop.py", str(input_path)]), patch(
                "sys.stdout", new_callable=io.StringIO
            ) as output, patch("loop.retry_rewrite.call_llm", return_value=self.answer):
                status = main()
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())["attempt"], 2)
            self.assertFalse((Path(temporary) / "feedback_output.json").exists())


if __name__ == "__main__":
    unittest.main()
