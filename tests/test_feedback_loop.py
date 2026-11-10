"""첫 첨삭을 피드백 입력으로 바꾸고 재작성 회차를 제한하는지 검사한다."""

import io
import json
import tempfile
import unittest
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
            {"item_id": entry["item_id"], "text": entry["text"], "llm_opinion": "원문을 유지했습니다."}
            for entry in self.experience["experiences"]
        ]}

    def test_case_feedback_files_use_style_and_reset_feedback(self):
        """실제 피드백 입력 파일을 받아 예시 출력과 같은 필드 모양을 돌려준다."""
        case_dir = ROOT / "data" / "cases" / "case-01"
        data = json.loads((case_dir / "feedback_input.json").read_text(encoding="utf-8"))
        expected = json.loads((case_dir / "feedback_output.json").read_text(encoding="utf-8"))
        with patch("sys.stdin", io.StringIO("")), patch(
            "loop.feedback_loop.call_llm", return_value=self.answer
        ) as llm:
            result = rewrite_with_feedback(data)

        self.assertEqual(set(result), set(expected))
        self.assertEqual(result["attempt"], expected["attempt"])
        self.assertEqual(result["style_id"], expected["style_id"])
        self.assertEqual(result["revised_cv"][0]["style"], "achievement")
        self.assertEqual(result["old_revised_cv"][0], data["revised_cv"][0])
        self.assertEqual(result["user_feedback"], expected["user_feedback"])
        self.assertEqual(
            set(result["revised_cv"][0]["sentences"][0]),
            set(expected["revised_cv"][0]["sentences"][0]),
        )
        self.assertIn(data["user_feedback"][0]["req-1"], llm.call_args.args[0])

    def test_interactive_feedback_preserves_shape_and_source(self):
        """입력한 피드백을 전달하고 원문을 보존한 다음 회차 결과를 돌려준다."""
        with patch("sys.stdin", io.StringIO("SQL 성과 강조\nPython 기간 유지\n")), patch(
            "sys.stderr", new_callable=io.StringIO
        ), patch("loop.feedback_loop.call_llm", return_value=self.answer) as llm:
            result = rewrite_with_feedback(self.data)

        self.assertEqual(set(result), set(self.data))
        self.assertEqual(result["attempt"], 2)
        self.assertEqual(result["revised_cv"][0]["attempt"], 2)
        self.assertEqual(result["user_feedback"][-1], {
            "req-1": "", "req-2": "", "req-3": ""
        })
        self.assertEqual(result["old_revised_cv"][0], self.data["revised_cv"][0])
        self.assertEqual(result["revised_cv"][0]["sentences"][0]["source"], self.experience["experiences"][0]["text"])
        self.assertIn("SQL 성과 강조", llm.call_args.args[0])
        self.assertIn("Python 기간 유지", llm.call_args.args[0])
        llm.assert_called_once()

    def test_stops_before_fifth_attempt(self):
        """세 번 피드백을 반영한 뒤 추가 요청은 LLM 호출 전에 거절한다."""
        with patch("loop.feedback_loop.call_llm", return_value=self.answer) as llm:
            result = self.data
            for number in range(2, 5):
                result = rewrite_with_feedback(result, {"req-1": f"의견 {number}"})
                self.assertEqual(result["attempt"], number)
            with self.assertRaisesRegex(ValueError, "최대 attempt 4"):
                rewrite_with_feedback(result, {"req-1": "추가 의견"})
        self.assertEqual(llm.call_count, 3)

    def test_blank_llm_sentence_skips_only_that_item(self):
        """빈 답변의 req만 제외하고 다른 req의 첨삭 결과를 돌려준다."""
        answer = {"sentences": [dict(row) for row in self.answer["sentences"]]}
        answer["sentences"][1]["text"] = ""
        answer["sentences"][1]["llm_opinion"] = ""
        with patch("loop.feedback_loop.call_llm", return_value=answer):
            result = rewrite_with_feedback(self.data, {"req-1": "첫 의견"})
        self.assertEqual(
            [row["item_id"] for row in result["revised_cv"][0]["sentences"]], ["req-1"]
        )

    def test_case_id_reads_and_writes_case_feedback_files(self):
        """case_id를 받아 해당 폴더의 피드백 입력을 읽고 출력 파일을 돌려준다."""
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "data" / "cases" / "case01"
            case_dir.mkdir(parents=True)
            data = {**self.data, "case_id": "case01", "user_feedback": [{"req-1": "SQL 경험 강조"}]}
            (case_dir / "feedback_input.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with patch("sys.argv", ["feedback_loop.py", "case01"]), patch(
                "sys.stdin", io.StringIO("")
            ), patch("sys.stderr", new_callable=io.StringIO), patch(
                "loop.yjh_initial_rewrite.ROOT", Path(temporary)
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
            ) as error, patch("loop.yjh_initial_rewrite.ROOT", Path(temporary)), patch(
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
            data = {**self.data, "user_feedback": [{"req-1": "SQL 경험 강조"}]}
            input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with patch("sys.argv", ["feedback_loop.py", str(input_path)]), patch(
                "sys.stdout", new_callable=io.StringIO
            ) as output, patch("loop.feedback_loop.call_llm", return_value=self.answer):
                status = main()
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output.getvalue())["attempt"], 2)
            self.assertFalse((Path(temporary) / "feedback_output.json").exists())


if __name__ == "__main__":
    unittest.main()
