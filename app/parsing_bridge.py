"""화면과 파싱 파이프라인을 잇는 함수 모음.

화면(app/main.py, app/experience_input.py)은 파싱 함수를 직접 부르지 않고 이 파일의 함수만 부른다.
파싱 쪽 함수 이름이나 돌려주는 모양이 바뀌면 이 파일만 고치면 된다.

흐름 (C안: 미리 채우고 사람이 확인)
1. start_case_from_inputs: 공고·이력서 → 케이스 폴더 + checklist.json (확인 전)
2. fetch_experience_draft: 확인한 체크리스트 → checklist.json 덮어쓰기 + experience_draft.json
3. prefill_from_draft: 초안 → 경험 입력란에 미리 채울 글·연수
4. save_confirmed_experience: 사람이 확인한 경험 → experience.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from parsing import common as parsing_common
from parsing import experience_parser, parser_pipeline


ROOT = Path(__file__).resolve().parents[1]
EXPERIENCE_SCHEMA_PATH = ROOT / "schemas" / "parsing" / "experience.json"


def _read_json(path: Any) -> dict[str, Any]:
    """파일 경로를 받아 JSON 객체를 읽어 돌려준다."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def start_case_from_inputs(
    job_text: str, resume_text: str
) -> tuple[str, dict[str, Any] | None, list[str]]:
    """공고 TXT 내용과 이력서 원문을 받아 새 케이스를 만들고 (case_id, 확인 전 체크리스트, 오류 목록)을 돌려준다.

    파싱팀 run_pipeline_from_text가 jd.txt, resume.txt, checklist.json을 케이스 폴더에 저장한다.
    오류가 있으면 체크리스트는 None이다.
    """
    case_id, output_paths, errors = parser_pipeline.run_pipeline_from_text(job_text, resume_text)
    if errors:
        return case_id, None, list(errors)
    checklist_path = output_paths.get("checklist")
    if not checklist_path:
        return case_id, None, ["파싱 결과에 checklist.json 경로가 없습니다."]
    try:
        checklist = _read_json(checklist_path)
    except (OSError, ValueError) as error:
        return case_id, None, [f"checklist.json을 읽지 못했습니다: {error}"]
    # 화면에서 사람이 확인하기 전이므로 reviewed는 항상 false로 둔다.
    checklist["reviewed"] = False
    return case_id, checklist, []


def fetch_experience_draft(
    job_text: str, resume_text: str, confirmed_checklist: dict[str, Any], case_id: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """처음 분석 때와 같은 공고·이력서, 확인한 체크리스트, case_id를 받아 (경험 초안, 오류 목록)을 돌려준다.

    파싱팀 run_pipeline_from_confirmed_checklist가 확인한 체크리스트로 checklist.json을 덮어쓰고
    experience_draft.json을 만든다. 초안이 이미 있으면 다시 만들지 않고 그대로 쓴다.
    """
    _, output_paths, errors = parser_pipeline.run_pipeline_from_confirmed_checklist(
        job_text, resume_text, confirmed_checklist, case_id
    )
    if errors:
        return None, list(errors)
    draft_path = output_paths.get("experience_draft")
    if not draft_path:
        return None, ["파싱 결과에 experience_draft.json 경로가 없습니다."]
    try:
        return _read_json(draft_path), []
    except (OSError, ValueError) as error:
        return None, [f"experience_draft.json을 읽지 못했습니다: {error}"]


def regenerate_experience_draft(case_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """case_id를 받아 경험 초안을 새로 만들고 (경험 초안, 오류 목록)을 돌려준다. AI를 다시 부른다."""
    try:
        draft, _ = experience_parser.generate_experience_draft(case_id, overwrite=True)
    except Exception as error:  # 파싱 쪽 오류를 화면에 그대로 보여 준다.
        return None, [f"{type(error).__name__}: {error}"]
    return draft, []


def prefill_from_draft(
    draft: dict[str, Any] | None, checklist: dict[str, Any]
) -> tuple[dict[str, str], dict[str, int | None]]:
    """경험 초안과 확인한 체크리스트를 받아 ({item_id: 미리 채울 글}, {item_id: 미리 채울 연수})를 돌려준다.

    - 글: 초안이 찾은 이력서 원문. 못 찾은 항목(null)은 넣지 않는다(빈 입력란).
    - 연수: 요구 연수가 있는 항목만, 1 이상일 때만 넣는다. 0은 "못 찾음"으로 보고 빈칸(미확인)으로 둔다.
    - 초안의 case_id가 체크리스트와 다르면 아무것도 채우지 않는다.
    """
    if not isinstance(draft, dict) or draft.get("case_id") != checklist.get("case_id"):
        return {}, {}
    required = {
        item.get("id"): item.get("years")
        for item in checklist.get("items", [])
        if isinstance(item, dict)
    }
    texts: dict[str, str] = {}
    years: dict[str, int | None] = {}
    for row in draft.get("experiences", []):
        if not isinstance(row, dict) or row.get("item_id") not in required:
            continue
        item_id = row["item_id"]
        text = row.get("text")
        if isinstance(text, str) and text.strip():
            texts[item_id] = text
        value = row.get("years")
        needed = required[item_id]
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value > 0
            and isinstance(needed, int)
            and not isinstance(needed, bool)
            and needed > 0
        ):
            years[item_id] = value
    return texts, years


def keywords_missing(text: str, keywords: list[Any]) -> bool:
    """경험 글과 체크리스트 키워드를 받아, 키워드가 하나도 글에 없으면 True를 돌려준다.

    채점과 같은 기준이다: 영어 대소문자를 무시하고 키워드가 글 안에 그대로 있는지 본다.
    """
    words = [word for word in keywords if isinstance(word, str) and word.strip()]
    if not words or not text.strip():
        return False
    lowered = text.casefold()
    return not any(word.casefold() in lowered for word in words)


def save_confirmed_experience(experience: dict[str, Any]) -> tuple[Path | None, list[str]]:
    """사람이 확인한 experience를 받아 data/cases/<case_id>/experience.json에 저장하고 (경로, 오류 목록)을 돌려준다.

    파싱팀 스키마(schemas/parsing/experience.json)로 검사한 뒤 저장한다. 다시 확인하면 덮어쓴다.
    """
    try:
        case_dir = parsing_common.get_case_directory(experience.get("case_id"))
    except ValueError as error:
        return None, [str(error)]
    if not case_dir.is_dir():
        return None, [f"케이스 폴더가 없습니다: {case_dir}"]
    output_path = case_dir / "experience.json"
    try:
        parsing_common.write_json_document(
            output_path, experience, EXPERIENCE_SCHEMA_PATH, overwrite=True
        )
    except (OSError, ValueError) as error:
        return None, [f"experience.json 저장 실패: {error}"]
    return output_path, []
