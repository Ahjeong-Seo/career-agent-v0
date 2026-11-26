"""화면과 루프를 잇는 첫 생성 3종 함수가 결과와 오류를 제대로 돌려주는지 검사한다."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.loop_bridge import generate_first_rewrite


ROOT = Path(__file__).resolve().parents[1]


def fake_llm_answer(prompt: str, schema: dict) -> dict:
    """프롬프트를 받아, 들어온 경험 항목마다 문장 하나씩 가짜 LLM 답변을 돌려준다."""
    entries = json.loads(prompt.split("입력 데이터: ", 1)[1]) if "입력 데이터: " in prompt else []
    item_ids = [entry["item_id"] for entry in entries] or ["req-1", "req-2"]
    return {
        "sentences": [
            {"item_id": item_id, "text": f"{item_id} 첨삭 문장입니다.", "llm_opinion": "원문 사실을 유지했습니다."}
            for item_id in item_ids
        ]
    }


class GenerateFirstRewriteTests(unittest.TestCase):
    def test_returns_saved_rewrite_when_run_case_succeeds(self):
        """run_case가 저장한 rewrite.json을 읽어 (결과, 빈 오류 목록)으로 돌려준다."""
        with tempfile.TemporaryDirectory() as temporary:
            saved = Path(temporary) / "rewrite.json"
            saved.write_text(json.dumps({"case_id": "case-01", "revised_cv": []}), encoding="utf-8")
            with patch("app.loop_bridge.initial_rewrite.run_case", return_value=saved) as run_case:
                rewrite, errors = generate_first_rewrite("case-01")

        run_case.assert_called_once_with("case-01")
        self.assertEqual(rewrite, {"case_id": "case-01", "revised_cv": []})
        self.assertEqual(errors, [])

    def test_returns_error_instead_of_raising_when_codex_fails(self):
        """Codex가 없거나 호출이 실패하면 예외 대신 (None, 오류 문장)을 돌려준다."""
        with patch(
            "app.loop_bridge.initial_rewrite.run_case",
            side_effect=RuntimeError("Codex CLI를 찾을 수 없습니다. codex 명령을 설치해 주세요."),
        ):
            rewrite, errors = generate_first_rewrite("case-01")

        self.assertIsNone(rewrite)
        self.assertEqual(errors, ["Codex CLI를 찾을 수 없습니다. codex 명령을 설치해 주세요."])

    def test_missing_case_files_become_an_error_message(self):
        """케이스 폴더에 checklist.json·experience.json이 없으면 오류 문장으로 알려 준다."""
        with tempfile.TemporaryDirectory() as temporary:
            with patch("loop.initial_rewrite.ROOT", Path(temporary)):
                rewrite, errors = generate_first_rewrite("case-없음")

        self.assertIsNone(rewrite)
        self.assertEqual(len(errors), 1)

    def test_real_run_case_writes_three_styles_to_case_folder(self):
        """실제 run_case로 케이스 폴더 입력을 읽어 3종을 만들고 rewrite.json에 저장한다 (AI 호출만 가짜)."""
        checklist = json.loads((ROOT / "samples/checklist.sample.json").read_text(encoding="utf-8"))
        checklist["reviewed"] = True
        experience = json.loads((ROOT / "samples/experience.sample.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary) / "data" / "cases" / checklist["case_id"]
            case_dir.mkdir(parents=True)
            (case_dir / "checklist.json").write_text(json.dumps(checklist, ensure_ascii=False), encoding="utf-8")
            (case_dir / "experience.json").write_text(json.dumps(experience, ensure_ascii=False), encoding="utf-8")
            with patch("loop.initial_rewrite.ROOT", Path(temporary)), patch(
                "loop.initial_rewrite.call_llm", side_effect=fake_llm_answer
            ) as call_llm, patch("sys.stderr"):
                rewrite, errors = generate_first_rewrite(checklist["case_id"])

            self.assertEqual(errors, [])
            self.assertTrue((case_dir / "rewrite.json").exists())

        self.assertEqual(call_llm.call_count, 3)
        self.assertEqual(
            [row["style"] for row in rewrite["revised_cv"]], ["achievement", "keyword", "concise"]
        )
        sources = {row["item_id"]: row["text"] for row in experience["experiences"]}
        for row in rewrite["revised_cv"]:
            for sentence in row["sentences"]:
                self.assertEqual(sentence["source"], sources[sentence["item_id"]])


if __name__ == "__main__":
    unittest.main()
