"""화면과 루프(첨삭) 함수를 잇는 함수 모음.

화면(app/style_select.py)은 루프 함수를 직접 부르지 않고 이 파일의 함수만 부른다.
루프 쪽 함수 이름이나 돌려주는 모양이 바뀌면 이 파일만 고치면 된다. (app/parsing_bridge.py와 같은 방식)

흐름
1. 3단계에서 확정한 경험이 data/cases/<case_id>/experience.json에 저장된다.
2. generate_first_rewrite: 같은 폴더의 checklist.json·experience.json으로 첫 생성 3종을 만들어 rewrite.json에 저장한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loop import initial_rewrite


def generate_first_rewrite(case_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """case_id를 받아 첫 생성 3종을 만들고 (rewrite 객체, 오류 목록)을 돌려준다.

    루프의 run_case가 케이스 폴더의 checklist.json과 experience.json을 읽어
    스타일 3종을 순서대로 만들고 같은 폴더의 rewrite.json에 저장한다.
    Codex가 없거나 호출이 두 번 실패하는 등 오류가 나면 rewrite는 None이다.
    """
    try:
        path = initial_rewrite.run_case(case_id)
        rewrite = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError) as error:
        return None, [str(error)]
    return rewrite, []
