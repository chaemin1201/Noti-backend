# app/inputdata/dedupe.py
"""문제 중복 등록 방지.

같은 사용자(maker_id)가 같은 유형·제목·설명의 문제를 이미 등록했다면 같은 문제로 본다.
판정에는 content_hash(Problem.temporary_field_str_2)를 쓴다.
"""
import hashlib
import json
import re
import unicodedata

# 한글/영문 유형 이름을 하나로 통일 (코딩 == coding)
CANONICAL_TYPES = {
    "coding": "코딩", "코딩": "코딩",
    "debugging": "디버깅", "디버깅": "디버깅",
    "multiple_choice": "객관식", "객관식": "객관식",
    "short_answer": "단답형", "단답형": "단답형",
    "subjective": "주관식", "주관식": "주관식",
}


def _normalize(text, casefold: bool = False) -> str:
    s = unicodedata.normalize("NFC", "" if text is None else str(text))
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"\s+", " ", s).strip()   # 공백·줄바꿈 차이는 무시
    return s.casefold() if casefold else s


def _content_of(description):
    if not isinstance(description, str) or not description.lstrip().startswith("{"): return description
    try: d = json.loads(description)
    except ValueError: return description
    return str(d.get("content") or "") if isinstance(d, dict) and "content" in d else description


def compute_content_hash(problem_type, title, description) -> str:
    """유형 + 제목 + 설명으로 만든 sha256 (64자, 컬럼 길이 100 이내).

    - 제목은 대소문자를 구분하지 않는다. (PY11-0001 == py11-0001)
    - 설명은 대소문자를 구분한다. (코드가 들어 있을 수 있으므로)
    - 정답, 테스트 케이스, 태그가 달라도 같은 문제로 본다. 정답을 고치려면 재등록이 아니라 수정을 쓴다.
    """
    ptype = CANONICAL_TYPES.get(str(problem_type), str(problem_type))
    description = _content_of(description)        # {"intent","subtitle","content"} 로 저장된 설명은 본문만 비교 (부제목·문제의도가 달라도 같은 문제)
    key = "\x1f".join([ptype, _normalize(title, casefold=True), _normalize(description)])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class TitleTakenError(Exception):
    """등록 제목(코드)이 이미 다른 문제에 쓰이고 있다 (동시 등록에서 같은 번호를 받은 경우). 새 번호를 받아 다시 시도하면 된다."""


class DuplicateProblemError(Exception):
    """이미 같은 문제가 있을 때 crud 가 발생시킨다. 오류가 아니라 '건너뜀'으로 처리한다."""

    def __init__(self, existing_problem_id: int, content_hash: str):
        super().__init__(f"이미 등록된 문제입니다. (problem_id={existing_problem_id})")
        self.existing_problem_id = existing_problem_id
        self.content_hash = content_hash
