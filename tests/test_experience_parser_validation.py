"""경험 초안 파서의 LLM 응답 검증을 확인한다."""

import unittest

from parsing.experience_parser import (
    _extract_experience_years,
    _validate_llm_result,
)


class ExperienceParserValidationTests(unittest.TestCase):
    """LLM이 반환한 경험 문구가 이력서 원문에 근거하는지 검사한다."""

    def test_extract_experience_years_results(self):
        """경험 원문의 명시 연수와 복수 연수 처리 결과를 확인한다."""
        cases = (
            ("1년 7개월", 1),
            ("3~5년", None),
            ("경력 3년, 프로젝트 5년", None),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(_extract_experience_years(text, 1), expected)

    def setUp(self):
        """검증에 사용할 체크리스트와 이력서 원문을 준비한다."""
        self.checklist = {
            "case_id": "case-01",
            "items": [
                {
                    "id": "req-1",
                    "text": "Python 사용 경험",
                    "keywords": ["Python"],
                    "type": "경험",
                    "level": "필수",
                    "years": None,
                }
            ],
        }
        self.resume_text = "Python으로 업무를 진행했습니다."

    def _result_with_text(self, text):
        """경험 문구를 받아 검증 함수에 전달할 LLM 응답 객체를 반환한다."""
        return {
            "case_id": "case-01",
            "experiences": [
                {
                    "item_id": "req-1",
                    "text": text,
                    "evidence": [text],
                    "match_basis": "keywords",
                }
            ],
        }

    def test_rejects_text_that_is_not_verbatim_from_resume(self):
        """resume.txt에 그대로 없는 문구면 초안 검증을 중단한다."""
        result = self._result_with_text("Python 업무를 진행했습니다.")

        with self.assertRaisesRegex(ValueError, "resume.txt 원문 그대로가 아닙니다"):
            _validate_llm_result(result, self.resume_text, self.checklist)

    def test_rejects_text_with_a_number_absent_from_resume(self):
        """원문에 없는 숫자가 포함된 문구면 초안 검증을 중단한다."""
        result = self._result_with_text("Python으로 5건 업무를 진행했습니다.")

        # 현재는 원문 일치 검사가 숫자 근거 검사보다 먼저 이 문구를 거절한다.
        with self.assertRaisesRegex(ValueError, "resume.txt 원문 그대로가 아닙니다"):
            _validate_llm_result(result, self.resume_text, self.checklist)


if __name__ == "__main__":
    unittest.main()
