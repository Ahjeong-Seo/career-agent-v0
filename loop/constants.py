"""루프에서 함께 사용하는 계약 버전과 스타일 이름을 모아 둔다."""

PROMPT_VERSION = "rewrite_v1"
SCHEMA_VERSION = 1

# JSON에는 안정적인 영문 ID를 저장하고, 사람이 보는 문장에는 한글 이름을 쓴다.
STYLES = (
    ("achievement", "성과 강조형"),
    ("keyword", "키워드 맞춤형"),
    ("concise", "간결형"),
)
