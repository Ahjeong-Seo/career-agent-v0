"""공개 score_case 경계에서 규칙 기반 채점 결과를 검증한다."""

import unittest
from copy import deepcopy

from scoring.score import score_case


def make_inputs():
    """검토 완료 checklist와 연결된 경험·첨삭 입력을 반환한다."""
    checklist = {
        "case_id": "case-01",
        "schema_version": 1,
        "reviewed": True,
        "items": [
            {
                "id": "req-1",
                "text": "SQL 활용 능력",
                "keywords": ["SQL"],
                "type": "기술",
                "level": "필수",
            }
        ],
    }
    experience = {
        "case_id": "case-01",
        "schema_version": 1,
        "experiences": [{"item_id": "req-1", "text": "SQL로 주간 리포트를 만들었습니다."}],
    }
    rewrite = {
        "case_id": "case-01",
        "style_id": "achievement",
        "attempt": 1,
            "attempt_id": "attempt-01",
        "sentences": [
            {
                "item_id": "req-1",
                "source": "SQL로 주간 리포트를 만들었습니다.",
                "text": "SQL로 주간 리포트를 만들었습니다.",
            }
        ],
    }
    return checklist, experience, rewrite


class ScoreCaseTests(unittest.TestCase):
    """score_case의 외부 입력과 반환 결과를 검증한다."""

    def test_keyword_match_returns_satisfied_item(self):
        """키워드가 문안에 있으면 충족 상태와 이유를 반환한다."""
        checklist, experience, rewrite = make_inputs()
        rewrite["sentences"][0]["text"] = "sql로 주간 리포트를 만들었습니다."

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["items"][0]["item_id"], "req-1")
        self.assertEqual(result["items"][0]["status"], "충족")
        self.assertEqual(result["items"][0]["reason"], "'SQL' 키워드가 결과 문안에 있습니다.")
        self.assertEqual(result["items"][0]["score"], {"earned": 10, "max": 10})
        self.assertEqual(result["issues"], [])
        self.assertFalse(result["needs_revision"])
        self.assertEqual(result["attempt_id"], "attempt-01")

    def test_missing_experience_row_returns_no_experience_status(self):
        """확정 payload에서 누락된 경험 행을 경험 없음으로 표시한다."""
        checklist, experience, rewrite = make_inputs()
        experience["experiences"] = []
        rewrite["sentences"] = []

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["items"][0]["item_id"], "req-1")
        self.assertEqual(result["items"][0]["status"], "경험 없음")
        self.assertEqual(result["items"][0]["reason"], "확정한 경험 입력에 이 항목이 없습니다.")
        self.assertEqual(result["items"][0]["score"], {"earned": 0, "max": 10})

    def test_experience_payload_requires_schema_version(self):
        """공식 experience payload에 schema_version이 없으면 채점을 막는다."""
        checklist, experience, rewrite = make_inputs()
        del experience["schema_version"]

        with self.assertRaisesRegex(ValueError, "experience.schema_version"):
            score_case(checklist, experience, rewrite)

    def test_missing_rewrite_sentence_is_unmet(self):
        """경험 응답은 있지만 첨삭 문장이 없으면 미충족으로 표시한다."""
        checklist, experience, rewrite = make_inputs()
        rewrite["sentences"] = []

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["items"][0]["status"], "미충족")
        self.assertEqual(result["items"][0]["reason"], "첨삭 문장이 없습니다.")

    def test_no_experience_with_rewrite_is_flagged_in_item_reason(self):
        """경험 없음을 선택한 항목에 문장이 있으면 삭제 이유를 안내한다."""
        checklist, experience, rewrite = make_inputs()
        experience["experiences"] = []

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["items"][0]["status"], "경험 없음")
        self.assertEqual(
            result["items"][0]["reason"],
            "경험 없음으로 선택했지만 결과 문장이 있습니다. 문장을 삭제해 주세요.",
        )
        self.assertTrue(result["needs_revision"])
        self.assertEqual(result["issues"][0]["code"], "TEXT_WITHOUT_EXPERIENCE")
        self.assertIn("경험 없는 항목의 문장을 삭제", result["feedback"])

    def test_unfounded_number_is_a_separate_issue(self):
        """원문에 없는 문안 숫자는 상태와 별도인 단일 issue로 반환한다."""
        checklist, experience, rewrite = make_inputs()
        experience["experiences"][0]["text"] = "SQL로 1,000건의 주문을 집계했습니다."
        rewrite["sentences"][0]["source"] = experience["experiences"][0]["text"]
        rewrite["sentences"][0]["text"] = "SQL로 1,000건을 집계하고 1,500건으로 개선했습니다."

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["items"][0]["status"], "충족")
        self.assertEqual(result["items"][0]["score"], {"earned": 10, "max": 10})
        self.assertEqual(result["issues"], [{
            "item_id": "req-1",
            "code": "UNGROUNDED_NUMBER",
            "value": "1,500",
            "reason": "경험 원문에 없는 숫자입니다.",
        }])
        self.assertTrue(result["needs_revision"])

    def test_missing_numeric_evidence_is_visible_but_not_deducted(self):
        """원문에 수치가 없으면 결과에 표시하되 상태 점수를 낮추지 않는다."""
        checklist, experience, rewrite = make_inputs()

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["items"][0]["score"], {"earned": 10, "max": 10})
        self.assertEqual(result["items"][0]["checks"][0]["result"], "fail")
        self.assertIn("점수에는 반영하지 않습니다", result["items"][0]["checks"][0]["reason"])

    def test_unmet_item_marks_result_for_revision(self):
        """미충족 항목은 합격 판정 없이 재검토 필요를 표시한다."""
        checklist, experience, rewrite = make_inputs()
        rewrite["sentences"][0]["text"] = "주간 리포트를 만들었습니다."

        result = score_case(checklist, experience, rewrite)

        self.assertTrue(result["needs_revision"])
        self.assertNotIn("passed", result)

    def test_registered_generic_phrase_becomes_issue_but_keyword_is_exempt(self):
        """등록된 정형 표현은 issue가 되고 checklist 키워드면 예외 처리한다."""
        checklist, experience, rewrite = make_inputs()
        rewrite["sentences"][0]["text"] = "SQL로 적극적으로 기여했습니다."

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["items"][0]["status"], "충족")
        self.assertEqual(result["issues"], [{
            "item_id": "req-1",
            "code": "GENERIC_PHRASE",
            "value": "적극적으로 기여",
            "reason": "등록된 정형 표현과 일치합니다.",
        }])

        checklist["items"][0]["keywords"].append("적극적으로 기여")
        exempt = score_case(checklist, experience, rewrite)
        self.assertFalse(any(issue["code"] == "GENERIC_PHRASE" for issue in exempt["issues"]))

    def test_grounded_and_korean_number_tokens_do_not_create_issues(self):
        """원문에 있는 숫자와 판정 대상이 아닌 한글 숫자는 경고하지 않는다."""
        checklist, experience, rewrite = make_inputs()
        experience["experiences"][0]["text"] = "SQL로 1,000건을 처리했습니다."
        rewrite["sentences"][0]["source"] = experience["experiences"][0]["text"]
        rewrite["sentences"][0]["text"] = "SQL로 1000건을 처리하고 두 배로 늘렸습니다."

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["issues"], [])

    def test_case_id_mismatch_stops_scoring_with_actionable_error(self):
        """서로 다른 케이스의 입력을 섞으면 어느 데이터가 어긋났는지 알린다."""
        checklist, experience, rewrite = make_inputs()
        rewrite["case_id"] = "case-02"

        with self.assertRaisesRegex(ValueError, "case_id"):
            score_case(checklist, experience, rewrite)

    def test_rewrite_source_must_copy_original_experience(self):
        """rewrite의 source가 경험 원문과 다르면 불일치 필드를 알린다."""
        checklist, experience, rewrite = make_inputs()
        rewrite["sentences"][0]["source"] = "수정된 원문"

        with self.assertRaisesRegex(ValueError, r"rewrite\.sentences\[req-1\]\.source"):
            score_case(checklist, experience, rewrite)

    def test_duplicate_item_ids_are_rejected(self):
        """경험 응답의 중복 item_id를 찾아 어느 입력 목록이 잘못됐는지 알린다."""
        checklist, experience, rewrite = make_inputs()
        experience["experiences"].append(dict(experience["experiences"][0]))

        with self.assertRaisesRegex(ValueError, "experience.experiences.*중복.*req-1"):
            score_case(checklist, experience, rewrite)

    def test_empty_checklist_and_unknown_style_are_rejected(self):
        """채점 항목이 없거나 허용되지 않은 style이면 이유를 표시한다."""
        checklist, experience, rewrite = make_inputs()
        checklist["items"] = []
        with self.assertRaisesRegex(ValueError, "checklist.items.*한 개 이상"):
            score_case(checklist, experience, rewrite)

        checklist, experience, rewrite = make_inputs()
        rewrite["style_id"] = "unknown"
        with self.assertRaisesRegex(ValueError, "style_id"):
            score_case(checklist, experience, rewrite)

    def test_career_year_is_unverified_and_not_an_unfounded_number_issue(self):
        """경력 연수는 비교하지 않고 판정 이유에 미확인 상태를 표시한다."""
        checklist, experience, rewrite = make_inputs()
        checklist["items"][0]["type"] = "경력"
        checklist["items"][0]["text"] = "Python 3년 이상"
        checklist["items"][0]["keywords"] = ["Python"]
        experience["experiences"][0]["text"] = "Python으로 업무를 자동화했습니다."
        rewrite["sentences"][0]["source"] = experience["experiences"][0]["text"]
        rewrite["sentences"][0]["text"] = "Python을 3년 이상 사용했습니다."

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["items"][0]["status"], "충족")
        self.assertEqual(
            result["items"][0]["reason"],
            "'Python' 키워드가 결과 문안에 있습니다. 연수 미확인.",
        )
        self.assertEqual(result["issues"], [])

    def test_missing_career_rewrite_still_explains_year_is_unverified(self):
        """경력 항목에 문안이 없어도 연수는 검증하지 않는다고 표시한다."""
        checklist, experience, rewrite = make_inputs()
        checklist["items"][0]["type"] = "경력"
        rewrite["sentences"] = []

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["items"][0]["reason"], "첨삭 문장이 없습니다. 연수 미확인.")

    def test_style_and_attempt_are_preserved_for_style_level_score(self):
        """한국어 스타일과 4회를 넘긴 재시도 번호를 정책대로 반환한다."""
        checklist, experience, rewrite = make_inputs()
        rewrite["style"] = "간결형"
        del rewrite["style_id"]
        rewrite["attempt"] = 5

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["style_id"], "concise")
        self.assertEqual(result["attempt"], 5)

    def test_three_style_scores_can_share_one_attempt(self):
        """동일 입력의 세 스타일 score가 같은 attempt 식별자를 보존한다."""
        checklist, experience, rewrite = make_inputs()
        scores = []
        for style_id in ("achievement", "keyword", "concise"):
            style_rewrite = deepcopy(rewrite)
            style_rewrite["style_id"] = style_id
            scores.append(score_case(checklist, experience, style_rewrite))

        self.assertEqual([score["style_id"] for score in scores], ["achievement", "keyword", "concise"])
        self.assertEqual({score["attempt_id"] for score in scores}, {"attempt-01"})

    def test_required_and_preferred_item_points_follow_status(self):
        """필수·우대 최대 점수와 충족 상태에 따라 항목 점수를 계산한다."""
        checklist, experience, rewrite = make_inputs()
        checklist["items"].append({
            "id": "req-2",
            "text": "Python 활용",
            "keywords": ["Python"],
            "type": "기술",
            "level": "우대",
        })
        experience["experiences"].append({"item_id": "req-2", "text": "Python을 사용했습니다."})
        rewrite["sentences"].append({
            "item_id": "req-2",
            "source": "Python을 사용했습니다.",
            "text": "데이터를 처리했습니다.",
        })

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["items"][0]["score"], {"earned": 10, "max": 10})
        self.assertEqual(result["items"][1]["score"], {"earned": 0, "max": 5})

    def test_numeric_evidence_presence_is_reported_without_deduction(self):
        """수치 근거 유무를 check로 표시하되 item score에는 감점하지 않는다."""
        checklist, experience, rewrite = make_inputs()
        experience["experiences"][0]["text"] = "SQL로 1,000건을 집계했습니다."
        rewrite["sentences"][0]["source"] = experience["experiences"][0]["text"]
        rewrite["sentences"][0]["text"] = "SQL로 1,000건을 집계했습니다."

        result = score_case(checklist, experience, rewrite)

        self.assertEqual(result["items"][0]["score"], {"earned": 10, "max": 10})
        self.assertEqual(result["items"][0]["checks"], [{
            "code": "NUMERIC_EVIDENCE_PRESENT",
            "result": "pass",
            "reason": "경험 원문에 수치 근거가 있습니다.",
        }])

    def test_feedback_contains_item_reason_and_quality_issue(self):
        """재작성용 feedback에 항목 이유와 품질 경고를 함께 반환한다."""
        checklist, experience, rewrite = make_inputs()
        rewrite["sentences"][0]["text"] = "SQL로 30% 성과를 만들며 적극적으로 기여했습니다."

        result = score_case(checklist, experience, rewrite)

        self.assertIn("req-1", result["feedback"])
        self.assertIn("30%", result["feedback"])
        self.assertIn("적극적으로 기여", result["feedback"])


if __name__ == "__main__":
    unittest.main()
