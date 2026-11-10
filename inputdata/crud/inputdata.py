# app/inputdata/crud.py
from __future__ import annotations
from typing import Any, Dict
import json
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.inputdata.dedupe import compute_content_hash, DuplicateProblemError, TitleTakenError
from app.problem.models.problem import Problem
from app.problem.models.coding_problem import CodingProblem, DebuggingProblem
from app.problem.models.multiple_choice_problem import MultipleChoiceProblem
from app.problem.models.short_answer_problem import ShortAnswerProblem
from app.problem.models.subjective_problem import SubjectiveProblem

logger = logging.getLogger(__name__)

PROBLEM_MODEL_MAP: Dict[str, Any] = {
    "coding": CodingProblem, "코딩": CodingProblem,
    "debugging": DebuggingProblem, "디버깅": DebuggingProblem,
    "multiple_choice": MultipleChoiceProblem, "객관식": MultipleChoiceProblem,
    "short_answer": ShortAnswerProblem, "단답형": ShortAnswerProblem,
    "subjective": SubjectiveProblem, "주관식": SubjectiveProblem,
}

ALLOWED_FIELDS_MAP: Dict[str, set[str]] = {
    "coding": {"title","image_url","description","difficulty","tags","problem_condition","reference_codes","test_cases","rating_mode"},
    "코딩":   {"title","image_url","description","difficulty","tags","problem_condition","reference_codes","test_cases","rating_mode"},
    "debugging": {"title","image_url","description","difficulty","tags","problem_condition","reference_codes","test_cases","rating_mode","base_code"},
    "디버깅":   {"title","image_url","description","difficulty","tags","problem_condition","reference_codes","test_cases","rating_mode","base_code"},
    "multiple_choice": {"title","image_url","description","difficulty","tags","options","correct_answers","rating_mode"},
    "객관식":          {"title","image_url","description","difficulty","tags","options","correct_answers","rating_mode"},
    "short_answer":    {"title","image_url","description","difficulty","tags","answer_text","rating_mode","grading_criteria"},
    "단답형":          {"title","image_url","description","difficulty","tags","answer_text","rating_mode","grading_criteria"},
    "subjective":      {"title","image_url","description","difficulty","tags","answer_text","rating_mode","grading_criteria"},
    "주관식":          {"title","image_url","description","difficulty","tags","answer_text","rating_mode","grading_criteria"},
}

def _as_list(v: Any) -> list:
    if v is None: 
        return []
    if isinstance(v, list): 
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s: 
            return []
        try:
            p = json.loads(s)
            return p if isinstance(p, list) else ([p] if p else [])
        except Exception:
            return [v]
    return [v]

def _as_lower(v: Any, default: str = "") -> str:
    s = "" if v is None else str(v).strip()
    return s.lower() if s else default

def _normalize_rating_mode(problem_type: str, v: Any) -> str:
    s = _as_lower(v)
    if problem_type in ("coding","코딩","debugging","디버깅"):
        return s if s in {"space","regex","hard","none"} else "none"
    if problem_type in ("multiple_choice","객관식"):
        return "none"
    if problem_type in ("short_answer","단답형"):
        return s if s in {"exact","partial","soft","none"} else "none"
    if problem_type in ("subjective","주관식"):
        return s if s in {"active","deactive"} else "deactive"
    return "none"

async def create_problem(db: AsyncSession, problem_data, maker_id: str, dedupe_title=None):
    # 1) 타입 확인 (Enum 값 추출)
    problem_type_enum = getattr(problem_data, "problemType", None)
    if not problem_type_enum:
        raise HTTPException(status_code=400, detail="문제 유형이 지정되지 않았습니다.")
    
    # Enum 값을 문자열로 변환
    # use_enum_values=True 설정이 있어도 안전하게 처리
    problem_type: str = (
        problem_type_enum.value 
        if hasattr(problem_type_enum, 'value') 
        else str(problem_type_enum)
    )
    
    if problem_type not in PROBLEM_MODEL_MAP:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 문제 유형: {problem_type}")
    
    model_cls = PROBLEM_MODEL_MAP[problem_type]
    allowed = ALLOWED_FIELDS_MAP[problem_type]

    # 2) dict 추출 (Pydantic v2 호환)
    # try:
    #     raw: Dict[str, Any] = problem_data.model_dump()
    # except AttributeError:
    #     raw = problem_data.dict()
    raw: Dict[str, Any] = problem_data.model_dump(mode="json")      # Enum을 문자열 값으로 변환

    # 3) 화이트리스트 필터
    data: Dict[str, Any] = {k: v for k, v in raw.items() if k in allowed}

    # 4) 공통 배열 보정
    if "tags" in allowed: 
        data["tags"] = _as_list(data.get("tags"))
    if "problem_condition" in allowed: 
        data["problem_condition"] = _as_list(data.get("problem_condition"))
    if "test_cases" in allowed: 
        data["test_cases"] = _as_list(data.get("test_cases"))
    if "grading_criteria" in allowed: 
        data["grading_criteria"] = _as_list(data.get("grading_criteria"))

    # 5) 타입별 정책
    if problem_type in ("coding","코딩"):
        data["reference_codes"] = _as_list(data.get("reference_codes"))
        data["rating_mode"] = _normalize_rating_mode(problem_type, data.get("rating_mode"))
        data.pop("base_code", None)

    elif problem_type in ("debugging","디버깅"):
        base_code = _as_list(data.get("base_code"))
        if not base_code:
            raise HTTPException(status_code=400, detail="디버깅 문제는 base_code가 최소 1개 필요합니다.")
        data["base_code"] = base_code
        data["rating_mode"] = _normalize_rating_mode(problem_type, data.get("rating_mode"))
        reference_codes = _as_list(data.get("reference_codes"))
        if not reference_codes:
            raise HTTPException(status_code=400, detail="디버깅 문제는 reference_codes(정답코드)가 최소 1개 필요합니다.")
        data["reference_codes"] = reference_codes

    elif problem_type in ("multiple_choice","객관식"):
        data["options"] = _as_list(data.get("options"))
        if not data["options"]:
            raise HTTPException(status_code=400, detail="객관식 문제는 options이 최소 1개 필요합니다.")
        data["correct_answers"] = _as_list(data.get("correct_answers"))
        data["rating_mode"] = "none"  # 객관식은 항상 "none"

    elif problem_type in ("short_answer","단답형"):
        answer = data.get("answer_text")
        # 딕셔너리 또는 배열 형식 지원
        if isinstance(answer, (dict, list)):
            data["answer_text"] = answer
        else:
            data["answer_text"] = _as_list(answer)
        data["rating_mode"] = _normalize_rating_mode(problem_type, data.get("rating_mode"))

    elif problem_type in ("subjective","주관식"):
        v = data.get("answer_text")
        # 리스트면 첫 번째 항목 사용
        if isinstance(v, list):
            data["answer_text"] = v[0] if v else ""
        # 딕셔너리면 JSON 문자열로 변환
        elif isinstance(v, dict):
            data["answer_text"] = json.dumps(v, ensure_ascii=False)
        else:
            data["answer_text"] = str(v) if v else ""
        data["rating_mode"] = _normalize_rating_mode(problem_type, data.get("rating_mode"))

    # 5-1) 중복 검사: 같은 사용자가 같은 유형·제목·설명의 문제를 이미 등록했는지 확인
    #      (삭제된 문제는 제외 -> 삭제 후 다시 등록할 수 있음)
    content_hash = compute_content_hash(problem_type, data.get("title") if dedupe_title is None else dedupe_title, data.get("description"))      # dedupe_title: 제목을 등록 코드로 바꿔 넣어도 같은 문제를 알아보도록 원래 제목으로 비교
    existing_id = await db.scalar(
        select(Problem.problem_id)
        .where(
            Problem.maker_id == maker_id,
            Problem.temporary_field_str_2 == content_hash,
            Problem.is_deleted.is_(False),
        )
        .limit(1)
    )
    if existing_id is not None:
        raise DuplicateProblemError(existing_id, content_hash)

    # 6) 데이터베이스 저장
    try:
        # temporary_field_str_2 = content_hash (문제 중복 체크용)
        problem_obj = model_cls(**data, maker_id=maker_id, temporary_field_str_2=content_hash)

        # 안전 가드: 코딩 문제 reference_codes 기본값
        if isinstance(problem_obj, CodingProblem) and getattr(problem_obj, "reference_codes", None) is None:
            problem_obj.reference_codes = []

        async with db.begin_nested():       # 중복 인덱스 위반 시 이 저장만 되돌리고 세션은 계속 쓴다
            db.add(problem_obj)
            await db.flush()
        return problem_obj

    except IntegrityError as e:
        msg = str(e.orig)
        if "uq_problem_maker_content_hash" in msg or "temporary_field_str_2" in msg:   # Postgres: 인덱스 이름 / SQLite: 컬럼 이름. 동시에 같은 문제가 먼저 들어간 경우 → 오류가 아니라 '중복'
            existing_id = await db.scalar(select(Problem.problem_id).where(
                Problem.maker_id == maker_id, Problem.temporary_field_str_2 == content_hash,
                Problem.is_deleted.is_(False)).limit(1))
            raise DuplicateProblemError(existing_id, content_hash)
        if "uq_problem_title_code" in msg or "problem.title" in msg:           # 등록 제목 코드(PY41_0007)가 겹침: 중복 문제가 아니라 번호 충돌이므로 호출한 쪽이 새 번호로 다시 시도한다
            raise TitleTakenError(str(data.get("title")))
        # await db.rollback()       # 세션 전체를 롤백 -> 성공한 문제들도 날아감
        logger.error("문제 저장 무결성 오류: %s", e.orig)   # 서버에서 오류 원인을 알려줌(오류날 때 DB구조를 프론트 노출 방지)
        raise HTTPException(status_code=400, detail="데이터 무결성 오류로 저장하지 못했습니다.")