from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from app.loop.data_input import data_input
from app.loop.revise_cv import revise_cv
from app.loop.rewrite_cv import rewrite_cv
from app.constants import DEFAULT_CASE


def main() -> int:
    """명령행 인수를 받아 프로그램을 실행하고 JSON을 출력한 뒤 종료 코드를 돌려준다."""
    parser = argparse.ArgumentParser(description="요구사항별 경험을 이력서 문장으로 다듬습니다.")
    parser.add_argument("case", nargs="?", type=Path, default=DEFAULT_CASE)
    arguments = parser.parse_args()
    try:
        inputResult = data_input(arguments.case)
        revisedResult = revise_cv(inputResult)
        rewriteResult = rewrite_cv(revisedResult)
        result = rewriteResult
    except (OSError, ValueError, EOFError, RuntimeError, json.JSONDecodeError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())