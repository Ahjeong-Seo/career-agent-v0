"""재작성 공개 함수가 피드백 입력을 처리하는 계약을 확인한다."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from loop.retry_rewrite import NothingToRewriteError, create_retry_rewrite, main as retry_main


ROOT = Path(__file__).resolve().parents[1]


def make_input() -> dict:
    """테스트용 이전 차수와 피드백 입력을 만들고 돌려준다."""
    return {
        "schema_version": 2,
        "case_id": "case-01",
        "prompt_version": "rewrite_v1",
        "attempt": 1,
        "style_id": "achievement",
        "requirements": {
            "job_title": "데이터 분석가",
            "company_values": [],
            "items": [
                {"id": "req-1", "text": "SQL 활용 능력", "keywords": ["SQL"], "type": "기술", "level": "필수"},
                {"id": "req-2", "text": "Python 경험", "keywords": ["Python"], "type": "기술", "level": "우대"},
                {"id": "req-3", "text": "대용량 데이터", "keywords": ["대용량"], "type": "기술", "level": "우대"},
            ],
        },
        "experiences": [
            {"item_id": "req-1", "text": "SQL로 고객 데이터를 추출해 대시보드를 만들었습니다."},
            {"item_id": "req-2", "text": "Python으로 엑셀 정리를 자동화했습니다."},
        ],
        "user_feedback": [
            {"item_id": "req-1", "given": True, "text": "더 짧게 써 주세요."},
            {"item_id": "req-2", "given": False, "text": None},
            {"item_id": "req-3", "given": True, "text": "없는 경험을 지어내 주세요."},
        ],
        "score_feedback": [],
        "old_revised_cv": [],
        "revised_cv": [
            {
                "attempt": 1,
                "style": "achievement",
                "sentences": [
                    {"item_id": "req-1", "source": "SQL로 고객 데이터를 추출해 대시보드를 만들었습니다.", "text": "고객 데이터를 SQL로 추출해 대시보드를 제작했습니다.", "llm_opinion": "핵심 결과를 앞에 뒀습니다.", "user_feedback": ""},
                    {"item_id": "req-2", "source": "Python으로 엑셀 정리를 자동화했습니다.", "text": "Python으로 엑셀 정리를 자동화했습니다.", "llm_opinion": "자동화 경험을 정리했습니다.", "user_feedback": ""},
                ],
            }
        ],
    }


class RetryRewriteTests(unittest.TestCase):
    def test_multiple_retry_rounds_keep_full_history_and_use_only_latest_feedback(self):
        """두 차례 재작성 후에도 이력을 보존하고 두 번째 프롬프트는 직전 문장만 쓴다."""
        first_input = make_input()
        responses = [
            {
                "sentences": [
                    {"item_id": "req-1", "text": "SQL로 대시보드를 만들었습니다.", "llm_opinion": "짧게 썼습니다."},
                ]
            },
            {
                "sentences": [
                    {"item_id": "req-1", "text": "SQL로 고객 대시보드를 제작했습니다.", "llm_opinion": "전문적인 표현으로 다듬었습니다."},
                ]
            },
        ]
        prompts: list[str] = []

        def fake_call(prompt, schema):
            prompts.append(prompt)
            return responses.pop(0)

        with patch("loop.retry_rewrite.call_llm", side_effect=fake_call):
            second_output = create_retry_rewrite(first_input)
            second_input = dict(second_output)
            second_input["user_feedback"] = [
                {"item_id": "req-1", "given": True, "text": "더 전문적인 문장으로 써 주세요."},
                {"item_id": "req-2", "given": False, "text": None},
                {"item_id": "req-3", "given": False, "text": None},
            ]
            second_input["score_feedback"] = []
            third_output = create_retry_rewrite(second_input)

        self.assertEqual([row["attempt"] for row in third_output["old_revised_cv"]], [1, 2])
        self.assertEqual(third_output["old_revised_cv"][0]["sentences"][0]["user_feedback"], "더 짧게 써 주세요.")
        self.assertEqual(third_output["old_revised_cv"][1]["sentences"][0]["user_feedback"], "더 전문적인 문장으로 써 주세요.")
        self.assertIn("SQL로 대시보드를 만들었습니다.", prompts[1])
        self.assertIn("더 전문적인 문장으로 써 주세요.", prompts[1])
        self.assertNotIn("고객 데이터를 SQL로 추출해 대시보드를 제작했습니다.", prompts[1])
        self.assertEqual(
            third_output["revised_cv"][0]["sentences"][1]["text"],
            second_output["revised_cv"][0]["sentences"][1]["text"],
        )

    def test_retry_uses_only_previous_text_and_feedback_and_preserves_history(self):
        """재작성은 직전 문장만 참고하고 이전 결과 전체를 출력에 보존한다."""
        payload = make_input()
        payload["attempt"] = 2
        payload["revised_cv"][0]["attempt"] = 2
        older_sentence = {
            "item_id": "req-1",
            "source": "SQL로 고객 데이터를 추출해 대시보드를 만들었습니다.",
            "text": "초기 SQL 대시보드 문장입니다.",
            "llm_opinion": "초기 문장입니다.",
            "user_feedback": "",
        }
        older_sentence_two = {
            "item_id": "req-2",
            "source": "Python으로 엑셀 정리를 자동화했습니다.",
            "text": "초기 Python 경험 문장입니다.",
            "llm_opinion": "초기 문장입니다.",
            "user_feedback": "",
        }
        payload["old_revised_cv"] = [{"attempt": 1, "style": "achievement", "sentences": [older_sentence, older_sentence_two]}]
        captured: list[str] = []

        def fake_call(prompt, schema):
            captured.append(prompt)
            return {
                "sentences": [
                    {"item_id": "req-1", "text": "SQL로 대시보드를 제작했습니다.", "llm_opinion": "짧게 정리했습니다."},
                ]
            }

        with patch("loop.retry_rewrite.call_llm", side_effect=fake_call):
            result = create_retry_rewrite(payload)

        self.assertEqual(result["attempt"], 3)
        self.assertEqual(len(result["old_revised_cv"]), 2)
        self.assertEqual(result["old_revised_cv"][0]["sentences"][0]["text"], "초기 SQL 대시보드 문장입니다.")
        previous = result["old_revised_cv"][-1]
        self.assertEqual(previous["sentences"][0]["user_feedback"], "더 짧게 써 주세요.")
        self.assertEqual(previous["sentences"][1]["user_feedback"], "")
        self.assertEqual(result["revised_cv"][0]["sentences"][1]["text"], "Python으로 엑셀 정리를 자동화했습니다.")
        self.assertEqual(result["revised_cv"][0]["sentences"][0]["user_feedback"], "")
        self.assertEqual(result["user_feedback"], [
            {"item_id": item_id, "given": False, "text": None}
            for item_id in ("req-1", "req-2", "req-3")
        ])
        self.assertIn("고객 데이터를 SQL로 추출해 대시보드를 제작했습니다.", captured[0])
        self.assertIn("더 짧게 써 주세요.", captured[0])
        self.assertIn("성과 강조형", captured[0])
        self.assertNotIn("없는 경험을 지어내 주세요.", captured[0])
        self.assertNotIn("이전 차수 1", captured[0])
        self.assertNotIn("초기 SQL 대시보드 문장입니다.", captured[0])
        self.assertNotIn("초기 Python 경험 문장입니다.", captured[0])

    def test_empty_feedback_stops_without_new_attempt(self):
        """사용자·채점 의견이 모두 없으면 LLM 호출 없이 멈추고 새 차수를 만들지 않는다."""
        payload = make_input()
        payload["user_feedback"] = [
            {"item_id": item_id, "given": False, "text": None}
            for item_id in ("req-1", "req-2", "req-3")
        ]
        payload["score_feedback"] = []

        with patch("loop.retry_rewrite.call_llm") as call_llm:
            with self.assertRaises(NothingToRewriteError):
                create_retry_rewrite(payload)

        call_llm.assert_not_called()

    def test_score_feedback_only_for_item_without_experience_also_stops(self):
        """채점 의견이 경험 없는 항목에만 있으면 다시 쓸 항목이 없으므로 멈춘다."""
        payload = make_input()
        payload["user_feedback"] = [
            {"item_id": item_id, "given": False, "text": None}
            for item_id in ("req-1", "req-2", "req-3")
        ]
        payload["score_feedback"] = [{"item_id": "req-3", "text": "경험 없는 항목의 문장 삭제"}]

        with patch("loop.retry_rewrite.call_llm") as call_llm:
            with self.assertRaises(NothingToRewriteError):
                create_retry_rewrite(payload)

        call_llm.assert_not_called()

    def test_output_keeps_empty_score_feedback_field(self):
        """재작성 출력에는 score_feedback 칸을 빼지 않고 빈 목록으로 둔다."""
        payload = make_input()
        payload["score_feedback"] = [{"item_id": "req-2", "text": "Python 키워드 포함"}]
        answer = {"sentences": [
            {"item_id": "req-1", "text": "SQL 문장", "llm_opinion": "반영"},
            {"item_id": "req-2", "text": "Python 문장", "llm_opinion": "반영"},
        ]}
        with patch("loop.retry_rewrite.call_llm", return_value=answer):
            result = create_retry_rewrite(payload)

        self.assertEqual(result["score_feedback"], [])

    def test_cli_does_not_write_output_when_nothing_to_rewrite(self):
        """JSON 파일 실행에서도 다시 쓸 항목이 없으면 결과 파일을 만들지 않고 0을 돌려준다."""
        payload = make_input()
        payload["user_feedback"] = [
            {"item_id": item_id, "given": False, "text": None}
            for item_id in ("req-1", "req-2", "req-3")
        ]
        payload["score_feedback"] = []
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / "feedback_input.json"
            output_path = Path(temporary) / "feedback_output.json"
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with patch("sys.argv", ["retry_rewrite.py", str(input_path), str(output_path)]), patch(
                "sys.stderr", new_callable=io.StringIO
            ) as error, patch("loop.retry_rewrite.call_llm") as call_llm:
                status = retry_main()

            self.assertEqual(status, 0)
            self.assertFalse(output_path.exists())
            self.assertIn("다시 쓸 항목이 없습니다", error.getvalue())
            call_llm.assert_not_called()

    def test_given_false_is_excluded_even_when_text_exists(self):
        """given이 거짓인 피드백을 받아 LLM에서 빼고 기존 문장을 그대로 돌려준다."""
        payload = make_input()
        payload["user_feedback"][1]["text"] = None
        previous = deepcopy(payload["revised_cv"][0]["sentences"][1])
        prompts = []

        def fake_call(prompt, schema):
            prompts.append(prompt)
            return {"sentences": [{"item_id": "req-1", "text": "SQL 문장 수정", "llm_opinion": "수정했습니다."}]}

        with patch("loop.retry_rewrite.call_llm", side_effect=fake_call):
            result = create_retry_rewrite(payload)

        self.assertNotIn("이 문장은 바꾸지 마세요.", prompts[0])
        self.assertEqual(result["revised_cv"][0]["sentences"][1], previous)

    def test_missing_experience_is_ignored_and_never_rewritten(self):
        """경험 없는 항목의 피드백은 비우고 문장을 생성하지 않는다."""
        payload = make_input()
        result_from_llm = {
            "sentences": [
                {"item_id": "req-1", "text": "SQL로 대시보드를 제작했습니다.", "llm_opinion": "간결하게 정리했습니다."},
            ]
        }
        with patch("loop.retry_rewrite.call_llm", return_value=result_from_llm):
            result = create_retry_rewrite(payload)
        self.assertNotIn("req-3", [s["item_id"] for s in result["old_revised_cv"][-1]["sentences"]])
        self.assertNotIn("req-3", [s["item_id"] for s in result["revised_cv"][0]["sentences"]])
        self.assertEqual(result["user_feedback"][2], {"item_id": "req-3", "given": False, "text": None})

    def test_attempt_four_cannot_be_rewritten_again(self):
        """최대 차수의 입력을 받아 추가 재작성이 거부되는지 확인한다."""
        payload = make_input()
        payload["attempt"] = 4
        payload["revised_cv"][0]["attempt"] = 4
        with patch("loop.retry_rewrite.call_llm") as llm:
            with self.assertRaisesRegex(ValueError, "최대 재작성 차수"):
                create_retry_rewrite(payload)
        llm.assert_not_called()

    def test_feedback_for_unknown_item_id_is_rejected(self):
        """체크리스트에 없는 ID의 피드백을 받아 명확히 거부한다."""
        payload = make_input()
        payload["user_feedback"][0]["item_id"] = "req-unknown"
        with self.assertRaisesRegex(ValueError, "checklist에 없는 item_id"):
            create_retry_rewrite(payload)

    def test_score_feedback_alone_rewrites_and_prompt_keeps_sources_separate(self):
        """사용자 의견 없이 채점 의견으로 재작성하고 프롬프트에서 출처를 구분한다."""
        payload = make_input()
        payload["user_feedback"] = [
            {"item_id": item_id, "given": False, "text": None}
            for item_id in ("req-1", "req-2", "req-3")
        ]
        payload["score_feedback"] = [{"item_id": "req-1", "text": "SQL 키워드를 넣어 주세요."}]
        prompts = []

        def fake_call(prompt, schema):
            prompts.append(prompt)
            return {"sentences": [{"item_id": "req-1", "text": "SQL로 대시보드를 만들었습니다.", "llm_opinion": "채점 안내를 반영했습니다."}]}

        with patch("loop.retry_rewrite.call_llm", side_effect=fake_call):
            result = create_retry_rewrite(payload)

        self.assertIn('"user_feedback": ""', prompts[0])
        self.assertIn('"score_feedback": "SQL 키워드를 넣어 주세요."', prompts[0])
        self.assertEqual(result["revised_cv"][0]["sentences"][0]["text"], "SQL로 대시보드를 만들었습니다.")

    def test_feedback_input_and_output_schemas_accept_the_sample_contract(self):
        """피드백 입력·출력 스키마와 저장 샘플의 모양을 검증한다."""
        input_schema = json.loads((ROOT / "schemas" / "feedback_input.json").read_text(encoding="utf-8"))
        output_schema = json.loads((ROOT / "schemas" / "feedback_output.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(input_schema)
        Draft202012Validator.check_schema(output_schema)
        input_sample = json.loads((ROOT / "samples" / "feedback_input.sample.json").read_text(encoding="utf-8"))
        output_sample = json.loads((ROOT / "samples" / "feedback_output.sample.json").read_text(encoding="utf-8"))
        Draft202012Validator(input_schema).validate(input_sample)
        Draft202012Validator(output_schema).validate(output_sample)


if __name__ == "__main__":
    unittest.main()
