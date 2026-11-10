# app/inputdata/intake/router.py
"""문제지 업로드 → AI 정리 → 승인 후 등록 API.

  POST   /intake/preview                 AI 를 부르지 않고 파일을 문제로 나눈 결과만 확인 (문제 수·경계·그림·경고)
  POST   /intake/jobs                    파일 업로드(엑셀·워드·PDF…) → 작업 생성, 백그라운드 처리 시작 (202)
  GET    /intake/jobs                    내 작업 목록
  GET    /intake/jobs/{job_id}           진행 상황과 상태별 개수
  GET    /intake/jobs/{job_id}/items     결과 항목 (status 로 거르기)
  POST   /intake/jobs/{job_id}/approve   한꺼번에 등록 (item_ids / all / edits: 수정+재검사+등록을 한 번의 호출로)
  DELETE /intake/jobs/{job_id}           작업 데이터 지우기 (등록된 문제는 그대로)
  POST   /intake/jobs/{job_id}/resume    AI 처리에 실패했거나 중단된 문제를 이어서 처리
  PATCH  /intake/items/{item_id}         항목 내용(payload)·부제목·문제의도 수정 → 서버가 다시 검사해 상태를 정함
  GET    /intake/items/{item_id}/original  이 문제의 원본(글·엑셀 열·그림)만
  POST   /intake/items/{item_id}/suggest-conditions  조건 예시 하나 (정답 코드가 쓰는 것 기준, AI 없음)
  POST   /intake/items/{item_id}/reject  항목 제외
"""
import os
import tempfile
from typing import Annotated, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from app.database import get_db
from app.security.security import get_current_user
from . import config, parsing, service
from .models import ALL_STATUS, EDITABLE, REGISTERED, SKIPPED, DUPLICATE, IntakeItem, IntakeJob

router = APIRouter(prefix="/intake", tags=["intake"])


def _uid(current_user):
    uid = current_user.get("sub")
    if not uid: raise HTTPException(status_code=401, detail="User ID not found in token")
    return uid


async def _job(db, job_id, uid):
    j = await db.get(IntakeJob, job_id)
    if not j or j.maker_id != uid: raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return j


async def _item(db, item_id, uid):
    it = await db.get(IntakeItem, item_id)
    if not it: raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다.")
    j = await db.get(IntakeJob, it.job_id)
    if not j or j.maker_id != uid: raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다.")
    return it


async def _read_uploads(files):
    """올린 파일을 검사해 (표 위치, 원본 위치, [(이름, 확장자, 내용)]) 로. 작업 생성과 미리보기가 함께 쓴다."""
    if not files: raise HTTPException(status_code=400, detail="파일을 올려 주세요.")
    if len(files) > config.max_files(): raise HTTPException(status_code=400, detail=f"한 번에 최대 {config.max_files()}개 파일까지 올릴 수 있습니다.")
    tables, originals, blobs = [], [], []
    for f in files:
        k = parsing.kind_of(f.filename or "")
        if not k:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {os.path.basename(f.filename or '')} (표 .xlsx/.csv/.db(SQLite), 원본 .pdf/.docx/.pptx/.hwp/.hwpx/.txt/.md)")
        data = await f.read(config.max_file_bytes() + 1)
        if len(data) > config.max_file_bytes(): raise HTTPException(status_code=413, detail=f"파일이 너무 큽니다. (최대 {config.max_file_bytes() // 1024 // 1024}MB)")
        if not data: raise HTTPException(status_code=400, detail=f"빈 파일입니다: {os.path.basename(f.filename or '')}")
        (tables if k == "table" else originals).append(len(blobs)); blobs.append((os.path.basename(f.filename), os.path.splitext(f.filename)[1].lower(), data))
    return tables, originals, blobs


async def _parse_uploads(tables, originals, blobs, pattern):
    """(입력 종류, 문제 레코드 목록). 사용자가 고칠 수 있는 입력 문제는 422 로."""
    def parse():
        with tempfile.TemporaryDirectory() as d:                 # 업로드 원본은 파싱 후 바로 지운다 (저장하지 않음)
            paths = []
            for i, (_, ext, data) in enumerate(blobs):
                p = os.path.join(d, f"f{i}{ext}"); open(p, "wb").write(data); paths.append(p)
            return parsing.build_records([paths[i] for i in tables], [paths[i] for i in originals], pattern, [blobs[i][0] for i in originals], table_labels=[blobs[i][0] for i in tables])
    try:
        return await asyncio.to_thread(parse)
    except parsing.IntakeInputError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/preview")
async def preview(current_user: Annotated[dict, Depends(get_current_user)], files: List[UploadFile] = File(...), pattern: Optional[str] = Form(None)):
    """AI 를 부르지 않고 파일을 문제로 나눈 결과만 보여 준다 (문제 수, 경계, 그림, 이상 징후). 작업을 만들지 않고 아무것도 저장하지 않는다."""
    _uid(current_user)
    tables, originals, blobs = await _read_uploads(files)
    kind, records = await _parse_uploads(tables, originals, blobs, pattern)
    return parsing.preview_of(kind, records)


@router.post("/jobs", status_code=202)
async def create_job(background_tasks: BackgroundTasks, current_user: Annotated[dict, Depends(get_current_user)],
                     files: List[UploadFile] = File(...), mode: str = Form("none"), auto_register: bool = Form(True),
                     pattern: Optional[str] = Form(None), db: AsyncSession = Depends(get_db)):
    """엑셀(표) 하나 + 원본(PDF·워드·한글·txt·md) 여러 개 중 하나 이상을 올린다. 둘 다 올리면 서로 대조한다."""
    uid = _uid(current_user)
    tables, originals, blobs = await _read_uploads(files)
    if await service.active_job(db, uid): raise HTTPException(status_code=409, detail="처리 중인 작업이 있습니다. 끝난 뒤에 올려 주세요.")
    if mode not in ("none", "space", "regex", "hard", "exact", "partial", "soft"):
        raise HTTPException(status_code=400, detail="채점 모드 값이 올바르지 않습니다.")
    kind, records = await _parse_uploads(tables, originals, blobs, pattern)
    if len(records) > config.max_problems():
        raise HTTPException(status_code=413, detail=f"문제가 {len(records)}개입니다. 한 번에 최대 {config.max_problems()}개까지 처리할 수 있으니 나눠서 올려 주세요.")
    jobs_used, problems_used = await service.daily_usage(db, uid)
    if config.daily_jobs() and jobs_used >= config.daily_jobs():
        raise HTTPException(status_code=429, detail=f"오늘 올릴 수 있는 작업 수({config.daily_jobs()}개)를 모두 사용했습니다. 내일 다시 올려 주세요.")
    if config.daily_problems() and problems_used + len(records) > config.daily_problems():
        raise HTTPException(status_code=429, detail=f"오늘 처리할 수 있는 문제 수({config.daily_problems()}개)를 넘습니다. 오늘 이미 {problems_used}개를 올렸고 이번에 {len(records)}개입니다. 나눠서 내일 올려 주세요.")
    skipped = sorted({m.split(": ", 1)[1] for r in records for m in ((r.get("intake") or {}).get("메모") or []) if m.startswith("인식하지 못해 무시한 열: ")})
    job_id = await service.create_job(db, uid, kind, [b[0] for b in blobs], records, mode, auto_register)
    background_tasks.add_task(service.process_job, job_id)
    background_tasks.add_task(service.capture_job, job_id, [b for i, b in enumerate(blobs) if i in originals], records)       # 원본 캡처는 AI 처리와 따로
    return {"job_id": job_id, "status": "processing", "input_kind": kind, "records_total": len(records),
            "warnings": [f"엑셀 열을 인식하지 못해 값이 AI 에게 전달되지 않았습니다: {c}" for c in skipped],
            "message": "처리를 시작했습니다. GET /intake/jobs/{job_id} 로 진행 상황을 확인하세요."}


@router.get("/jobs")
async def list_jobs(current_user: Annotated[dict, Depends(get_current_user)], limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    uid = _uid(current_user)
    jobs = (await db.execute(select(IntakeJob).where(IntakeJob.maker_id == uid).order_by(IntakeJob.created_at.desc()).limit(limit))).scalars().all()
    return [await service.job_summary(db, j) for j in jobs]


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, current_user: Annotated[dict, Depends(get_current_user)], db: AsyncSession = Depends(get_db)):
    return await service.job_summary(db, await _job(db, job_id, _uid(current_user)))


@router.get("/jobs/{job_id}/items")
async def list_items(job_id: str, current_user: Annotated[dict, Depends(get_current_user)], status: Optional[str] = Query(None),
                     limit: int = Query(200, ge=1, le=200), offset: int = Query(0, ge=0), with_record: bool = False,
                     db: AsyncSession = Depends(get_db), ai_filled: bool = Query(False, description="true 면 AI 가 직접 푼 정답이 들어 있는 항목만 (등록 뒤 사후 점검용)")):
    await _job(db, job_id, _uid(current_user))
    if status and status not in ALL_STATUS: raise HTTPException(status_code=400, detail=f"status 는 {', '.join(ALL_STATUS)} 중 하나여야 합니다.")
    q = select(IntakeItem).where(IntakeItem.job_id == job_id)
    if status: q = q.where(IntakeItem.status == status)
    q = q.order_by(IntakeItem.seq, IntakeItem.out_index)
    if ai_filled:                                             # JSON 안의 값이라 DB 에서 거르지 않고 가져와서 거른다 (작업당 최대 200문제)
        items = [i for i in (await db.execute(q)).scalars().all() if service.ai_filled(i.review)][offset:offset + limit]
    else:
        items = (await db.execute(q.limit(limit).offset(offset))).scalars().all()
    return [service.item_out(i, with_record) for i in items]


class ApproveItem(BaseModel):
    item_id: int
    payload: Optional[dict] = None                  # 고친 문제 내용 전체 (없으면 지금 저장된 내용 그대로)
    subtitle: Optional[str] = Field(None, max_length=300)
    intent: Optional[str] = Field(None, max_length=500)


class ApproveRequest(BaseModel):
    item_ids: Optional[List[int]] = None            # 등록할 항목들
    all: bool = False                               # true 면 승인할 수 있는 모든 항목
    edits: Optional[List[ApproveItem]] = None       # 고친 항목들: 서버가 먼저 저장·재검사한 뒤 같이 등록 (한 번의 호출로 수정+등록)


@router.post("/jobs/{job_id}/approve")
async def approve(job_id: str, body: ApproveRequest, current_user: Annotated[dict, Depends(get_current_user)], db: AsyncSession = Depends(get_db)):
    """한꺼번에 등록한다: 문제마다 호출하지 말고 item_ids / all / edits 로 여러 개를 한 번에 보낸다."""
    uid = _uid(current_user)
    await _job(db, job_id, uid)
    if not body.all and not body.item_ids and not body.edits: raise HTTPException(status_code=400, detail="item_ids·edits 를 보내거나 all=true 로 보내세요.")
    edits = [e.model_dump() for e in (body.edits or [])]
    results = await service.approve(db, job_id, uid, None if body.all else (body.item_ids or []), edits)
    cnt = {}
    for r in results: cnt[r["result"]] = cnt.get(r["result"], 0) + 1
    return {"summary": cnt, "results": results}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, current_user: Annotated[dict, Depends(get_current_user)], db: AsyncSession = Depends(get_db)):
    """작업 데이터(작업·항목·캡처)를 지운다. 등록된 문제는 그대로다. 처리 중인 작업은 지울 수 없다."""
    job = await _job(db, job_id, _uid(current_user))
    if job.status == "processing" and service._alive(job): raise HTTPException(status_code=409, detail="처리 중인 작업은 지울 수 없습니다.")
    await service.delete_jobs(db, [job_id])
    return {"job_id": job_id, "deleted": True}


@router.post("/jobs/{job_id}/resume", status_code=202)
async def resume(job_id: str, background_tasks: BackgroundTasks, current_user: Annotated[dict, Depends(get_current_user)], db: AsyncSession = Depends(get_db)):
    uid = _uid(current_user)
    job = await _job(db, job_id, uid)
    if job.status == "processing" and service._alive(job): raise HTTPException(status_code=409, detail="아직 처리 중입니다.")   # paused·failed·done 은 heartbeat 가 남아 있어도 돌고 있지 않다
    other = await service.active_job(db, uid)
    if other and other.job_id != job_id: raise HTTPException(status_code=409, detail="다른 작업이 처리 중입니다.")
    n = await service.reset_failed(db, job_id)
    job = await _job(db, job_id, uid)
    job.status = "processing"; await db.commit()
    background_tasks.add_task(service.process_job, job_id)
    return {"job_id": job_id, "status": "processing", "retry_items": n}


class EditRequest(BaseModel):
    payload: dict                                   # 문제 내용 전체 (image_url 포함 가능)
    subtitle: Optional[str] = Field(None, max_length=300)     # 부제목 (보내지 않으면 그대로)
    intent: Optional[str] = Field(None, max_length=500)       # 문제의도 (보내지 않으면 그대로)


@router.patch("/items/{item_id}")
async def edit_item(item_id: int, body: EditRequest, current_user: Annotated[dict, Depends(get_current_user)], db: AsyncSession = Depends(get_db)):
    it = await _item(db, item_id, _uid(current_user))
    if it.status not in EDITABLE: raise HTTPException(status_code=409, detail=f"상태가 {it.status} 인 항목은 수정할 수 없습니다.")
    await service.edit_payload(db, it, body.payload, body.subtitle, body.intent)
    return service.item_out(await _item(db, item_id, _uid(current_user)))


@router.get("/items/{item_id}/original")
async def item_original(item_id: int, current_user: Annotated[dict, Depends(get_current_user)], db: AsyncSession = Depends(get_db)):
    """승인 화면 왼쪽 패널: 이 문제의 원본 글·엑셀 열·그림 (그림은 base64)."""
    return await service.original_of(db, await _item(db, item_id, _uid(current_user)))


class SuggestRequest(BaseModel):
    payload: Optional[dict] = None                  # 화면의 지금 내용(저장 전 수정 포함). 없으면 저장된 내용
    conditions: Optional[List[str]] = None          # 화면의 지금 조건 목록. 없으면 payload 의 problem_condition


@router.post("/items/{item_id}/suggest-conditions")
async def suggest_conditions(item_id: int, current_user: Annotated[dict, Depends(get_current_user)], body: SuggestRequest = SuggestRequest(),
                             db: AsyncSession = Depends(get_db)):
    """조건 예시 하나 (정답 코드가 쓰는 것 기준, AI 호출 없음). 항목 조회의 condition_example 과 같은 값이며, 화면에서 정답 코드를 고친 뒤 다시 받을 때 쓴다."""
    return service.suggest_conditions(await _item(db, item_id, _uid(current_user)), body.payload, body.conditions)


@router.post("/items/{item_id}/reject")
async def reject_item(item_id: int, current_user: Annotated[dict, Depends(get_current_user)], db: AsyncSession = Depends(get_db)):
    it = await _item(db, item_id, _uid(current_user))
    if it.status in (REGISTERED, DUPLICATE): raise HTTPException(status_code=409, detail="이미 등록된 항목은 제외할 수 없습니다.")
    it.status = SKIPPED; await db.commit()
    return {"item_id": item_id, "status": SKIPPED}
