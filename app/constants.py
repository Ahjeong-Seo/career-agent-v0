from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASE = ROOT / "schemas" / "loop"/ "jd_requirements.json"
PROMPT_VERSION = ROOT / "prompts" / "loop" / "write_v1"
STYLES = ("성과 강조형", "담백한 사실형", "직무 연결형")
SENTENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["item_id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}