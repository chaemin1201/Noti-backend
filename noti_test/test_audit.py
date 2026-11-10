"""사후 점검 표시(ai_filled) 시험: 자동 등록은 그대로 하되, AI 가 직접 푼 정답이 있는 항목을 조회·요약에서 구별한다.
가짜 AI 를 쓰므로 AI 호출 없음.   noti_test 폴더에서:  python test_audit.py"""
import asyncio, csv, io, json, os, sys
import _bootstrap
_bootstrap.setup(sqlite=True)
os.environ["INTAKE_MAX_FILES"] = "30"
import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base, get_db
from app.security.security import get_current_user
if "user" not in Base.metadata.tables:
    class _User(Base):
        __tablename__ = "user"; user_id: Mapped[str] = mapped_column(primary_key=True)
from app.problem.models.problem import Problem
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem
os.environ["INTAKE_AI_ANSWER_REVIEW"] = "off"          # 이 시험은 AI 가 푼 정답도 자동 등록하고 사후 점검 표시를 남기는 방식(끄기)을 확인한다. 기본(켬)은 test_policy.py
from app.inputdata.intake import router as intake_router, service
from app.inputdata.intake.checks import fix as audit

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

print("1. ai_filled 판단 (단위)")
f = audit.ai_filled
check("AI 가 푼 정답 항목만 골라냄", f({"채움": [{"항목": "correct_answers", "검증": "손 추적"}, {"항목": "problemType", "검증": "손 추적"}]}) == ["correct_answers"])
check("정답자료를 그대로 쓴 것('자료 일치')은 제외", f({"채움": [{"항목": "reference_codes", "검증": "자료 일치"}]}) == [])
check("정답코드·테스트 케이스·단답형 정답도 포함, 중복 제거", f({"채움": [{"항목": "reference_codes", "검증": "손 추적"}, {"항목": "test_cases", "검증": "미검증"}, {"항목": "answer_text", "검증": "손 추적"}, {"항목": "answer_text", "검증": "손 추적"}]}) == ["reference_codes", "test_cases", "answer_text"])
check("review 가 없거나 비어 있어도 안전", f(None) == [] and f({}) == [] and f({"채움": ["문자열"]}) == [])

print("2. 업로드 → 자동 등록 → 조회 (가짜 AI)")
def fake_ai(user):
    rec = json.loads(user.split("입력: ", 1)[1]); name = rec["fields"]["이름"].replace("문제 ", ""); d = rec["fields"]["설명"]
    base = {"title": name, "rating_mode": "none", "description": d}
    if name == "AUD-1": p, fill = {**base, "problemType": "객관식", "options": ["a", "b"], "correct_answers": [0]}, []                     # 정답을 입력으로 받음
    elif name == "AUD-2": p, fill = {**base, "problemType": "객관식", "options": ["a", "b"], "correct_answers": [1]}, [{"항목": "correct_answers", "내용": "b", "근거": "풀이", "검증": "손 추적"}]   # AI 가 풀었음
    else: p, fill = {**base, "problemType": "단답형", "answer_text": ["x"]}, [{"항목": "answer_text", "내용": "x", "근거": "정답자료", "검증": "자료 일치"}]   # 정답자료를 베낌
    rv = {"상태": "등록가능", "보류사유": None, "입력종류": "엑셀", "정리": [], "복구": [], "채움": fill, "조언": [], "확인필요": [], "참고": []}
    return json.dumps({"id": name, "payload": p, "review": rv}, ensure_ascii=False)
service._default_ai = lambda: (fake_ai, "fake")

def make_csv():
    out = io.StringIO(); w = csv.writer(out); NL = chr(10)
    w.writerow(["이름", "유형", "설명", "보기", "정답"])
    w.writerow(["문제 AUD-1", "객관식", "정답을 준 문제", "a" + NL + "b", "1"])
    w.writerow(["문제 AUD-2", "객관식", "정답이 빈 문제", "a" + NL + "b", ""])
    w.writerow(["문제 AUD-3", "단답형", "정답자료가 있는 문제", "", ""])
    return out.getvalue().encode("utf-8")

ENGINE = None
async def main():
    global ENGINE
    engine = ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)
    async with S() as db:
        await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": "u1"}); await db.commit()
    service.set_session_factory(S)
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60)
    r = await c.post("/intake/jobs", files=[("files", ("q.csv", make_csv(), "text/csv"))])
    check("업로드 202", r.status_code == 202, r.text[:200]); job = r.json()["job_id"]
    for _ in range(100):
        j = (await c.get(f"/intake/jobs/{job}")).json()
        if j["status"] != "processing": break
        await asyncio.sleep(0.1)
    check("3문제 모두 승인 없이 자동 등록 (보통 정책)", j["counts"] == {"registered": 3}, j["counts"])
    check("작업 요약에 사후 점검 대상 수가 나온다 (AI 가 푼 1개, 모두 등록됨)", j.get("ai_filled") == 1 and j.get("ai_filled_registered") == 1, {k: j.get(k) for k in ("ai_filled", "ai_filled_registered")})
    items = (await c.get(f"/intake/jobs/{job}/items")).json()
    by = {i["result_id"]: i for i in items}
    check("항목마다 ai_filled 목록이 붙는다", by["AUD-1"]["ai_filled"] == [] and by["AUD-2"]["ai_filled"] == ["correct_answers"] and by["AUD-3"]["ai_filled"] == [], {k: v["ai_filled"] for k, v in by.items()})
    only = (await c.get(f"/intake/jobs/{job}/items", params={"ai_filled": "true"})).json()
    check("ai_filled=true 는 AI 가 푼 항목만 (AUD-2)", [i["result_id"] for i in only] == ["AUD-2"], [i["result_id"] for i in only])
    check("ai_filled 필터에도 페이지(offset)가 적용된다", (await c.get(f"/intake/jobs/{job}/items", params={"ai_filled": "true", "offset": 1})).json() == [])
    check("필터를 안 주면 3개 모두", len((await c.get(f"/intake/jobs/{job}/items")).json()) == 3)
    return 0

async def _run():
    try: return await main()
    finally:
        if ENGINE is not None: await ENGINE.dispose()
asyncio.run(_run())
print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
