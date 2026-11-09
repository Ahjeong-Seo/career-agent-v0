"""선택한 스타일 재작성 계약을 Codex 호출 경계에서 검증한다."""

from unittest import TestCase
from unittest.mock import patch

from loop.initial_rewrite import create_retry_rewrite


class RetryRewriteTests(TestCase):
    def test_retry_sends_both_feedback_types_and_keeps_item_comments(self):
        """재작성은 선택 스타일과 두 피드백을 루프에 보내고 항목 의견을 결과에 보존한다."""
        checklist = {
            "case_id": "case-01",
            "items": [
                {"id": "req-1", "text": "SQL 활용", "keywords": ["SQL"], "type": "기술", "level": "필수"},
                {"id": "req-2", "text": "Python 자동화", "keywords": ["Python"], "type": "기술", "level": "필수"},
            ],
        }
        experience = {
            "case_id": "case-01",
            "experiences": [
                {"item_id": "req-1", "text": "SQL로 데이터를 조회했습니다."},
                {"item_id": "req-2", "text": "Python으로 정리 스크립트를 만들었습니다."},
            ],
        }
        llm_answer = {
            "sentences": [
                {"item_id": "req-1", "text": "SQL로 데이터를 조회했습니다.", "llm_opinion": "원문 사실을 유지했습니다."},
                {"item_id": "req-2", "text": "Python으로 정리 스크립트를 작성했습니다.", "llm_opinion": "요구 키워드를 반영했습니다."},
            ]
        }
        captured = {}

        def codex_boundary(prompt, schema):
            """Codex 호출을 흉내 내고 전달받은 프롬프트를 보관한다."""
            captured["prompt"] = prompt
            return llm_answer

        with patch("loop.initial_rewrite.call_llm", side_effect=codex_boundary):
            result = create_retry_rewrite(
                checklist,
                experience,
                "keyword",
                2,
                {"req-1": "성과를 과장하지 말아 주세요.", "req-2": "간결하게 써 주세요."},
                "req-2: Python 키워드를 포함하기",
            )

        self.assertEqual(result["style"], "keyword")
        self.assertEqual(result["attempt"], 2)
        self.assertEqual(result["prompt_version"], "rewrite_retry_v1")
        self.assertIn("req-2: Python 키워드를 포함하기", captured["prompt"])
        self.assertIn("성과를 과장하지 말아 주세요.", captured["prompt"])
        self.assertIn("간결하게 써 주세요.", captured["prompt"])
        self.assertEqual(
            [row["user_feedback"] for row in result["revised_cv"][0]["sentences"]],
            ["성과를 과장하지 말아 주세요.", "간결하게 써 주세요."],
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
