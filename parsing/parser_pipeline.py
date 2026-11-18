"""공고와 이력서 TXT를 읽어 케이스별 체크리스트와 경험 JSON을 생성한다."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loop.data_contracts import load_checklist, validate_document
from parsing.checklist_parser import SCHEMA_PATH as CHECKLIST_SCHEMA_PATH, parse_checklist
from parsing.common import (
    create_case_directory,
    get_case_directory,
    read_input_text,
    sanitize_json_strings,
    write_json_document,
    write_text_file,
)
from parsing.experience_parser import generate_experience_draft


def run_pipeline_from_text(
    job_text: str, resume_text: str, case_id: str | None = None
) -> tuple[str, dict[str, Path], list[str]]:
    """공고·이력서 문자열을 받아 원문 TXT와 JSON을 저장하고 ID·경로·오류를 돌려준다."""
    input_error = _validate_pipeline_texts(job_text, resume_text)
    if input_error:
        return case_id or "", {}, [input_error]

    try:
        case_id, case_dir, case_directory_created = _prepare_case_directory(case_id)
    except (OSError, ValueError) as error:
        reported_case_id = case_id if isinstance(case_id, str) else ""
        return reported_case_id, {}, [
            f"케이스 폴더 준비 실패: {type(error).__name__}: {error}"
        ]

    output_paths, errors = _save_source_texts(case_dir, job_text, resume_text)
    if errors:
        if case_directory_created:
            cleanup_error = _remove_empty_case_directory(case_dir)
            if cleanup_error:
                errors.append(cleanup_error)
        return case_id, output_paths, errors

    errors = _run_parsers(job_text, case_id, output_paths)
    return case_id, output_paths, errors


def run_pipeline_from_confirmed_checklist(
    job_text: str,
    resume_text: str,
    confirmed_checklist: dict,
    case_id: str | None = None,
) -> tuple[str, dict[str, Path], list[str]]:
    """확인된 checklist·JD·resume를 받아 case 파일과 경험 초안을 생성한다."""
    input_error = _validate_pipeline_texts(job_text, resume_text)
    if input_error:
        return "", {}, [input_error]
    if not isinstance(confirmed_checklist, dict):
        return "", {}, ["확인된 checklist는 JSON 객체여야 합니다."]
    items = confirmed_checklist.get("items")
    if not isinstance(items, list) or not items:
        return "", {}, ["확인된 checklist.items는 비어 있지 않은 목록이어야 합니다."]
    expected_ids = [f"req-{index}" for index in range(1, len(items) + 1)]
    actual_ids = [item.get("id") if isinstance(item, dict) else None for item in items]
    if actual_ids != expected_ids:
        return "", {}, ["checklist 항목 ID는 req-1부터 순서대로 있어야 합니다."]

    case_directory_created = False
    try:
        if case_id is None:
            case_id = create_case_directory()
            case_directory_created = True
        case_dir = get_case_directory(case_id)
        if not case_dir.is_dir():
            return case_id, {}, [f"케이스 폴더가 없습니다: {case_dir}"]
    except (OSError, ValueError) as error:
        return case_id or "", {}, [
            f"케이스 폴더 준비 실패: {type(error).__name__}: {error}"
        ]

    checklist = deepcopy(confirmed_checklist)
    checklist["case_id"] = case_id
    checklist = sanitize_json_strings(checklist)
    checklist_path = case_dir / "checklist.json"
    try:
        validate_document(checklist_path, checklist, CHECKLIST_SCHEMA_PATH)
        output_paths = _save_confirmed_case_files(
            case_dir, job_text, resume_text, checklist
        )
    except Exception as error:
        cleanup_error = (
            _remove_created_case_directory(case_dir)
            if case_directory_created
            else None
        )
        message = f"case 원본 파일 저장 실패: {type(error).__name__}: {error}"
        return case_id, {}, [message, *([cleanup_error] if cleanup_error else [])]

    try:
        _, output_paths["experience_draft"] = generate_experience_draft(case_id)
    except Exception as error:
        return case_id, output_paths, [
            f"experience_parser.py: {type(error).__name__}: {error}"
        ]
    return case_id, output_paths, []


def _save_confirmed_case_files(
    case_dir: Path, job_text: str, resume_text: str, checklist: dict
) -> dict[str, Path]:
    """case 폴더와 확정 입력을 받아 세 파일을 저장·확인하고 파일 경로를 반환한다."""
    output_paths: dict[str, Path] = {}
    created_paths: list[Path] = []
    try:
        for name, file_name, content in (
            ("job_txt", "jd.txt", job_text),
            ("resume_txt", "resume.txt", resume_text),
        ):
            path = case_dir / file_name
            if path.exists():
                existing_content = read_input_text(path)
                if existing_content != content:
                    raise ValueError(f"기존 {file_name} 내용과 전달된 내용이 다릅니다.")
            else:
                write_text_file(path, content)
                created_paths.append(path)
            output_paths[name] = path

        checklist_path = case_dir / "checklist.json"
        if checklist_path.exists():
            existing_checklist = load_checklist(checklist_path)
            existing_ids = [item["id"] for item in existing_checklist["items"]]
            confirmed_ids = [item["id"] for item in checklist["items"]]
            if existing_ids != confirmed_ids:
                raise ValueError("확인된 checklist의 item ID가 저장된 checklist와 다릅니다.")
            if existing_checklist != checklist:
                write_json_document(
                    checklist_path,
                    checklist,
                    CHECKLIST_SCHEMA_PATH,
                    overwrite=True,
                    sanitize_strings=True,
                )
        else:
            write_json_document(
                checklist_path,
                checklist,
                CHECKLIST_SCHEMA_PATH,
                sanitize_strings=True,
            )
            created_paths.append(checklist_path)
        output_paths["checklist"] = checklist_path
    except Exception:
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise
    return output_paths


def _remove_created_case_directory(case_dir: Path) -> str | None:
    """이번 실행에서 만든 빈 case 폴더를 지우고 실패 시 오류를 반환한다."""
    try:
        case_dir.rmdir()
    except OSError as error:
        return f"빈 case 폴더 정리 실패: {type(error).__name__}: {error}"
    return None


def _validate_pipeline_texts(job_text: str, resume_text: str) -> str | None:
    """공고·이력서 문자열을 받아 비어 있거나 문자열이 아닌 입력의 오류를 반환한다."""
    if not isinstance(job_text, str) or not job_text.strip():
        return "공고 TXT 내용이 비어 있거나 문자열이 아닙니다."
    if not isinstance(resume_text, str) or not resume_text.strip():
        return "이력서 TXT 내용이 비어 있거나 문자열이 아닙니다."
    return None


def _prepare_case_directory(case_id: str | None) -> tuple[str, Path, bool]:
    """선택적 케이스 ID를 받아 폴더 경로와 이번 호출의 신규 생성 여부를 반환한다."""
    if case_id is None:
        case_id = create_case_directory()
        return case_id, get_case_directory(case_id), True

    case_dir = get_case_directory(case_id)
    return case_id, case_dir, not case_dir.exists()


def _save_source_texts(
    case_dir: Path, job_text: str, resume_text: str
) -> tuple[dict[str, Path], list[str]]:
    """케이스 폴더와 두 원문을 받아 TXT 경로와 저장 오류를 반환한다."""
    source_files = (
        ("job_txt", case_dir / "jd.txt", job_text),
        ("resume_txt", case_dir / "resume.txt", resume_text),
    )
    output_paths: dict[str, Path] = {}
    errors: list[str] = []
    created_paths: list[Path] = []

    for name, path, content in source_files:
        existed_before = path.exists()
        try:
            output_paths[name] = write_text_file(path, content)
            created_paths.append(path)
        except FileExistsError as error:
            errors.append(f"원문 TXT 저장 실패 ({path}): {type(error).__name__}: {error}")
            break
        except OSError as error:
            if not existed_before and path.exists():
                created_paths.append(path)
            errors.append(f"원문 TXT 저장 실패 ({path}): {type(error).__name__}: {error}")
            break

    if errors:
        for path in created_paths:
            try:
                path.unlink(missing_ok=True)
                source_name = "job_txt" if path.name == "jd.txt" else "resume_txt"
                output_paths.pop(source_name, None)
            except OSError as error:
                errors.append(
                    f"부분 저장 파일 정리 실패 ({path}): "
                    f"{type(error).__name__}: {error}"
                )

    return output_paths, errors


def _remove_empty_case_directory(case_dir: Path) -> str | None:
    """이번 실행에서 만든 빈 케이스 폴더를 지우고 실패하면 오류 문장을 반환한다."""
    try:
        case_dir.rmdir()
    except OSError as error:
        return f"빈 케이스 폴더 정리 실패 ({case_dir}): {type(error).__name__}: {error}"
    return None


def _run_parsers(
    job_text: str,
    case_id: str,
    output_paths: dict[str, Path],
) -> list[str]:
    """공고 문자열과 케이스 ID로 checklist 파서를 실행하고 오류 목록을 반환한다."""
    errors = []

    try:
        _, output_paths["checklist"] = parse_checklist(job_text, case_id)
    except Exception as error:
        errors.append(f"checklist_parser.py: {type(error).__name__}: {error}")

    return errors


def run_pipeline_from_files(
    job_txt: str | Path, resume_txt: str | Path
) -> tuple[str, dict[str, Path], list[str]]:
    """공고·이력서 TXT 경로를 읽어 문자열 파이프라인에 전달하고 결과를 반환한다."""
    job_text = read_input_text(job_txt)
    resume_text = read_input_text(resume_txt)
    return run_pipeline_from_text(job_text, resume_text)


def main(argv: Sequence[str] | None = None) -> None:
    """공고 TXT와 이력서 TXT 경로를 받아 파이프라인을 실행하고 결과를 출력한다."""
    parser = argparse.ArgumentParser(
        description="공고 TXT와 이력서 TXT에서 케이스별 JSON 결과를 생성합니다."
    )
    parser.add_argument("job_txt", help="회사정보와 채용공고가 포함된 TXT 파일 경로")
    parser.add_argument("resume_txt", help="이력서 TXT 파일 경로")
    args = parser.parse_args(argv)

    try:
        case_id, output_paths, errors = run_pipeline_from_files(
            args.job_txt, args.resume_txt
        )
    except (OSError, ValueError) as error:
        parser.exit(status=1, message=f"오류: {error}\n")

    print(f"case_id: {case_id}")
    for name, output_path in output_paths.items():
        print(f"{name}: {output_path}")
    for error in errors:
        print(f"오류: {error}", file=sys.stderr)
    if errors:
        parser.exit(status=1)


if __name__ == "__main__":
    main()
