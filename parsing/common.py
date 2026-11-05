"""파서에서 함께 쓰는 파일 읽기, 케이스 폴더, JSON 저장 기능이다."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from loop.data_contracts import validate_document


ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "data" / "cases"
CASE_ID_PATTERN = re.compile(r"^case-\d+$")


def read_input_text(path: str | Path) -> str:
    """TXT 파일 경로를 받아 UTF-8 문자열을 읽어 돌려준다."""
    input_path = Path(path)
    try:
        return input_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{input_path}: UTF-8 TXT 파일이 아닙니다.") from error


def get_case_directory(case_id: str) -> Path:
    """케이스 ID를 받아 유효성을 확인하고 케이스 폴더 경로를 돌려준다."""
    if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError("case_id는 'case-숫자' 형식이어야 합니다.")
    return CASES_DIR / case_id


def create_case_directory() -> str:
    """다음 케이스 ID를 정해 폴더를 만들고 ID를 돌려준다."""
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    existing_numbers = [
        int(match.group(1))
        for child in CASES_DIR.iterdir()
        if child.is_dir() and (match := re.fullmatch(r"case-(\d+)", child.name))
    ]
    next_number = max(existing_numbers, default=0) + 1

    while True:
        case_id = f"case-{next_number:02d}"
        case_dir = CASES_DIR / case_id
        try:
            case_dir.mkdir()
            return case_id
        except FileExistsError:
            next_number += 1


def write_json_document(
    output_path: Path,
    data: dict[str, Any],
    schema_path: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """저장 경로·JSON 데이터·스키마를 받아 검증 후 저장 경로를 돌려준다."""
    validate_document(output_path, data, schema_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with output_path.open(mode, encoding="utf-8") as output_file:
        json.dump(data, output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    return output_path


def write_text_file(output_path: Path, content: str) -> Path:
    """TXT 저장 경로와 문자열을 받아 UTF-8로 저장하고 경로를 돌려준다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="") as output_file:
        output_file.write(content)
    return output_path
