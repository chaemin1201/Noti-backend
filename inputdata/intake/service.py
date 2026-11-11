# app/inputdata/intake/service.py
"""작업 생성 · AI 처리 · 검사 · 등록 · 승인 로직."""
import asyncio
import base64
import inspect
import json
import logging
import re
import os
import time
import types
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.problem.models.problem import Problem

from app.database import get_db
from app.inputdata.dedupe import DuplicateProblemError, TitleTakenError, compute_content_hash
from app.inputdata.schemas import format_validation_errors, problem_adapter
from ..crud.inputdata import create_problem
from . import config, llm
from .checks import checker
from .readers import images as images_mod, capture as capture_mod
from .models import (EDITABLE, IntakeCapture, ProblemTitleSeq, extras, unwrap as unwrap_description, wrap as wrap_description, AI_FAILED, APPROVABLE, BLOCKED, DUPLICATE, HELD, NEEDS_INPUT, NEEDS_REVIEW, PENDING, PROCESSING,
                     READY, REGISTER_FAILED, REGISTERED, IntakeItem, IntakeJob)
from .llm import parse_lines
from .checks.fix import ai_filled, approval_reason as echo_reason
from .checks import fix, suggest
from .checks.fix import fidelity_reason, fix_title
from . import parsing
from .parsing import attached_images, batch_user_text, user_text
# ====================================================================================================
# 목차 — 문제지 업로드 처리·승인·등록의 중심 파일입니다. 함수가 구역 순서로 모여 있습니다.
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
# 1. 작업 만들기 · 진행 관리
# ----------------------------------------------------------------------------------------------------

logger = logging.getLogger(__name__)


_RUNNING: set = set()            # 이 서버 프로세스에서 처리 중인 job_id


_SEM = None


_session_factory = None          # 테스트용: 세션 팩토리를 직접 지정


def set_session_factory(factory):
    global _session_factory
    _session_factory = factory

@asynccontextmanager
async def session_scope():
    """백그라운드 작업용 DB 세션. 요청 세션은 응답 후 닫히므로 새로 연다."""
    if _session_factory is not None:
        async with _session_factory() as db:
            yield db
        return
    agen = get_db()
    db = await agen.__anext__()
    try:
        yield db
    finally:
        await agen.aclose()

if config.exec_misconfigured():
    logger.warning("INTAKE_EXEC 는 켜졌지만 INTAKE_EXEC_ISOLATED 가 없어 정답 코드 실행 검증은 꺼진 상태로 동작합니다.")


def _now():
    return datetime.now(timezone.utc)

def is_running(job_id):
    return job_id in _RUNNING

def _alive(job):
    """이 프로세스에서 돌고 있거나, 다른 워커가 최근에 신호(heartbeat)를 남겼으면 살아 있는 작업이다."""
    if job.job_id in _RUNNING: return True
    hb = job.heartbeat_at
    if hb is None: return False
    if hb.tzinfo is None: hb = hb.replace(tzinfo=timezone.utc)
    return (_now() - hb).total_seconds() < config.heartbeat_seconds()

# ---------------------------------------------------------------- 작업 만들기
async def delete_jobs(db, job_ids):
    """작업과 그 항목·캡처를 지운다 (등록된 문제는 그대로). 지운 작업 수."""
    ids = list(job_ids)
    if not ids: return 0
    await db.execute(delete(IntakeCapture).where(IntakeCapture.job_id.in_(ids)))
    await db.execute(delete(IntakeItem).where(IntakeItem.job_id.in_(ids)))
    await db.execute(delete(IntakeJob).where(IntakeJob.job_id.in_(ids)))
    await db.commit()
    return len(ids)


async def purge_old_jobs(db):
    """보관 기간(INTAKE_JOB_DAYS)이 지난, 처리가 끝난 작업을 지운다. 새 작업을 올릴 때 함께 한다."""
    if not config.job_days(): return 0
    cutoff = _now() - timedelta(days=config.job_days())
    old = (await db.execute(select(IntakeJob.job_id).where(IntakeJob.created_at < cutoff, IntakeJob.status != "processing"))).scalars().all()
    return await delete_jobs(db, old)


async def create_job(db, maker_id, kind, file_names, records, mode, auto_register):
    await purge_old_jobs(db)
    job_id = str(uuid.uuid4())
    db.add(IntakeJob(job_id=job_id, maker_id=maker_id, status="processing", input_kind=kind, file_names=list(file_names),
                     options={"mode": mode, "auto_register": bool(auto_register)}, records_total=len(records), heartbeat_at=_now()))
    await db.flush()
    for i, rec in enumerate(records, 1):
        db.add(IntakeItem(job_id=job_id, seq=i, out_index=0, source_key=str(rec["key"]), record=rec, status=PENDING))
    await db.commit()
    return job_id

async def daily_usage(db, maker_id):
    """오늘(서버 시간 0시부터) 이 사용자가 만든 작업 수와 문제 수. 일일 한도 확인용."""
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    row = (await db.execute(select(func.count(), func.coalesce(func.sum(IntakeJob.records_total), 0)).where(IntakeJob.maker_id == maker_id, IntakeJob.created_at >= start))).one()
    return int(row[0] or 0), int(row[1] or 0)

async def active_job(db, maker_id):
    """처리 중인 작업이 있으면 돌려준다. 서버 재시작 등으로 멈춘 작업은 'paused' 로 바꾼다."""
    rows = (await db.execute(select(IntakeJob).where(IntakeJob.maker_id == maker_id, IntakeJob.status == "processing"))).scalars().all()
    live = None
    for j in rows:
        if _alive(j): live = j
        else:
            j.status, j.message = "paused", "서버가 다시 시작되어 중단되었습니다. 이어서 처리하려면 resume 을 호출하세요."
    await db.commit()
    return live

async def job_summary(db, job):
    counts = dict((await db.execute(select(IntakeItem.status, func.count()).where(IntakeItem.job_id == job.job_id).group_by(IntakeItem.status))).all())
    waiting = (await db.execute(select(func.count()).select_from(IntakeItem).where(
        IntakeItem.job_id == job.job_id, IntakeItem.record.is_not(None), IntakeItem.status.in_([PENDING, PROCESSING, AI_FAILED])))).scalar()
    filled = [st for st, rv in (await db.execute(select(IntakeItem.status, IntakeItem.review).where(
        IntakeItem.job_id == job.job_id, IntakeItem.review.is_not(None)))).all() if ai_filled(rv)]
    return {"job_id": job.job_id, "status": job.status, "message": job.message, "input_kind": job.input_kind, "files": job.file_names,
            "ai_filled": len(filled), "ai_filled_registered": sum(1 for st in filled if st == REGISTERED),     # 사후 점검 대상 수
            "auto_register": (job.options or {}).get("auto_register", True), "records_total": job.records_total,
            "records_done": job.records_total - waiting, "counts": counts,
            "needs_action": counts.get(NEEDS_REVIEW, 0) + counts.get(NEEDS_INPUT, 0) + counts.get(READY, 0) + counts.get(BLOCKED, 0) + counts.get(HELD, 0) + counts.get(REGISTER_FAILED, 0) + counts.get(AI_FAILED, 0),
            "created_at": job.created_at.isoformat() if job.created_at else None}

async def reset_failed(db, job_id):
    rows = (await db.execute(select(IntakeItem).where(IntakeItem.job_id == job_id, IntakeItem.status == AI_FAILED))).scalars().all()
    n = len(rows)
    for it in rows: it.status, it.error = PENDING, None
    await db.commit()
    return n

# ----------------------------------------------------------------------------------------------------
# 2. AI 처리 흐름 (작업 하나를 문제 단위로 처리)
# ----------------------------------------------------------------------------------------------------

async def _beat(db, job_id):
    j = await db.get(IntakeJob, job_id)
    if j: j.heartbeat_at = _now()

async def _keepalive(job_id):
    """AI 호출이 길어져도(재시도 대기만 수 분) 이 작업이 살아 있다고 계속 알린다. 호출이 끝나면 취소된다."""
    interval = max(1, config.heartbeat_seconds() // 3)
    while True:
        await asyncio.sleep(interval)
        try:
            async with session_scope() as db:        # 호출 중인 본 세션과 따로 연다
                await _beat(db, job_id); await db.commit()
        except Exception:
            logger.exception("heartbeat 갱신 실패: %s", job_id)

# ---------------------------------------------------------------- 등록
class SlowCall(Exception):
    """AI 응답이 기한 안에 오지 않아 그 문제를 보류로 돌리는 경우."""

async def _timed(fn, *args):
    """AI 호출 하나를 별도 스레드에서 실행하고 기다린다. config.call_deadline() 초를 넘기면 그 요청을 버리고 같은 요청을 한 번 더 보낸다(멈춘 호출 하나가 작업 전체를 붙잡지 않게)."""
    dl = config.call_deadline()
    if not dl:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), config.ai_item_timeout())
    try:
        return await asyncio.wait_for(asyncio.shield(asyncio.ensure_future(asyncio.to_thread(fn, *args))), dl)
    except asyncio.TimeoutError:
        logger.warning("AI 호출이 %s초 넘게 걸려 같은 요청을 다시 보냅니다", dl)
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args), config.call_hard_limit())
        except asyncio.TimeoutError:
            raise SlowCall(f"AI 응답이 {dl + config.call_hard_limit()}초가 지나도 오지 않았습니다")

# ---------------------------------------------------------------- AI 처리
def _accepts(fn, name):
    """fn 이 name 이라는 이름의 인자를 받는지 (가짜 AI 처럼 인자가 적은 함수에는 넘기지 않기 위해)."""
    try: return name in inspect.signature(fn).parameters
    except (TypeError, ValueError): return False

def _tokens(info):
    """(입력, 출력, 생각, 캐시) 토큰. 생각 토큰은 Gemini 가 출력과 별도로 세어 요금에 포함되고, 캐시는 같은 앞부분(프롬프트)을 다시 쓴 입력 토큰이다."""
    u = (info or {}).get("usage") or {}
    det = u.get("prompt_tokens_details") or {}
    return (u.get("promptTokenCount") or u.get("input_tokens") or u.get("prompt_tokens") or 0,
            u.get("candidatesTokenCount") or u.get("output_tokens") or u.get("completion_tokens") or 0,
            u.get("thoughtsTokenCount") or ((u.get("completion_tokens_details") or {}).get("reasoning_tokens") if isinstance(u.get("completion_tokens_details"), dict) else 0) or 0,
            u.get("cachedContentTokenCount") or u.get("cache_read_input_tokens") or (det.get("cached_tokens") if isinstance(det, dict) else 0) or 0)

def _log_call(calls, key, why, elapsed, info):
    i, o, th, ca = _tokens(info)
    calls.append((key, why, elapsed, i, o, th, ca))
    logger.info("AI 호출 %s [%s] %.1f초 토큰 입력 %s(캐시 %s) / 출력 %s / 생각 %s", key, why, elapsed, i or "?", ca, o or "?", th)

def _log_summary(calls, job_id):
    """작업이 느리고 토큰이 많이 드는 이유를 숫자로 볼 수 있게 호출 횟수, 다시 부른 횟수, 시간, 토큰(입력·캐시·출력·생각)을 한 줄로 남긴다."""
    if not calls: return
    again = sum(1 for c in calls if c[1] in ("고쳐 쓰기", "형식 다시 요청", "그림 줄여 다시"))
    light = sum(1 for c in calls if c[1] == "가벼운 호출")
    logger.info("AI 호출 요약 작업 %s: %d회(가벼운 호출 %d회, 다시 부른 것 %d회), 합계 %.0f초, 최장 %.1f초(%s), 토큰 입력 %d(캐시 %d) / 출력 %d / 생각 %d",
                job_id, len(calls), light, again, sum(c[2] for c in calls), max(c[2] for c in calls), max(calls, key=lambda c: c[2])[0],
                sum(c[3] for c in calls), sum(c[6] for c in calls), sum(c[4] for c in calls), sum(c[5] for c in calls))

def _default_ai():
    provider, model, key = llm.resolve()        # 키·모델이 없으면 SystemExit
    prompt = open(config.prompt_path(), encoding="utf-8").read()
    thinking = os.environ.get("LLM_THINKING") or None

    def call(user, images=None, info=None, system=None):
        sysp = system if system else llm.trim_prompt(prompt, user, has_images=bool(images))          # system: 짧은 메타 호출처럼 긴 프롬프트가 필요 없는 요청
        return llm.call_llm(provider, model, key, sysp, user, system and 1500 or config.max_tokens(), thinking=thinking, images=images, info=info)
    return call, model

async def _seen_hashes(db, job_id):
    seen = {}
    rows = (await db.execute(select(IntakeItem.payload).where(IntakeItem.job_id == job_id, IntakeItem.payload.is_not(None)))).scalars().all()
    for p in rows:
        try: seen[compute_content_hash(p.get("problemType"), p.get("title"), p.get("description"))] = p.get("title")
        except Exception: pass
    return seen

async def process_job(job_id, ai_fn=None):
    """백그라운드에서 문제를 하나씩 AI 에게 보내고, 검사하고, (자동 등록 대상이면) 등록한다."""
    global _SEM
    if job_id in _RUNNING: return
    _RUNNING.add(job_id)
    try:
        if _SEM is None: _SEM = asyncio.Semaphore(config.concurrent_jobs())
        async with _SEM:
            await _process(job_id, ai_fn)
    except Exception:
        logger.exception("작업 처리 중 예기치 않은 오류: %s", job_id)
        try:
            async with session_scope() as db:
                j = await db.get(IntakeJob, job_id)
                if j: j.status, j.message = "failed", "처리 중 예기치 않은 오류가 났습니다. 잠시 후 resume 으로 이어서 처리하세요."; await db.commit()
        except Exception:
            logger.exception("작업 상태 기록 실패")
    finally:
        _RUNNING.discard(job_id)

def _forced_hold(rec):
    """엑셀(또는 둘 다) 입력에서 이름이 없거나 같은 이름이 여러 번 나오면 AI 를 부르지 않고 바로 보류한다 (제목을 임의로 바꿔 등록하지 않기 위해)."""
    why = fix.unsolvable_reference(rec)
    if why:                                                                      # 교재 문제 번호만 있고 내용이 없는 문제: AI 를 부르지 않고 보류 (설명을 보고 풀 수 없으면 보류)
        return {"id": str(rec.get("key")), "payload": None, "review": {
            "상태": "보류", "보류사유": why, "입력종류": rec.get("입력종류") or "원본", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": ["문제 내용을 입력하거나 해당 교재 문제를 문서에 넣어 다시 올리세요"], "참고": ["서버가 AI 호출 전에 보류함"]}}
    if rec.get("스캔") and not rec.get("이미지"):
        memo = [str(m) for m in ((rec.get("intake") or {}).get("메모") or []) if "그림으로 만들지 못함" in str(m)]
        return {"id": str(rec.get("key")), "payload": None, "review": {
            "상태": "보류", "보류사유": "스캔 문서의 쪽을 그림으로 만들지 못해 읽을 수 없습니다. " + (memo[0] if memo else "서버에 PDF 그림 변환 도구가 필요합니다."),
            "입력종류": "원본", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": ["문제 내용을 직접 입력하거나 글이 있는 파일로 다시 올리세요"], "참고": ["서버가 AI 호출 전에 보류함"]}}
    f = rec.get("fields")
    if f is None: return None
    memo = [str(m) for m in ((rec.get("intake") or {}).get("메모") or [])]
    dup = next((m for m in memo if m.startswith("같은 이름이 여러 번 나옴")), None)
    if (f.get("이름") or "").strip() and not dup: return None
    why = ("엑셀에 이름이 없습니다. 이름을 채워야 합니다." if not (f.get("이름") or "").strip() else
           "같은 이름이 여러 번 나옵니다: " + dup.replace("같은 이름이 여러 번 나옴", "").strip() + ". 이름을 서로 다르게 고쳐야 합니다.")
    key = str(rec.get("key") or (f.get("이름") or "").strip() or "이름없음")
    return {"id": key, "payload": None, "review": {
        "상태": "보류", "보류사유": why, "입력종류": rec.get("입력종류") or "엑셀", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": ["이름을 확인하세요"], "참고": ["서버가 AI 호출 전에 보류함"]}}

def _batchable(rec, mode, light_on):
    """묶어서 보낼 수 있는 문제: 그림이 없는 짧은 엑셀·원본 문제이고, 방식 분할 후보가 아니며, 가벼운 호출·이름 보류 대상이 아닌 것."""
    if rec.get("입력종류") not in ("엑셀", "원본") or rec.get("이미지") or _forced_hold(rec): return False
    it = rec.get("intake") or {}
    if it.get("방식표기") or any("분할 후보" in str(m) for m in (it.get("메모") or [])): return False
    if light_on and fix.light_payload(rec, mode): return False
    from .parsing import prompt_input
    return len(json.dumps(prompt_input(rec), ensure_ascii=False)) <= 2500

def _batch_key(rec):
    return (rec.get("입력종류"), rec.get("원본형식") or rec.get("표형식") or "")

async def _precheck(row, rec, exec_on):
    """AI 가 낸 결과 한 줄을 저장 전에 서버 검사로 미리 돌려 보고, 막힐 이유(중복 제외)를 돌려준다. (원본 row 는 바꾸지 않는다)"""
    import copy
    p = copy.deepcopy(row.get("payload")); rv = copy.deepcopy(row.get("review") or {})
    if p is None: return []
    if exec_on: await asyncio.to_thread(fix.fill, p, rv, checker.run_code, checker.norm_out)
    p, _ = fix.normalize(p, rv)
    if p is None: return []                                    # 보류 결과(payload 없음)는 검사할 것이 없다
    fix.drop_false_injection(rec, rv)
    fix_title(rec, p)
    case = {"id": row.get("id"), "payload": p, "review": rv}
    if rec.get("원본조각"): case["원본조각"] = rec["원본조각"]
    if rec.get("이미지"): case["그림있음"] = True
    fails, _w = await asyncio.to_thread(checker.check_case, case, {}, not exec_on)
    out = [f for f in fails if not str(f).startswith("dup:")]
    if p.get("problemType") == "디버깅" and any("base_code" in str(f) for f in out):
        out.append("base_code: 디버깅 문제의 제공 코드(문제에 주어진 코드)는 base_code [{language, code, is_main:false}] 에 넣고, reference_codes 에는 제공 코드까지 포함한 전체 정답 코드를 넣으세요. 설명에서는 그 코드 블록을 뺍니다.")
    if p.get("problemType") in ("코딩", "디버깅") and p.get("reference_codes") and not p.get("test_cases") and not any(w in " ".join(map(str, rv.get("확인필요") or [])) + " ".join(map(str, rv.get("참고") or [])) for w in ("매번 달라", "그래픽", "난수", "실행마다")):
        out.append("test_cases: 코딩·디버깅 문제에는 테스트 케이스가 필요합니다. 입력이 필요한 프로그램이면 입력 시나리오를 정하고, 정답 코드를 따라가 기대 출력과 함께 만드세요(출력이 매번 달라지는 문제나 그래픽 문제만 예외).")
    return out

def _split_fail(row, rec):
    """제목이 'ID-1' 로 끝나는데 혼자뿐이면(방식 분할이라 해 놓고 나머지 줄을 내지 않음) 다시 쓰게 할 이유를 돌려준다. 나머지 방식의 문제가 조용히 사라지는 것을 막는다."""
    msg = ("split: 제목이 '-1' 로 끝나 풀이 방식을 나눈 것으로 보이는데 '-2' 이후의 줄이 없습니다. 방식 수만큼 JSON 한 줄씩 모두 출력하세요. "
           "나머지 방식의 정답 코드는 입력에 없어도 직접 작성해 채우고(보류하지 마세요), 분할이 아니었다면 제목을 원래 ID 로 쓰세요.")
    rv = (row or {}).get("review") or {}
    if (row or {}).get("payload") is None and rv.get("상태") == "보류" and re.search(r"분할|나눠|나누", str(rv.get("보류사유") or "")):
        return [msg.replace("제목이 '-1' 로 끝나 풀이 방식을 나눈 것으로 보이는데 '-2' 이후의 줄이 없습니다.", "풀이 방식을 나눠야 한다는 이유로 보류했지만 분할은 보류 사유가 아닙니다.")]
    t = str(((row or {}).get("payload") or {}).get("title") or "")
    methods = {re.sub(r"\s", "", m) for m in ((rec.get("intake") or {}).get("방식표기") or []) if re.fullmatch(r"(?:방법|풀이)\s*\d+", str(m))}
    if len(methods) >= 2 and (row or {}).get("payload") is not None and not re.search(r"-\d+$", t) and not str(rec.get("key") or "").endswith(tuple(f"-{k}" for k in range(1, 10))):
        return [f"split: 풀이 방식이 {len(methods)}개({', '.join(sorted(methods))})인데 한 문제로 냈습니다. \"모두 작성\"이든 \"택1\"이든 방식 수만큼 문제로 나눠 JSON 한 줄씩 모두 출력하세요(제목은 원래 ID 뒤에 -1, -2 …). 방식마다 그 방식을 [필수] 조건으로 쓰고 \"모두 작성\" 같은 안내 문장은 빼세요."]
    if not re.search(r"-1$", t) or str(rec.get("key") or "").endswith("-1"): return []
    return [msg]

_NO_EXAMPLE_HOLD_RE = re.compile(r"입출력\s*예.{0,12}(?:없|부족)|(?:정답|해결책|풀이)\s*(?:코드)?.{0,12}(?:없|제공되지|부족)|test_cases.{0,20}(?:없|채울\s*수\s*없|작성\s*불가)|출력\s*예.{0,10}(?:없|부족)")


_IMAGE_RESULT_HOLD_RE = re.compile(r"(?:실행\s*결과|출력\s*(?:예|결과|형식)|입출력\s*예|콘솔).{0,40}(?:그림|이미지)|(?:그림|이미지).{0,40}(?:실행\s*결과|출력|입출력|콘솔)")


_UNSOLVED_HOLD_RE = re.compile(r"정답.{0,14}(누락|없|필요|입력|비어)|answer.{0,10}(missing|empty)", re.I)


def _hold_fail(row, rec):
    """객관식·단답형 정답이 비었다는 이유로 보류한 결과는 다시 쓰게 한다: 이 유형의 정답은 AI 가 직접 풀어 채우는 항목이다 (서술형 모범 답안만 사람이 입력)."""
    rv = (row or {}).get("review") or {}
    if (row or {}).get("payload") is not None or rv.get("상태") != "보류": return []
    why = str(rv.get("보류사유") or "")
    if _NO_EXAMPLE_HOLD_RE.search(why) and "본문" not in why and "서술" not in why and "주관식" not in why and "단답형" not in why and "객관식" not in why and rec.get("입력종류") != "엑셀":
        return ["hold: 입출력 예나 정답 코드가 입력에 없는 것은 보류 사유가 아닙니다. 정답 코드를 직접 작성하고 손 추적한 출력으로 test_cases 를 채우세요(입력이 필요하면 입력 시나리오를 정함). 문제 본문을 읽을 수 없을 때만 보류합니다."]
    if _IMAGE_RESULT_HOLD_RE.search(why) and "본문" not in why:
        return ["hold: 실행 결과·입출력 예가 그림으로만 있는 것은 보류 사유가 아닙니다. 첨부된 그림을 읽을 수 있으면 읽어 test_cases 로 옮기고, 읽을 수 없으면 정답 코드를 손 추적한 출력으로 test_cases 를 채운 뒤 확인필요에 \"원본 예시는 그림\"으로 적으세요. 보류는 문제 본문 자체를 읽을 수 없을 때만 합니다."]
    if not _UNSOLVED_HOLD_RE.search(why) or rec.get("이미지") or "서술" in why or "주관식" in why: return []
    return ["hold: 정답이 비어 있다는 이유는 보류 사유가 아닙니다. 객관식(options, correct_answers)과 단답형(answer_text)은 문제를 직접 풀어 채우세요(채움에 근거와 검증을 적음). 서술형 모범 답안만 비워 둡니다."]

def _confirmed_type(rec):
    """서버가 확정한 유형(코드 작성 소문항으로 나눈 문제: 코딩 또는 디버깅). 확정하지 않았으면 None."""
    it = (rec or {}).get("intake") or {}
    return it.get("유형힌트") if it.get("유형확정") else None

def _type_fail(row, rec):
    """서버가 확정한 유형과 다른 유형으로 낸 결과는 다시 쓰게 할 이유를 돌려준다 (모델마다 같은 문제를 다른 유형으로 정하면 설명·코드 위치·테스트 케이스가 모두 달라지기 때문)."""
    want = _confirmed_type(rec)
    p = (row or {}).get("payload")
    if not want or not isinstance(p, dict) or p.get("problemType") in (None, want): return []
    need = "base_code(문제에 주어진 코드), reference_codes(주어진 코드를 완성한 전체 실행 가능한 코드), test_cases" if want == "디버깅" else "reference_codes, test_cases"
    return [f"type: 서버가 이 문제를 코드를 작성하는 소문항으로 보고 유형을 '{want}' 로 확정했습니다. problemType 을 '{want}' 로 쓰고 {need} 를 채워 다시 쓰세요 (설명은 원문 그대로)."]


_LANG_OK = {"cpp": "cpp", "c": "c", "python": "python", "java": "java", "javascript": "javascript"}


async def _fill_code(rows, rec, ai_fn, wants_info, calls):
    """코딩·디버깅 결과에 정답 코드(reference_codes)나 제공 코드(base_code, 디버깅)가 끝내 비어 있으면(다시 쓰기로도 안 채워질 때) 서버가 채운다."""
    n = 0
    lang = _LANG_OK.get(str(((rec.get("intake") or {}).get("언어힌트") or "")).lower())
    for r in rows:
        p, rv = (r or {}).get("payload"), (r or {}).get("review")
        if not isinstance(p, dict) or p.get("problemType") not in ("코딩", "디버깅") or not isinstance(rv, dict): continue
        if p.get("problemType") == "디버깅" and not p.get("base_code"):
            code, rest = fix.extract_code_block(p.get("description"))
            if not code:                                                                # AI 가 설명에서 코드를 이미 뺐으면 원본 글에서 찾는다
                code, _ = fix.extract_code_block(rec.get("원본조각")); rest = p.get("description")
            if code:
                p["base_code"] = [{"language": lang or "python", "code": code, "is_main": False}]; p["description"] = rest; n += 1
                rv["정리"] = list(rv.get("정리") or []) + [{"항목": "base_code", "변경": "AI 가 비운 제공 코드를 설명의 코드 블록에서 서버가 옮김", "이유": "디버깅 문제는 제공 코드가 필요함"}]
        if not p.get("reference_codes") and lang:
            kw, info, t0 = {"system": fix.CODE_SYSTEM}, {}, time.time()
            if wants_info: kw["info"] = info
            try:
                got = fix.parse_code(await _timed(lambda: ai_fn(fix.code_request(p, lang), **kw)), lang)
            except Exception as e:
                logger.warning("정답 코드 호출 실패 %s: %s", rec.get("key"), e); got = None
            finally:
                _log_call(calls, rec.get("key"), "정답 코드", time.time() - t0, info)
            if got:
                p["reference_codes"] = got; n += 1
                rv["채움"] = [x for x in (rv.get("채움") or []) if not (isinstance(x, dict) and x.get("항목") == "reference_codes")] + [{"항목": "reference_codes", "내용": "제공 코드까지 포함한 전체 정답 코드", "근거": "설명과 제공 코드", "검증": "손 추적"}]
    return n

async def _fill_meta(rows, rec, ai_fn, wants_info, calls):
    """부제목·문제의도가 빠진 문제마다 짧은 메타 호출로 AI 가 문제를 보고 채운다 (채움에 '미검증' 으로 기록, 등록할 때 설명 화면의 칸에 들어간다). 실패해도 문제 처리는 계속한다."""
    f = (rec.get("fields") or {})
    for r in rows:
        p, rv = (r or {}).get("payload"), (r or {}).get("review")
        if not isinstance(p, dict) or not isinstance(rv, dict): continue
        have = {x.get("항목") for x in (rv.get("채움") or []) if isinstance(x, dict)}
        need = [k for k, lab in (("subtitle", "부제목"), ("intent", "문제의도")) if lab not in have and not str(f.get(lab) or "").strip()]
        if not need: continue
        kw, info, t0 = {"system": fix.META_SYSTEM}, {}, time.time()
        if wants_info: kw["info"] = info
        try:
            meta = fix.parse_meta(await _timed(lambda: ai_fn(fix.meta_request_payload(p, need), **kw)))
        except Exception as e:
            logger.warning("부제목·문제의도 호출 실패 %s: %s (비워 둠)", rec.get("key"), e); meta = {}
        finally:
            _log_call(calls, rec.get("key"), "메타", time.time() - t0, info)
        labels = {"subtitle": "부제목", "intent": "문제의도"}
        rv["채움"] = list(rv.get("채움") or []) + [{"항목": labels[k], "내용": meta[k], "근거": "문제 설명 요약", "검증": "미검증"} for k in need if k in meta]

def _repair_note(row, fails):
    """서버 검사에서 막힌 이유를 AI 에게 돌려주는 덧붙임 글. 모델이 비운 항목을 채우거나 틀린 곳을 고치게 한다."""
    prev = json.dumps(row, ensure_ascii=False)
    return ("\n\n[서버 검사 결과] 앞서 낸 결과가 아래 이유로 등록되지 않았습니다. 같은 입력으로 고쳐서 JSON 한 줄만 다시 출력하세요(풀이 방식을 나눈 결과이면 방식 수만큼 한 줄씩 모두). "
            "비어 있는 필수 항목(정답 코드, 입력 시나리오와 테스트 케이스 등)은 문제 설명을 보고 직접 채우고 채움에 기록하세요. "
            "문서·엑셀에 있는 값은 바꾸지 말고, 코드와 문서 값이 어긋나면 어긋난 사실을 확인필요에 적으세요.\n이유:\n"
            + "\n".join("- " + str(f)[:240] for f in fails[:6]) + "\n앞서 낸 결과: " + (prev if len(prev) <= 6000 else prev[:6000] + " …"))

async def _run_batches(ctx):
    """_process 의 한 부분. 바깥에서 쓰던 값은 ctx 로 받는다: ai_fn, calls, db, lock, mode, prefetch, sem, state, todo, wants_info, wants_system."""
    ai_fn, calls, db, lock, mode, prefetch, sem, state, todo, wants_info, wants_system = ctx.ai_fn, ctx.calls, ctx.db, ctx.lock, ctx.mode, ctx.prefetch, ctx.sem, ctx.state, ctx.todo, ctx.wants_info, ctx.wants_system
    n = config.batch_size()
    if n < 2: return
    light_on = config.light_rows() and wants_system
    loaded = []
    async with lock:
        for item_id in todo:
            it = await db.get(IntakeItem, item_id)
            if it is not None and it.status == PENDING and it.record and _batchable(it.record, mode, light_on): loaded.append((item_id, it.record))
    groups, cur = [], []
    for item_id, rec in loaded:                      # 이웃한 같은 종류끼리 n 개씩
        if cur and (_batch_key(cur[0][1]) != _batch_key(rec) or len(cur) >= n): groups.append(cur); cur = []
        cur.append((item_id, rec))
    if cur: groups.append(cur)

    async def one(group):
        async with sem:
            if state["stop"]: return
            info = {}
            kw = {"info": info} if wants_info else {}
            t0 = time.time()
            try:
                text = await _timed(lambda: ai_fn(batch_user_text([r for _, r in group], mode), **kw))
            except Exception as e:
                logger.warning("묶음 호출 실패 (문제마다 따로 처리): %s", e); return
            finally:
                _log_call(calls, "묶음 %d개(%s…)" % (len(group), group[0][1].get("key")), "묶음", time.time() - t0, info)
            rows = parse_lines(text)[0]
            for item_id, rec in group:                # 줄의 id 로 문제를 찾는다. 못 찾은 문제는 따로 처리한다
                ids = {str(rec.get("key") or ""), str(fix.expected_title(rec) or "")} - {""}
                mine = [r for r in rows if r["id"] in ids or any(r["id"].startswith(i + "-") for i in ids)]
                if mine: prefetch[item_id] = "\n".join(json.dumps(r, ensure_ascii=False) for r in mine)
    await asyncio.gather(*(one(g) for g in groups if len(g) >= 2))

async def _handle(ctx, item_id):
    """_process 의 한 부분. 바깥에서 쓰던 값은 ctx 로 받는다: ai_fn, auto, calls, db, exec_on, job_id, lock, maker_id, mode, prefetch, seen, sem, state, wants_info, wants_system."""
    ai_fn, auto, calls, db, exec_on, job_id, lock, maker_id, mode, prefetch, seen, sem, state, wants_info, wants_system = ctx.ai_fn, ctx.auto, ctx.calls, ctx.db, ctx.exec_on, ctx.job_id, ctx.lock, ctx.maker_id, ctx.mode, ctx.prefetch, ctx.seen, ctx.sem, ctx.state, ctx.wants_info, ctx.wants_system
    async with sem:
        if state["stop"]: return                     # 멈추기로 했으면 아직 시작하지 않은 문제는 그대로 둔다 (resume 으로 이어서)
        async with lock:
            it = await db.get(IntakeItem, item_id)
            if it is None or it.status != PENDING: return
            seq, rec = it.seq, it.record
            it.status = PROCESSING; await _beat(db, job_id); await db.commit()
        held = _forced_hold(rec)
        if held:                                       # 이름이 없거나 중복이면 AI 를 부르지 않고 바로 보류
            async with lock:
                await _store_rows(db, job_id, item_id, seq, rec, [held], seen, exec_on, auto, maker_id)
            return
        if config.light_rows() and wants_system:           # 완성된 엑셀·DB 행: 서버가 값으로 만들고 AI 에는 비어 있는 메타 정보만 짧게 묻는다
            light = fix.light_payload(rec, mode)
            if light:
                lp, need = light
                if not config.fill_cond(): need = [k for k in need if k not in ("conditions", "extra_cases")]
                meta, ok = {}, True
                if need:
                    kw = {"system": fix.META_SYSTEM}
                    info = {}
                    if wants_info: kw["info"] = info
                    t0 = time.time()
                    try:
                        meta = fix.parse_meta(await _timed(lambda: ai_fn(fix.meta_request(rec, need), **kw)))
                    except Exception as e:
                        logger.warning("가벼운 호출 실패 %s: %s (일반 호출로 처리)", rec.get("key"), e); ok = False
                    finally:
                        _log_call(calls, rec.get("key"), "가벼운 호출", time.time() - t0, info)
                if ok:
                    async with lock:
                        await _store_rows(db, job_id, item_id, seq, rec, [fix.light_row(rec, lp, meta, need)], seen, exec_on, auto, maker_id)
                    return
        keep = asyncio.create_task(_keepalive(job_id))
        async def ask(r, im, extra="", why="처음"):
            info = {}
            kw = {"images": im} if im else {}                              # 그림이 있으면 함께 보낸다 (AI 함수가 images 를 받는 경우만)
            if wants_info: kw["info"] = info
            call = (lambda u: ai_fn(u, **kw)) if kw else ai_fn
            t0 = time.time()
            try:
                return await _timed(call, user_text(r, mode) + extra)
            finally:
                _log_call(calls, rec.get("key"), why, time.time() - t0, info)
        try:
            imgs = attached_images(rec); used = (rec, imgs)
            try:
                pre = prefetch.pop(item_id, None)
                text = pre if pre is not None else await ask(rec, imgs)
            except Exception as first:
                if not (imgs and (isinstance(first, llm.TransientLLMError) or isinstance(first, asyncio.TimeoutError)) and not getattr(first, "fatal", False)): raise
                small = images_mod.shrink(imgs)                              # 그림이 많아 AI 가 오래 생각하다 끊긴 경우: 그림을 줄여 한 번 더 보낸다
                memo = list((rec.get("intake") or {}).get("메모") or []) + [f"처음 호출이 시간 초과로 끊겨 그림을 줄여 다시 보냄: 그림 {len(small)}장(번호 {[a['n'] for a in small]}), 긴 변 900px 이하. 보내지 못한 그림 내용은 확인필요에 적음"]
                logger.warning("그림 %d장 → %d장으로 줄여 다시 보냅니다: %s", len(imgs), len(small), rec.get("key"))
                used = ({**rec, "이미지": small, "intake": {**(rec.get("intake") or {}), "메모": memo}}, small)
                text = await ask(*used, why="그림 줄여 다시")
            parsed = parse_lines(text)[0]
            if not parsed and config.repair_rounds() > 0:                              # JSON 한 줄을 못 읽었으면 형식만 다시 요청한다
                try:
                    parsed = parse_lines(await ask(*used, why="형식 다시 요청", extra="\n\n[서버 검사 결과] 앞서 낸 출력에서 JSON 한 줄을 읽지 못했습니다. 설명·코드 펜스·여러 줄 없이, 출력 형식의 JSON 한 줄만 다시 출력하세요."))[0]
                except Exception as e3:
                    logger.warning("형식 다시 요청 실패 %s: %s", rec.get("key"), e3)
            for attempt in range(config.repair_rounds() + 1 if len(parsed) == 1 else 0):          # 서버 검사에서 막힐 결과면 이유를 알려 주고 AI 가 한 번 고쳐 쓰게 한다 (모델이 달라도 결과를 맞추는 장치)
                fails = await _precheck(parsed[0], rec, exec_on) + _split_fail(parsed[0], rec) + _hold_fail(parsed[0], rec) + _type_fail(parsed[0], rec)
                if not fails: break
                if attempt >= config.repair_rounds() and (config.repair_rounds() == 0 or not any(str(f).startswith(("split:", "schema:")) for f in fails)): break      # 방식 분할이 빠졌거나 필수 항목이 비었을 때만 한 번 더 시도한다
                try:
                    again = parse_lines(await ask(*used, why="고쳐 쓰기", extra=_repair_note(parsed[0], fails)))[0]
                except Exception as e2:
                    logger.warning("고쳐 쓰기 실패 %s: %s", rec.get("key"), e2); break
                if not again: break
                logger.info("고쳐 쓰기: %s (%d건 → 다시 검사) %s", rec.get("key"), len(fails), " | ".join(str(f)[:90] for f in fails[:3]))
                parsed = again
                if len(parsed) != 1: break                                  # 여러 줄(방식 분할)로 나뉘었으면 이후 검사는 저장 단계가 한다
        except SlowCall as e:                                               # 응답이 너무 늦은 문제는 기다리지 않고 보류로 돌린다 (재시도로 다시 처리)
            logger.warning("AI 응답 지연으로 보류 %s: %s", rec.get("key"), e)
            held = {"id": str(rec.get("key")), "payload": None, "review": {
                "상태": "보류", "보류사유": f"{e}. 처리 속도를 지키려고 이 문제는 보류했습니다. 잠시 뒤 재시도하면 다시 처리됩니다.",
                "입력종류": rec.get("입력종류") or "원본", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": ["AI 응답 지연: 재시도하세요"], "참고": ["서버가 응답 지연으로 보류함"]}}
            async with lock:
                await _store_rows(db, job_id, item_id, seq, rec, [held], seen, exec_on, auto, maker_id)
            return
        except Exception as e:
            async with lock:
                it = await db.get(IntakeItem, item_id)
                if getattr(e, "fatal", False):
                    it.status = PENDING; await db.commit()
                    state["stop"] = state["stop"] or ("failed", "AI 설정 오류로 중단했습니다. 관리자에게 문의하세요.")
                    return
                state["consec"] += 1
                logger.warning("AI 호출 실패 %s: %s", rec.get("key"), e, exc_info=not isinstance(e, (llm.TransientLLMError, asyncio.TimeoutError)))      # 예상 밖 오류는 어디서 났는지 남긴다
                it.status, it.error = AI_FAILED, "AI 호출에 실패했습니다. 잠시 후 다시 시도하세요."; await db.commit()
                if state["consec"] >= config.max_consecutive_ai_failures():
                    state["stop"] = state["stop"] or ("paused", f"AI 서버가 혼잡해 연속 {state['consec']}문제 호출에 실패해 중단했습니다. 잠시 후 resume 으로 이어서 처리하세요.")
            return
        finally:
            keep.cancel()
        fills = []                                                                       # 정답 코드 채우기와 부제목·의도 채우기는 서로 독립이라 동시에 한다 (한 문제의 호출이 줄줄이 이어지는 시간을 줄임)
        if parsed and wants_system and config.fill_code():
            fills.append(_fill_code(parsed, rec, ai_fn, wants_info, calls))                    # 다시 쓰기로도 비어 있는 제공 코드·정답 코드를 채운다
        if parsed and wants_system and config.fill_meta():
            fills.append(_fill_meta(parsed, rec, ai_fn, wants_info, calls))                    # 부제목·문제의도가 빠졌으면 짧은 호출로 채운다
        if fills: await asyncio.gather(*fills)
        async with lock:
            state["consec"] = 0
            rows = parsed
            if not rows:
                it = await db.get(IntakeItem, item_id); it.status, it.error = AI_FAILED, "AI 출력에서 결과를 읽지 못했습니다."; await db.commit()
                return
            await _store_rows(db, job_id, item_id, seq, rec, rows, seen, exec_on, auto, maker_id)

async def _process(job_id, ai_fn):
    exec_on = config.exec_enabled()
    async with session_scope() as db:
        job = await db.get(IntakeJob, job_id)
        if not job: return
        maker_id, mode, auto = job.maker_id, (job.options or {}).get("mode", "none"), (job.options or {}).get("auto_register", True)
        job.status, job.message, job.heartbeat_at = "processing", None, _now()
        await db.commit()
        if ai_fn is None:
            try:
                ai_fn, _ = _default_ai()
            except SystemExit as e:                 # 키·모델 미설정 — 입력은 그대로 두고 설정 후 resume
                logger.error("AI 설정 오류: %s", e)       # 실제 이유(키 없음, 모델 이름 없음 등)는 서버 로그에 남긴다
                return await _stop(db, job_id, "failed", "서버에 AI 설정이 없습니다. 관리자에게 문의하세요. (GEMINI_API_KEY, LLM_MODEL)")
            except OSError:
                return await _stop(db, job_id, "failed", "프롬프트 파일을 읽을 수 없습니다. 관리자에게 문의하세요. (INTAKE_PROMPT_PATH)")
        seen = await _seen_hashes(db, job_id)
        todo = (await db.execute(select(IntakeItem.item_id).where(IntakeItem.job_id == job_id, IntakeItem.status == PENDING,
                                                                 IntakeItem.record.is_not(None)).order_by(IntakeItem.seq))).scalars().all()
        lock = asyncio.Lock()                                # 한 DB 세션을 여러 문제가 동시에 쓰지 않도록 (AI 호출만 동시에 진행한다)
        sem = asyncio.Semaphore(max(1, config.concurrency()))
        calls = []                                           # 호출마다 (문제, 이유, 걸린 시간, 입력 토큰, 출력 토큰) — 작업이 끝나면 요약을 로그에 남긴다
        wants_info = _accepts(ai_fn, "info")
        wants_system = _accepts(ai_fn, "system")
        state = {"consec": 0, "stop": None}                  # stop: 작업을 멈출 이유 (상태, 메시지)

        prefetch = {}                                        # item_id -> 묶음 호출에서 받은 그 문제의 결과 글 (있으면 첫 호출을 건너뛴다)
        ctx = types.SimpleNamespace(ai_fn=ai_fn, auto=auto, calls=calls, db=db, exec_on=exec_on, job_id=job_id, lock=lock, maker_id=maker_id, mode=mode, prefetch=prefetch, seen=seen, sem=sem, state=state, todo=todo, wants_info=wants_info, wants_system=wants_system)                    # 아래 두 함수(_run_batches, _handle)가 쓰는 값 묶음

        await _run_batches(ctx)
        recs = {}
        if len(todo) >= 4:
            try:
                recs = dict((await db.execute(select(IntakeItem.item_id, IntakeItem.record).where(IntakeItem.item_id.in_(todo)))).all())
            except Exception:
                logger.exception("문제 입력 조회 실패(순서 정렬·캐시 데우기를 건너뜀)")
        warm = []
        if config.warmup() and config.concurrency() > 1 and recs:
            groups = {}
            for iid in todo:
                r = recs.get(iid) or {}
                if config.light_rows() and fix.light_payload(r, mode): continue                  # 가벼운 호출은 짧은 프롬프트라 데울 것이 없다
                groups.setdefault((_batch_key(r), bool(r.get("이미지"))), []).append(iid)
            warm = [g[0] for g in groups.values() if len(g) >= 4]                                 # 같은 프롬프트로 4문제 이상일 때만
        if warm:
            logger.info("프롬프트 캐시 데우기: %d개 프롬프트의 첫 문제를 먼저 처리", len(warm))
            await asyncio.gather(*(_handle(ctx, i) for i in warm))                                      # 프롬프트가 서로 다르므로 동시에: 앞부분(지시문)이 캐시에 올라간 뒤 나머지를 처리한다
        warmed = set(warm)
        def weight(iid):                                                                          # 무거운 문제(글이 길거나 방식이 여러 개라 출력이 긴 것)를 먼저 시작해야 마지막에 혼자 남는 긴 호출이 줄어든다
            r = recs.get(iid) or {}
            return len(json.dumps(r, ensure_ascii=False)) + 3000 * len((r.get("intake") or {}).get("방식표기") or [])
        await asyncio.gather(*(_handle(ctx, i) for i in sorted((x for x in todo if x not in warmed), key=weight, reverse=True)))
        _log_summary(calls, job_id)
        if state["stop"]: return await _stop(db, job_id, *state["stop"])
        await _stop(db, job_id, None, None)

async def _stop(db, job_id, status, message):
    j = await db.get(IntakeJob, job_id)
    if status is None:
        left = (await db.execute(select(func.count()).select_from(IntakeItem).where(
            IntakeItem.job_id == job_id, IntakeItem.status.in_([PENDING, PROCESSING, AI_FAILED])))).scalar()
        status = "done" if not left else "paused"
        message = None if not left else f"AI 처리에 실패한 문제 {left}개가 있습니다. resume 으로 다시 시도하세요."
    j.status, j.message = status, message
    if status == "done": j.finished_at = _now()
    await db.commit()

async def _store_rows(db, job_id, first_item_id, seq, rec, rows, seen, exec_on, auto, maker_id):
    ids = []
    for idx, r in enumerate(rows):
        r["review"] = r.get("review") or {}
        if exec_on and r.get("payload"):                                    # AI 가 손으로 추적한 기대 출력을 정답 코드의 실제 실행 출력으로 채움 (모델에 따라 틀리는 값을 서버가 바로잡는다)
            await asyncio.to_thread(fix.fill, r["payload"], r["review"], checker.run_code, checker.norm_out)
        fix.correct(rec, r)                                                    # 형식 바로잡기·원문 복원·설명 정리 등 서버 보정 전부 (AI·DB 호출 없음. 시험 도구도 같은 함수를 씀)
        if r.get("payload"):
            await asyncio.to_thread(fix.extend_cases, r["payload"], r["review"], checker.run_code, checker.norm_out, exec_on)      # 입력을 받는 코드인데 테스트 케이스가 1개뿐이면 입력만 다른 케이스를 2개까지 더함
            suggest.apply_conditions(r["payload"], r["review"])               # AI 가 제안한 조건(사용 기능·출력형식)을 정답 코드·기대 출력과 맞는지 확인하고 자동으로 더함
        fix.finish(rec, r)                                                     # 그림 올림 표시·거짓 경고 지우기·제목 되돌리기·서술형 답 비우기
        case = {"id": r["id"], "payload": r.get("payload"), "review": r.get("review") or {}, "record": rec}
        if rec.get("원본조각"): case["원본조각"] = rec["원본조각"]
        if rec.get("이미지"): case["그림있음"] = True          # 그림에서 옮긴 설명 글은 원본 글에 없으므로 설명 대조를 완화한다
        status, fails, warns, reasons = classify(case, seen, exec_on)
        await _give_code_title(db, case["payload"], case["review"])      # 제목을 영문·숫자 코드로 (중복 검사 classify 는 원래 제목으로 이미 끝났다)
        fix.fix_example_ref(rec, case["payload"], case["review"])         # 옮겨진 예시를 가리키던 말(np1 배열과 같이 → 출력 결과와 같이)을 고침: 원본 대조 검사 뒤에 고쳐야 '원본과 다름'으로 막히지 않는다
        if idx == 0:
            it = await db.get(IntakeItem, first_item_id)
        else:
            it = IntakeItem(job_id=job_id, seq=seq, out_index=idx, source_key=str(rec["key"]), record=None)
            db.add(it)
        it.result_id, it.payload, it.review = str(r["id"]), case["payload"], case["review"]
        it.check_fails, it.check_warns, it.approval_reasons, it.status, it.error = fails, warns, reasons, status, None
        await db.flush()
        ids.append((it.item_id, status, case["payload"]))
    await db.commit()
    for item_id, status, payload in ids:                # 깨끗한 것만 자동 등록
        if status == READY and auto:
            await _apply_register(db, item_id, payload, maker_id)

# ----------------------------------------------------------------------------------------------------
# 3. 상태 결정
# ----------------------------------------------------------------------------------------------------

# ---------------------------------------------------------------- 검사 결과 분류
def _runnable(payload):
    return bool(payload) and payload.get("problemType") in ("코딩", "디버깅") and payload.get("test_cases") and payload.get("reference_codes")

def classify(case, seen, exec_on):
    """(상태, 검사 실패, 검사 경고, 승인 필요 이유)"""
    fails, warns = checker.check_case(case, seen, skip_exec=not exec_on)
    review, payload = case.get("review") or {}, case.get("payload")
    if review.get("상태") == "보류" or payload is None:
        return (BLOCKED if fails else HELD), fails, warns, []
    if fails:
        return BLOCKED, fails, warns, []
    if fix.needs_input(payload):
        return NEEDS_INPUT, fails, warns, [fix.REASON]
    gaps = fix.test_case_gaps(payload)
    reasons = []
    notes = review.get("확인필요") or []
    if notes: reasons.append(f"AI가 사람이 확인할 것 {len(notes)}건을 표시했습니다.")
    if any(fix.UNSURE_TYPE_RE.search(str(n)) for n in notes):
        reasons.append("문제 유형이 5가지(코딩·디버깅·객관식·단답형·주관식)에 딱 맞지 않아 가장 가까운 유형으로 넣었습니다. 유형을 확인하세요.")
    if config.ai_answer_review() and (payload or {}).get("problemType") in ("객관식", "단답형") and {"correct_answers", "answer_text"} & set(fix.ai_filled(review)):
        reasons.append("AI 가 직접 푼 정답입니다(손으로 따라간 값이라 실행으로 확인할 수 없고 틀릴 수 있음). 정답을 확인하세요.")
    up = [g["n"] for g in (review.get("그림") or []) if isinstance(g, dict) and g.get("올림")]
    if up: reasons.append(f"문제에 올릴 그림 {len(up)}장(번호 {up}: 출력 예시·개념)이 있습니다. 정답이 보이지 않는지 확인하고 올리세요.")
    for w in warns:
        if str(w).startswith("ref:"): reasons.append("정답 코드에 제공 코드가 거의 들어 있지 않습니다. 제공 코드까지 포함한 전체 코드인지 확인하세요."); break
    r = checker.answer_leak_reason(payload)
    if r: reasons.append(r)
    r = checker.dup_option_reason(payload)
    if r: reasons.append(r)
    r = echo_reason(warns)
    if r: reasons.append(r)
    r = fidelity_reason(case.get("record"), payload)
    if r: reasons.append(r)
    if (review.get("제목정보") or {}).get("주제번호확실") is False:
        reasons.append("제목 코드의 주제 번호를 문제 ID에서 찾지 못해 0으로 했습니다. 등록 제목(" + str(review["제목정보"].get("등록제목")) + ")의 주제 번호를 확인하세요.")
    if _runnable(payload):
        if not exec_on:
            reasons.append("정답 코드를 서버에서 실행해 확인하지 않았습니다.")
        else:                                           # 실행 환경이 없는 언어(java 등)는 실행 검증을 건너뛰므로 사람이 확인
            skipped = sorted({str(w).split(":", 1)[1].strip() for w in warns if str(w).startswith("exec:") and "실행 환경 없음" in str(w)})
            if skipped: reasons.append(f"정답 코드를 실행해 확인하지 못했습니다 ({', '.join(skipped)}).")
    if gaps: return NEEDS_INPUT, fails, warns, gaps + reasons                          # 테스트 케이스 입력·출력 빈칸은 사람이 채워야 승인 가능
    return (NEEDS_REVIEW if reasons else READY), fails, warns, reasons

# ----------------------------------------------------------------------------------------------------
# 4. 등록 · 승인
# ----------------------------------------------------------------------------------------------------

async def register_payload(db, payload, maker_id, dedupe_title=None):
    """(상태, 정보). 항목 상태 변경과 같은 트랜잭션으로 묶기 위해 commit 은 호출한 쪽에서 한다."""
    try:
        data = problem_adapter.validate_python(payload)
    except ValidationError as e:
        return REGISTER_FAILED, {"error": "; ".join(f"{x['field']}: {x['message']}" for x in format_validation_errors(e))}
    try:
        async with db.begin_nested():
            obj = await create_problem(db, data, maker_id, dedupe_title=dedupe_title)
            pid = obj.problem_id
        return REGISTERED, {"problem_id": pid}
    except DuplicateProblemError as e:
        return DUPLICATE, {"problem_id": e.existing_problem_id}
    except TitleTakenError:
        return TITLE_TAKEN, {}
    except HTTPException as e:
        return REGISTER_FAILED, {"error": str(e.detail)}
    except Exception:
        logger.exception("등록 중 오류")
        return REGISTER_FAILED, {"error": "저장 중 오류가 발생했습니다."}

_CODE_TITLE = re.compile(r"^[A-Z]+\d+_\d{4,}$")                 # 등록 제목: 영문 대문자 + 숫자 + _ + 순번 (한글·공백·기호 없음)


TITLE_TAKEN = "title_taken"


async def _max_existing(db, prefix):
    """이미 등록된 제목 중 접두(PY41)의 가장 큰 번호. 검색은 startswith(autoescape) 로 해서 DB 마다 다른 ESCAPE 문자 규칙에 기대지 않는다."""
    titles = (await db.execute(select(Problem.title).where(Problem.title.startswith(prefix + "_", autoescape=True)))).scalars().all()
    pat = re.compile(r"^" + re.escape(prefix) + r"_(\d{4,})$")
    return max([int(m.group(1)) for t in titles for m in [pat.match(str(t))] if m] or [0])


async def allocate_title(db, prefix):
    """등록 제목 'PY41_0007' 을 하나 예약한다: 접두별 카운터 표의 한 줄을 원자적으로 +1 (서버가 여러 개여도 같은 번호가 나가지 않는다)."""
    try:
        async with db.begin_nested():
            exists = (await db.execute(select(ProblemTitleSeq.last_no).where(ProblemTitleSeq.prefix == prefix))).scalar()
            seed = 0 if exists is not None else await _max_existing(db, prefix)             # 처음 쓰는 접두만: 이미 등록된 가장 큰 번호에서 이어 간다
            name = db.sync_session.get_bind().dialect.name
            ins = (pg_insert if name == "postgresql" else sqlite_insert)(ProblemTitleSeq).values(prefix=prefix, last_no=seed + 1)
            ins = ins.on_conflict_do_update(index_elements=[ProblemTitleSeq.prefix], set_={"last_no": ProblemTitleSeq.last_no + 1}).returning(ProblemTitleSeq.last_no)
            n = (await db.execute(ins)).scalar_one()
    except Exception as e:                                                                  # 표가 없거나 이 DB 가 upsert 를 지원하지 않음
        logger.warning("제목 번호 카운터를 쓰지 못해 가장 큰 번호 + 1 로 대신합니다 (마이그레이션 필요): %s", type(e).__name__)
        n = await _max_existing(db, prefix) + 1
    return f"{prefix}_{n:04d}"

async def _give_code_title(db, payload, review):
    """처리 결과의 제목을 영문·숫자 코드로 바꾼다 (승인 화면에서도 코드로 보이게). 번호는 이때 예약해 등록할 때 그대로 쓰고,"""
    ti = (review or {}).get("제목정보")
    if not isinstance(ti, dict) or not isinstance(payload, dict): return
    t = await allocate_title(db, ti["코드접두"])
    payload["title"] = t
    ti["등록제목"] = t

async def _apply_register(db, item_id, payload, maker_id):
    it = await db.get(IntakeItem, item_id)
    rec = it.record
    if rec is None:                                    # 방식 분할(-2 이후)은 입력을 저장하지 않으므로 같은 문제의 첫 항목에서 가져온다
        rec = (await db.execute(select(IntakeItem.record).where(IntakeItem.job_id == it.job_id, IntakeItem.seq == it.seq,
                                                                IntakeItem.out_index == 0))).scalar_one_or_none()
    ti = dict((it.review or {}).get("제목정보") or fix.title_info(rec, payload))
    orig = ti.get("원래이름") or payload.get("title")                    # 중복 검사는 원래 제목으로 (제목이 코드로 바뀌어도 같은 파일을 다시 올리면 알아봄)
    t = str(payload.get("title") or "")
    if not _CODE_TITLE.match(t): t = await allocate_title(db, ti.get("코드접두") or "ETC0")      # 처리 때 예약한 코드가 없거나 손으로 바꾼 제목이면 새로 받음
    for _ in range(4):
        coded = {**payload, "title": t}
        status, info = await register_payload(db, wrap_description(coded, rec, it.review, name=ti.get("읽을이름") or ""), maker_id, dedupe_title=orig)
        if status != TITLE_TAKEN: break
        t = await allocate_title(db, ti.get("코드접두") or "ETC0")                          # 다른 곳에서 같은 번호가 먼저 쓰였으면 새 번호로 다시
    if status == TITLE_TAKEN: status, info = REGISTER_FAILED, {"error": "제목 번호가 계속 겹쳐 저장하지 못했습니다. 다시 시도하세요."}
    if status == REGISTERED: it.review = {**(it.review or {}), "제목정보": {**ti, "등록제목": t}}
    it.status, it.problem_id, it.error = status, info.get("problem_id"), info.get("error")
    await db.commit()
    return status, info

async def approve(db, job_id, maker_id, item_ids=None, edits=None):
    """승인(등록). item_ids 가 None 이면 승인할 수 있는 모든 항목."""
    results, edited = [], []
    for e in edits or []:
        iid = e["item_id"]
        it = await db.get(IntakeItem, iid)
        if it is None or it.job_id != job_id:
            results.append({"item_id": iid, "result": "skipped", "reason": "이 작업에 없는 항목입니다."}); continue
        if it.status not in EDITABLE:
            results.append({"item_id": iid, "result_id": it.result_id, "result": "skipped", "reason": f"상태가 {it.status} 이라 수정할 수 없습니다."}); continue
        try:
            await edit_payload(db, it, e["payload"] if e.get("payload") is not None else (it.payload or {}), e.get("subtitle"), e.get("intent"))
        except HTTPException as ex:
            results.append({"item_id": iid, "result_id": it.result_id, "result": "edit_failed", "detail": ex.detail}); continue
        edited.append(iid)
    if item_ids is not None: item_ids = list(dict.fromkeys([*item_ids, *edited]))
    q = select(IntakeItem.item_id).where(IntakeItem.job_id == job_id).order_by(IntakeItem.seq, IntakeItem.out_index)
    if item_ids is not None: q = q.where(IntakeItem.item_id.in_(item_ids))
    ids = (await db.execute(q)).scalars().all()
    for item_id in ids:
        it = await db.get(IntakeItem, item_id)
        rid, st, payload = it.result_id, it.status, it.payload
        if st not in APPROVABLE:
            if item_ids is not None:
                results.append({"item_id": item_id, "result_id": rid, "result": "skipped", "reason": f"상태가 {st} 이라 승인할 수 없습니다.",
                                "check_fails": it.check_fails or [], "approval_reasons": it.approval_reasons or []})
            continue
        status, info = await _apply_register(db, item_id, payload, maker_id)
        results.append({"item_id": item_id, "result_id": rid, "result": status, **info})
    if item_ids is not None:
        for i in item_ids:
            if i not in set(ids): results.append({"item_id": i, "result": "skipped", "reason": "이 작업에 없는 항목입니다."})
    return results


# ----------------------------------------------------------------------------------------------------
# 5. 승인 화면에서 쓰는 기능 (수정 후 재검사 · 원본 보기 · 조건 예시 · 원본 캡처)
# ----------------------------------------------------------------------------------------------------

# ---------------------------------------------------------------- 조회·승인·수정
def item_out(it, with_record=False):
    d = {"item_id": it.item_id, "seq": it.seq, "out_index": it.out_index, "source_key": it.source_key, "result_id": it.result_id,
         "status": it.status, "payload": it.payload, "review": it.review, "check_fails": it.check_fails or [],
         "check_warns": it.check_warns or [], "approval_reasons": it.approval_reasons or [], "problem_id": it.problem_id,
         "error": it.error, "edited": it.edited, "ai_filled": ai_filled(it.review)}
    name = ((it.review or {}).get("제목정보") or {}).get("읽을이름") or ""
    d["subtitle"], d["intent"] = extras(it.record, it.review, name)             # 폼의 부제목·문제의도 칸 기본값 (등록될 값과 같은 규칙)
    d["condition_example"] = suggest.example_condition(it.payload)             # 조건 칸에 바로 보여 줄 예시 하나 (정답 코드가 쓰는 것 기준), 없으면 None
    if with_record: d["record"] = it.record
    return d

def suggest_conditions(it, form=None, current=None):
    """조건 예시 하나: 정답 코드가 쓰는 것을 읽어 '무엇을 사용해서 작성해야 하는지'를 조건으로 돌려준다 (AI 호출 없음, 즉시, 저장 안 함)."""
    p = form if isinstance(form, dict) else (it.payload or {})
    if p.get("problemType") not in ("코딩", "디버깅"):
        raise HTTPException(status_code=400, detail="조건은 코딩·디버깅 문제에만 있습니다.")
    if not any(isinstance(c, dict) and str(c.get("code") or "").strip() for c in (p.get("reference_codes") or [])):
        raise HTTPException(status_code=400, detail="정답 코드가 없어 예시를 만들 수 없습니다. 정답 코드를 먼저 채워 주세요.")
    ex = suggest.example_condition(p, [str(x) for x in current] if current is not None else None)
    return {"example": ex, "message": None if ex else "정답 코드에서 조건으로 쓸 만한 것을 찾지 못했습니다."}

_CAPTURE_LOCK = asyncio.Lock()                                  # 문서 변환(LibreOffice)은 한 번에 하나씩


async def capture_job(job_id, files, records):
    """올린 문서를 쪽 이미지로 만들어 저장하고, 문제마다 어느 쪽인지 기록한다 (AI 처리와 따로 백그라운드로). 실패해도 처리에는 영향 없다."""
    if not config.capture() or not files: return
    res = None
    try:
        async with _CAPTURE_LOCK:
            res = await asyncio.to_thread(capture_mod.capture, files, records, config.capture_pages(), config.capture_dpi())
    except Exception:
        logger.exception("원본 캡처 실패: %s", job_id)
    try:
        async with session_scope() as db:
            if config.capture_days():                                      # 보관 기간이 지난 캡처 지우기
                cutoff = _now() - timedelta(days=config.capture_days())
                await db.execute(delete(IntakeCapture).where(IntakeCapture.created_at < cutoff))
            job = await db.get(IntakeJob, job_id)
            if job is None: return
            status = (res or {}).get("status") or "failed"
            if res:
                for cp in res["captures"]:
                    db.add(IntakeCapture(job_id=job_id, file_name=cp["file"], page_no=cp["page"], mime=cp["mime"], data=cp["data"]))
                for key, pages in res["map"].items():
                    it = (await db.execute(select(IntakeItem).where(IntakeItem.job_id == job_id, IntakeItem.source_key == key, IntakeItem.out_index == 0))).scalars().first()
                    if it is not None and it.record is not None: it.record = {**it.record, "캡처쪽": pages}
            job.options = {**(job.options or {}), "capture": {"status": status, "unsupported": (res or {}).get("unsupported") or []}}
            await db.commit()
    except Exception:
        logger.exception("원본 캡처 저장 실패: %s", job_id)

async def original_of(db, it):
    """승인 화면 왼쪽 패널용: 이 문제 하나의 원본(글·엑셀 열·그림)만 준다. 목록(with_record)보다 가볍고 필요한 것만 담는다."""
    rec = it.record
    if rec is None:                                    # 방식 분할(-2 이후)은 입력을 저장하지 않으므로 같은 문제의 첫 항목에서 가져온다
        rec = (await db.execute(select(IntakeItem.record).where(IntakeItem.job_id == it.job_id, IntakeItem.seq == it.seq,
                                                                IntakeItem.out_index == 0))).scalar_one_or_none()
    rec = rec or {}
    pages = rec.get("캡처쪽") or []
    caps = []
    if pages:
        rows = (await db.execute(select(IntakeCapture).where(IntakeCapture.job_id == it.job_id, IntakeCapture.file_name.in_({p["file"] for p in pages})))).scalars().all()
        have = {(r.file_name, r.page_no): r for r in rows}
        caps = [{"file": p["file"], "page": p["page"], "mime": have[(p["file"], p["page"])].mime, "b64": base64.b64encode(have[(p["file"], p["page"])].data).decode()}
                for p in pages if (p["file"], p["page"]) in have]
    job = await db.get(IntakeJob, it.job_id)
    cstat = ((job.options or {}).get("capture") or {}).get("status") if job else None
    capture_status = "ready" if caps else ("pending" if (config.capture() and not cstat and rec.get("원본형식") in ("PDF", "워드", "파워포인트", "한글")) else (cstat or "none"))
    return {"item_id": it.item_id, "captures": caps, "capture_status": capture_status, "kind": rec.get("입력종류"), "format": rec.get("원본형식") or rec.get("표형식"), "page": rec.get("page"),
            "text": rec.get("원본조각"), "fields": rec.get("fields"),
            "images": [{"n": g.get("n"), "mime": g.get("mime"), "b64": g.get("b64")} for g in (rec.get("이미지") or []) if isinstance(g, dict)],
            "answer_material": rec.get("정답자료"),                         # 교수님 풀이(정답): 교수용 화면에만 보여야 한다
            "split": rec.get("방식분할"), "whole_doc": bool(rec.get("문서전체")), "memo": (rec.get("intake") or {}).get("메모") or []}

async def edit_payload(db, item, payload, subtitle=None, intent=None):
    """사람이 payload(와 부제목·문제의도)를 고친다. 스키마 검사를 통과해야 저장되고, 서버 검사를 다시 돌려 상태를 정한다:"""
    payload = dict(payload)
    wrapped = unwrap_description(payload.get("description"))              # 프론트가 설명을 {"intent","subtitle","content"} 로 이미 묶어 보냈으면 풀어서 본문만 검사하고,
    if wrapped is not None:                                              # 부제목·문제의도는 따로 보관했다가 등록할 때 같은 모양으로 다시 묶는다
        payload["description"] = wrapped[0]
        if subtitle is None: subtitle = wrapped[1]
        if intent is None: intent = wrapped[2]
    try:
        problem_adapter.validate_python(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=format_validation_errors(e))
    rv = dict(item.review or {})
    for k in ("정리", "복구", "채움", "조언", "확인필요", "참고"): rv.setdefault(k, [])      # 검사기가 있다고 가정하는 키 (AI 결과에는 늘 있지만 없어도 안전하게)
    human = dict(rv.get("사람입력") or {})
    if subtitle is not None: human["부제목"] = str(subtitle).strip()
    if intent is not None: human["문제의도"] = str(intent).strip()
    if human: rv["사람입력"] = human
    if rv.get("상태") == "보류":                       # 보류 문제를 사람이 직접 채운 것: 보류 사유는 참고로 남기고 검사 대상으로 돌린다
        rv["참고"] = list(rv.get("참고") or []) + [f"보류 문제를 사람이 직접 채웠습니다 (보류 사유: {rv.get('보류사유') or '-'})"]
        rv["상태"], rv["보류사유"] = "등록가능", None
    status, fails, warns, reasons = classify({"id": item.result_id, "payload": payload, "review": rv}, {}, config.exec_enabled())
    item.payload, item.review, item.edited, item.error = payload, rv, True, None
    item.check_fails, item.check_warns = fails, warns
    if status == BLOCKED:
        item.status, item.approval_reasons = BLOCKED, []
    elif status == NEEDS_INPUT:
        item.status, item.approval_reasons = NEEDS_INPUT, reasons
    else:
        item.status = NEEDS_REVIEW
        item.approval_reasons = ["사람이 내용을 수정했습니다. 확인 후 승인하세요."] + [r for r in reasons if not r.startswith("AI 가 사람이 확인할 것")]
    await db.commit()
