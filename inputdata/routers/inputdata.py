import asyncio
import json
from datetime import datetime
from pydantic import ValidationError

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from typing import Annotated, List, Dict, Any

from app.database import Base, get_db
from app.security.security import get_current_user
from app.inputdata.schemas import InputDataRequest, problem_adapter, format_validation_errors
from ..crud.inputdata import create_problem
from app.inputdata.dedupe import DuplicateProblemError
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/inputdata"
)

@router.post("")
async def input_data_endpoint(
    input_data: InputDataRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """
    CSV에서 파싱한 여러 문제를 한 번에 업로드
    - 부분 성공 지원: 일부 문제 실패해도 다른 문제는 계속 업로드
    - 상세한 성공/실패 정보 반환
    """
    maker_id = current_user.get("sub")
    if not maker_id:
        raise HTTPException(status_code=401, detail="User ID not found in token")

    if not input_data.problems:
        raise HTTPException(status_code=400, detail="업로드할 문제가 없습니다.")

    created_problems: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []   # 이미 등록되어 건너뛴 문제 (오류가 아님)
    errors: List[Dict[str, Any]] = []

    # 각 문제를 순회하며 검증 + 업로드
    for idx, raw in enumerate(input_data.problems, start=1):
        title = raw.get("title", "제목 없음")
        ptype = raw.get("problemType", "유형 없음")

        # 1) 문제별 검사(실패해도 다음 문제로 계속)
        try:
            problem_data = problem_adapter.validate_python(raw)
        except ValidationError as e:
            errors.append({
                "index": idx,
                "title": title,
                "problemType": ptype,
                "error": format_validation_errors(e),
                "status_code": 422,
            })
            logger.warning(f"⚠️ 문제 #{idx} 검증 실패: {title}")
            continue

        # 2) 세이브포인트
        try:
            async with db.begin_nested():
                problem_obj = await create_problem(db, problem_data, maker_id)

            created_problems.append({
                "index": idx,
                "title": problem_obj.title,
                "problem_id": problem_obj.problem_id,
                "problemType": problem_data.problemType,
            })
            logger.info(
                f"✅ 문제 업로드 성공 - ID: {problem_obj.problem_id}, "
                f"제목: {problem_obj.title}, 유형: {problem_data.problemType}"
            )

        except DuplicateProblemError as e:
            duplicates.append({
                "index": idx,
                "title": title,
                "problemType": ptype,
                "existing_problem_id": e.existing_problem_id,
            })
            logger.info(f"⏭️ 문제 #{idx} 중복으로 건너뜀: {title} (기존 ID: {e.existing_problem_id})")

        except HTTPException as e:
            errors.append({
                "index": idx,
                "title": title,
                "problemType": ptype,
                "error": e.detail,
                "status_code": e.status_code,
            })
            logger.warning(f"⚠️ 문제 #{idx} 업로드 실패: {e.detail}")

        except Exception:
            logger.exception(f"❌ 문제 #{idx} 저장 중 오류")
            errors.append({
                "index": idx,
                "title": title,
                "problemType": ptype,
                "error": "저장 중 오류가 발생했습니다.",
                "status_code": 500,
            })

    # 성공한 문제들을 한 번에 확정
    await db.commit()

    # ===== 응답 생성 =====
    total_problems = len(input_data.problems)
    success_count = len(created_problems)
    duplicate_count = len(duplicates)
    error_count = len(errors)
    dup_note = f" 중복 {duplicate_count}개는 건너뛰었습니다." if duplicate_count else ""

    # 오류 없음 (일부 또는 전부 중복이어도 오류가 아니므로 성공)
    if error_count == 0:
        message = (
            f"모든 {success_count}개 문제가 성공적으로 업로드되었습니다! 🎉"
            if duplicate_count == 0
            else f"{success_count}개 문제가 업로드되었습니다.{dup_note}"
        )
        return {
            "status": "success",
            "message": message,
            "created": success_count,
            "failed": 0,
            "skipped_duplicates": duplicate_count,
            "created_problems": created_problems,
            "duplicates": duplicates,
        }

    # 부분 성공 (업로드 또는 중복 건너뜀이 있고 오류도 있음)
    elif success_count > 0 or duplicate_count > 0:
        return {
            "status": "partial",
            "message": f"{success_count}/{total_problems}개 문제가 업로드되었습니다. "
                      f"{error_count}개 문제에 오류가 발생했습니다.{dup_note}",
            "created": success_count,
            "failed": error_count,
            "skipped_duplicates": duplicate_count,
            "created_problems": created_problems,
            "duplicates": duplicates,
            "errors": errors,
        }

    # 모두 실패
    else:
        logger.error(f"❌ 모든 {total_problems}개 문제 업로드 실패")
        return {
            "status": "failure",
            "message": f"모든 {total_problems}개 문제 업로드에 실패했습니다.",
            "created": 0,
            "failed": error_count,
            "skipped_duplicates": 0,
            "errors": errors,
        }
