"""파일을 읽고 팀에서 합의한 JSON Schema로 검사하는 공통 함수다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
CHECKLIST_SCHEMA_PATH = ROOT / "schemas" / "parsing" / "checklist.json"
EXPERIENCE_SCHEMA_PATH = ROOT / "schemas" / "parsing" / "experience.json"


def read_json(path: Path) -> dict[str, Any]:
    """JSON 파일 경로를 받아 객체로 읽고, 최상위 형식이 틀리면 오류를 낸다."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}: JSON 문법 오류 (줄 {error.lineno}, 칸 {error.colno})") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON 최상위 값은 객체여야 합니다.")
    return value


def validate_document(path: Path, data: dict[str, Any], schema_path: Path) -> None:
    """JSON 파일 경로·데이터·스키마를 받아 검사하고 성공 시 None을 돌려준다."""
    schema = read_json(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(data),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = []
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "(최상위)"
            details.append(f"{path}의 {location}: {error.message}")
        raise ValueError("\n".join(details))


def load_checklist(path: Path) -> dict[str, Any]:
    """체크리스트 파일을 받아 스키마와 ID 중복을 확인한 객체를 돌려준다."""
    checklist = read_json(path)
    validate_document(path, checklist, CHECKLIST_SCHEMA_PATH)

    # JSON Schema는 배열 안에서 ID가 중복되는지 확인할 수 없어 코드로 검사한다.
    item_ids = [item["id"] for item in checklist["items"]]
    seen: set[str] = set()
    for item_id in item_ids:
        if item_id in seen:
            raise ValueError(f"{path}의 items에 중복된 id가 있습니다: {item_id}")
        seen.add(item_id)
    return checklist
