"""loop_main의 case_id 입력이 팀 공통 rewrite.json을 저장하는지 검사한다."""

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from loop.loop_main import main
from loop.yjh_initial_rewrite import ROOT


class LoopMainCaseIdTests(unittest.TestCase):
    def test_case_id_shows_initial_result_and_saves_feedback_rewrite(self):
        """case_id를 받아 첫 결과를 보이고 피드백을 반영한 rewrite 파일을 돌려준다."""
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "data" / "cases" / "case-01"
            case_dir.mkdir(parents=True)
            shutil.copyfile(ROOT / "samples" / "checklist.sample.json", case_dir / "checklist.json")
            shutil.copyfile(ROOT / "samples" / "experience.sample.json", case_dir / "experience.json")

            def fake_call_llm(prompt, schema):
                """입력 프롬프트와 스키마를 받아 각 경험의 가짜 첨삭 문장을 돌려준다."""
                entries = json.loads(prompt.split("입력 데이터: ", 1)[1])
                is_feedback = isinstance(entries, dict)
                if is_feedback:
                    entries = [
                        {"item_id": entry["item_id"], "source": entry["text"]}
                        for entry in entries["experiences"]
                    ]
                return {"sentences": [
                    {
                        "item_id": entry["item_id"],
                        "text": "" if is_feedback and entry["item_id"] == "req-2" else entry["source"],
                        "llm_opinion": "원문 유지",
                    }
                    for entry in entries
                ]}

            with patch("sys.argv", ["loop_main.py", "case-01"]), patch(
                "sys.stdin", io.StringIO("1\n\n첫 피드백\n둘째 피드백\nn\n")
            ), patch("sys.stdout", new_callable=io.StringIO) as output, patch(
                "sys.stderr", new_callable=io.StringIO
            ) as progress, patch("loop.yjh_initial_rewrite.ROOT", Path(temporary)), patch(
                "loop.yjh_initial_rewrite.call_llm", side_effect=fake_call_llm
            ) as initial_llm, patch(
                "loop.rewrite_cv.call_llm", side_effect=fake_call_llm
            ) as feedback_llm:
                status = main()

            rewrite_path = case_dir / "rewrite.json"
            self.assertEqual(status, 0)
            self.assertTrue(rewrite_path.is_file())
            result = json.loads(rewrite_path.read_text(encoding="utf-8"))
            self.assertEqual(result["case_id"], "case-01")
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["attempt"], 2)
            self.assertEqual(result["style"], "achievement")
            self.assertEqual(len(result["revised_cv"]), 1)
            self.assertEqual(
                [row["item_id"] for row in result["revised_cv"][0]["sentences"]], ["req-1"]
            )
            self.assertEqual(result["revised_cv"][0]["sentences"][0]["user_feedback"], "첫 피드백")
            self.assertIn("성과 강조형", progress.getvalue())
            self.assertIn("관련 경험이 정말 없나요?", progress.getvalue())
            self.assertIn("피드백을 더 반영할까요?", progress.getvalue())
            self.assertEqual(initial_llm.call_count, 3)
            feedback_llm.assert_called_once()
            self.assertIn(str(rewrite_path), output.getvalue())

    def test_case_id_persists_added_experience_and_three_feedback_rounds(self):
        """새 경험과 세 번의 피드백을 받아 원문과 마지막 rewrite를 저장한다."""
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "data" / "cases" / "case-01"
            case_dir.mkdir(parents=True)
            shutil.copyfile(ROOT / "samples" / "checklist.sample.json", case_dir / "checklist.json")
            shutil.copyfile(ROOT / "samples" / "experience.sample.json", case_dir / "experience.json")
            new_source = "대용량 데이터를 처리하고 검증 문서를 작성했습니다."
            answers = (
                f"1\n{new_source}\n첫 의견\n둘째 의견\ny\n"
                "추가 의견 1\n추가 의견 2\n추가 의견 3\ny\n"
                "최종 의견 1\n최종 의견 2\n최종 의견 3\n"
            )

            def fake_call_llm(prompt, schema):
                """프롬프트와 스키마를 받아 원문에 근거한 가짜 문장 목록을 돌려준다."""
                entries = json.loads(prompt.split("입력 데이터: ", 1)[1])
                if isinstance(entries, dict):
                    entries = [
                        {"item_id": entry["item_id"], "source": entry["text"]}
                        for entry in entries["experiences"]
                    ]
                return {"sentences": [
                    {"item_id": entry["item_id"], "text": entry["source"], "llm_opinion": "원문 유지"}
                    for entry in entries
                ]}

            with patch("sys.argv", ["loop_main.py", "case-01"]), patch(
                "sys.stdin", io.StringIO(answers)
            ), patch("sys.stdout", new_callable=io.StringIO), patch(
                "sys.stderr", new_callable=io.StringIO
            ) as progress, patch("loop.yjh_initial_rewrite.ROOT", Path(temporary)), patch(
                "loop.yjh_initial_rewrite.call_llm", side_effect=fake_call_llm
            ), patch("loop.rewrite_cv.call_llm", side_effect=fake_call_llm) as feedback_llm:
                status = main()

            result = json.loads((case_dir / "rewrite.json").read_text(encoding="utf-8"))
            experience = json.loads((case_dir / "experience.json").read_text(encoding="utf-8"))
            self.assertEqual(status, 0)
            self.assertEqual(result["attempt"], 4)
            self.assertEqual(result["revised_cv"][0]["sentences"][-1]["source"], new_source)
            self.assertEqual(experience["experiences"][-1], {"item_id": "req-3", "text": new_source})
            self.assertEqual(result["revised_cv"][0]["sentences"][-1]["user_feedback"], "최종 의견 3")
            self.assertEqual(feedback_llm.call_count, 3)
            self.assertEqual(progress.getvalue().count("관련 경험이 정말 없나요?"), 1)
            self.assertIn("피드백 3/3 반영 결과", progress.getvalue())


if __name__ == "__main__":
    unittest.main()
