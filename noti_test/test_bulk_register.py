"""한꺼번에 등록(approve 의 edits) + 임시 작업 데이터 정리(보관 기간, DELETE) 시험.
noti_test 폴더에서:  python test_bulk_register.py"""
import asyncio, json, os, sys
from datetime import datetime, timedelta, timezone
import _bootstrap
_bootstrap.setup(sqlite=True)
import httpx
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base, get_db
from app.security.security import get_current_user
if "user" not in Base.metadata.tables:
    class _User(Base):
        __tablename__ = "user"; user_id: Mapped[str] = mapped_column(primary_key=True)
from app.problem.models.problem import Problem
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem  # noqa: F401
from app.inputdata.intake import router as intake_router, service
from app.inputdata.intake.models import IntakeCapture, IntakeItem, IntakeJob

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1; print("  ✅", name)
    else: bad += 1; print("  ❌", name, extra)

def coding(n, **kw):
    p = {"problemType": "코딩", "title": f"PY11_{n:04d}", "description": f"{n}번 문제: {n}를 출력하시오.", "difficulty": "easy", "tags": ["t"], "rating_mode": "none",
         "problem_condition": ["[필수] 정수만 출력"], "test_cases": [{"input": "", "expected_output": str(n), "is_hidden": False}],
         "reference_codes": [{"language": "python", "code": f"print({n})", "is_main": True}]}
    p.update(kw); return p

REV = {"상태": "등록가능", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": [], "참고": []}
def item(job, seq, key, status, payload, **kw):
    ti = {"코드접두": "PY11", "등록제목": f"PY11_{seq:04d}", "원래이름": key, "읽을이름": "", "주제번호확실": True}
    return IntakeItem(job_id=job, seq=seq, out_index=0, source_key=key, result_id=key, status=status, payload=payload,
                      review={**REV, "상태": "보류" if payload is None else "등록가능", "제목정보": ti}, record={"입력종류": "원본", "원본조각": key}, **kw)

async def scenario():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine); service.set_session_factory(S)
    now = datetime.now(timezone.utc)
    async with S() as db:
        for u in ("u1", "u2"): await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": u})
        for jid in ("J1", "J2"): db.add(IntakeJob(job_id=jid, maker_id="u1", status="done", input_kind="원본", file_names=["a.docx"], options={}, records_total=5))
        db.add(IntakeJob(job_id="JOLD", maker_id="u1", status="done", input_kind="원본", file_names=["o"], options={}, records_total=1, created_at=now - timedelta(days=40)))
        db.add(IntakeJob(job_id="JOLDRUN", maker_id="u1", status="processing", input_kind="원본", file_names=["o"], options={}, records_total=1, created_at=now - timedelta(days=40)))
        db.add(IntakeJob(job_id="JRUN", maker_id="u1", status="processing", input_kind="원본", file_names=["o"], options={}, records_total=1, heartbeat_at=now))
        db.add(item("J1", 1, "A", "held", None)); db.add(item("J1", 2, "B", "needs_review", coding(2))); db.add(item("J1", 3, "C", "needs_review", coding(3)))
        db.add(item("J1", 4, "D", "blocked", coding(4), check_fails=["cond: 형식 오류"], approval_reasons=[]))
        db.add(item("J2", 1, "E", "needs_review", coding(9)))
        db.add(item("JOLD", 1, "OLD", "needs_review", coding(8)))
        db.add(IntakeCapture(job_id="JOLD", file_name="o", page_no=1, data=b"x"))
        await db.commit()
        ids = {i.source_key: i.item_id for i in (await db.execute(select(IntakeItem))).scalars().all()}
    who = {"u": "u1"}
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": who["u"]}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=30)
    r = {}
    fixed = coding(1); fixed["description"] = "A 문제를 사람이 채운 설명입니다."
    # 1) 한 번의 호출: A(보류)를 채워 등록 + B 는 잘못된 그림 주소로 수정 실패 + C 는 그대로 등록 + D 는 차단 상태
    body = {"edits": [{"item_id": ids["A"], "payload": fixed, "subtitle": "합", "intent": "덧셈"}, {"item_id": ids["B"], "payload": coding(2, image_url="javascript:x")}],
            "item_ids": [ids["C"], ids["D"]]}
    r["one"] = await c.post("/intake/jobs/J1/approve", json=body)
    # 2) 남은 것 전부 (B 는 수정 실패로 그대로 승인 대기였음, D 는 차단이라 제외)
    r["all"] = await c.post("/intake/jobs/J1/approve", json={"all": True})
    # 3) 다른 작업의 항목은 건드리지 않는다
    r["cross"] = await c.post("/intake/jobs/J1/approve", json={"edits": [{"item_id": ids["E"], "payload": coding(9, description="바꿔치기")}]})
    r["empty"] = await c.post("/intake/jobs/J1/approve", json={})
    who["u"] = "u2"; r["other"] = await c.post("/intake/jobs/J1/approve", json={"all": True}); who["u"] = "u1"
    async with S() as db:
        rows = (await db.execute(select(Problem))).scalars().all()
        r["db"] = [(p.title, json.loads(p.description)) for p in rows]
        r["e_status"] = (await db.get(IntakeItem, ids["E"])).status
        r["e_desc"] = (await db.get(IntakeItem, ids["E"])).payload["description"]
        # 4) 보관 기간
        n = await service.purge_old_jobs(db)
        r["purged"] = n
        left = {j for j in (await db.execute(select(IntakeJob.job_id))).scalars().all()}
        r["left"] = left
        r["old_items"] = len((await db.execute(select(IntakeItem).where(IntakeItem.job_id == "JOLD"))).scalars().all())
        r["old_caps"] = len((await db.execute(select(IntakeCapture).where(IntakeCapture.job_id == "JOLD"))).scalars().all())
    # 5) 지우기
    who["u"] = "u2"; r["del_other"] = (await c.delete("/intake/jobs/J2")).status_code; who["u"] = "u1"
    r["del_run"] = (await c.delete("/intake/jobs/JRUN")).status_code
    r["del_ok"] = await c.delete("/intake/jobs/J1")
    async with S() as db:
        r["j1_items"] = len((await db.execute(select(IntakeItem).where(IntakeItem.job_id == "J1"))).scalars().all())
        r["problems_after"] = len((await db.execute(select(Problem))).scalars().all())
    await engine.dispose()
    return r

r = asyncio.run(scenario())
print("1. 한 번의 호출로 수정 + 등록")
j = r["one"].json()
check("호출 한 번으로 A(보류→채움)·C 가 등록된다", r["one"].status_code == 200 and j["summary"].get("registered") == 2, j)
res = {x["item_id"]: x for x in j["results"]}
check("수정이 잘못된 항목(B: 그림 주소)은 edit_failed + 이유를 돌려주고 전체를 막지 않는다", j["summary"].get("edit_failed") == 1 and any(x["result"] == "edit_failed" and x.get("detail") for x in j["results"]), j)
check("차단(blocked) 항목 D 는 skipped + 검사 결과를 같이 돌려준다", any(x["result"] == "skipped" and x.get("check_fails") == ["cond: 형식 오류"] for x in j["results"]), j)
check("두 번째 호출(all)은 남은 B 만 등록한다 (이미 등록된 것·차단된 D 는 제외)", r["all"].json()["summary"] == {"registered": 1}, r["all"].json())
titles = [t for t, _ in r["db"]]
check("3개가 등록되고 제목은 영문·숫자 코드, 중복 없음", len(r["db"]) == 3 and len(set(titles)) == 3 and all(__import__("re").fullmatch(r"[A-Z]+\d+_\d{4}", t) for t in titles), titles)
a = next((d for _, d in r["db"] if d["content"].startswith("A 문제를 사람이")), None)
check("수정과 함께 보낸 부제목·문제의도가 등록된 설명에 들어간다", a == {"intent": "덧셈", "subtitle": "합", "content": "A 문제를 사람이 채운 설명입니다."}, a)
print("2. 안전")
cj = r["cross"].json()
check("다른 작업의 항목은 수정도 등록도 되지 않는다", cj["summary"] == {"skipped": 1} and r["e_status"] == "needs_review" and "바꿔치기" not in r["e_desc"], (cj, r["e_status"]))
check("아무것도 안 보내면 400", r["empty"].status_code == 400)
check("다른 사용자는 404", r["other"].status_code == 404)
print("3. 임시 작업 데이터 정리")
check("보관 기간(30일)이 지난 끝난 작업은 항목·캡처와 함께 지워진다", r["purged"] == 1 and "JOLD" not in r["left"] and r["old_items"] == 0 and r["old_caps"] == 0, (r["purged"], r["left"]))
check("처리 중인 작업은 오래돼도 지우지 않는다", "JOLDRUN" in r["left"] and "JRUN" in r["left"])
check("다른 사용자는 작업을 지울 수 없다 (404)", r["del_other"] == 404)
check("처리 중인 작업은 지울 수 없다 (409)", r["del_run"] == 409)
check("작업 지우기: 항목은 지워지고 등록된 문제는 그대로 남는다", r["del_ok"].status_code == 200 and r["j1_items"] == 0 and r["problems_after"] == 3, (r["del_ok"].text, r["j1_items"], r["problems_after"]))
print(f"결과: 통과 {ok} / 실패 {bad}")
sys.exit(1 if bad else 0)
