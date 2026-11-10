"""짧은 문제를 여러 개씩 한 번의 AI 호출로 묶는 기능(INTAKE_BATCH) 시험 (가짜 AI).
noti_test 폴더에서:  python test_batch.py        (httpx, aiosqlite 필요)"""
import asyncio, csv, io, json, os, sys
import _bootstrap
_bootstrap.setup(sqlite=True)
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
from app.problem.models.problem import Problem  # noqa: F401
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem  # noqa: F401,E401
from app.inputdata.intake import router as intake_router, service, config, parsing
os.environ["INTAKE_FILL_META"] = "off"          # 이 시험은 호출 횟수를 세므로 부제목·문제의도를 채우는 추가 호출은 끈다 (test_meta_fill.py 가 따로 확인)

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {str(extra)[:300]}")

NL = chr(10)
print("1. 묶을 수 있는 문제 판정")
def rec(**kw):
    r = {"입력종류": "엑셀", "표형식": "엑셀", "key": "B_01", "fields": {"이름": "B_01", "유형": "코딩", "설명": "합", "정답코드": "print(1)", "출력": "1", "조건": "정수만"}, "intake": {"유형": "코딩", "유형추정": False, "필수누락": [], "메모": []}}
    r.update(kw); return r
check("그림이 없는 짧은 문제는 묶을 수 있다", service._batchable(rec(), "none", False))
check("그림이 붙은 문제는 묶지 않는다", not service._batchable(rec(이미지=[{"n": 1}]), "none", False))
check("방식 분할 후보는 묶지 않는다", not service._batchable(rec(intake={"메모": ["풀이 방식이 여러 개 → 문제 분할 후보"]}), "none", False) and not service._batchable({**rec(), "intake": {"방식표기": ["방법1"], "메모": []}}, "none", False))
check("글이 긴 문제는 묶지 않는다", not service._batchable(rec(fields={"이름": "B_01", "설명": "가" * 3000}), "none", False))
check("완성되어 가벼운 호출로 처리될 문제는 묶지 않는다", not service._batchable(rec(fields={"이름": "B_01", "유형": "코딩", "설명": "합", "정답코드": "print(1)", "출력": "1", "언어": "Python"}), "none", True))
b = parsing.batch_user_text([rec(), rec(key="B_02")], "none")
check("묶음 요청 글은 입력1, 입력2 로 나열하고 여러 문제임을 알린다", "입력1: " in b and "입력2: " in b and "[여러 문제]" in b, b[:200])

print("2. 업로드 흐름")
HEAD = ["이름", "유형", "설명", "정답코드", "입력", "출력", "조건", "언어"]
ROWS = [[f"B_0{i}", "코딩", f"{i}를 출력하시오", f"print({i})", "", str(i), "정수만 출력", "Python"] for i in range(1, 7)]
buf = io.StringIO(); w = csv.writer(buf); w.writerow(HEAD); [w.writerow(x) for x in ROWS]
CSV = buf.getvalue().encode("utf-8-sig")
CALLS = {"batch": 0, "single": 0}
def one(f):
    p = {"problemType": "코딩", "title": f["이름"], "description": f["설명"], "rating_mode": "none", "problem_condition": ["[필수] 정수만 출력"],
         "test_cases": [{"input": f.get("입력", ""), "expected_output": f["출력"], "is_hidden": False}], "reference_codes": [{"language": "python", "code": f["정답코드"], "is_main": True}]}
    return json.dumps({"id": f["이름"], "payload": p, "review": {"상태": "등록가능", "보류사유": None, "입력종류": "엑셀", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": [], "참고": []}}, ensure_ascii=False)
def ai_all(user, images=None, info=None, system=None):
    if "[여러 문제]" in user:
        CALLS["batch"] += 1
        outs = []
        for ln in user.split(NL):
            if ln.startswith("입력") and ": {" in ln: outs.append(one(json.loads(ln.split(": ", 1)[1])["fields"]))
        return NL.join(outs)
    CALLS["single"] += 1
    return one(json.JSONDecoder().raw_decode(user.split("입력: ", 1)[1])[0]["fields"])
def ai_drop_last(user, images=None, info=None, system=None):             # 묶음 응답에서 마지막 문제의 줄을 빠뜨린다
    out = ai_all(user, images, info, system)
    return NL.join(out.split(NL)[:-1]) if "[여러 문제]" in user else out

async def run(ai):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)
    async with S() as db:
        await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": "u1"}); await db.commit()
    service.set_session_factory(S)
    service._default_ai = lambda: (ai, "fake")
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60)
    r = await c.post("/intake/jobs", files=[("files", ("문제.csv", CSV, "text/csv"))])
    job = r.json()["job_id"]
    for _ in range(300):
        j = (await c.get(f"/intake/jobs/{job}")).json()
        if j["status"] != "processing": break
        await asyncio.sleep(0.1)
    items = (await c.get(f"/intake/jobs/{job}/items")).json()
    await engine.dispose()
    return j, {i["result_id"]: i for i in items}

os.environ["INTAKE_LIGHT_ROWS"] = "off"
CALLS.update(batch=0, single=0)
j0, i0 = asyncio.run(run(ai_all))
check("기본(INTAKE_BATCH 없음)은 묶지 않고 문제마다 호출한다 (6번)", CALLS == {"batch": 0, "single": 6} and len(i0) == 6, CALLS)

os.environ["INTAKE_BATCH"] = "3"
CALLS.update(batch=0, single=0)
j1, i1 = asyncio.run(run(ai_all))
check("INTAKE_BATCH=3 이면 6문제를 묶음 호출 2번으로 처리하고 개별 호출은 없다", CALLS == {"batch": 2, "single": 0} and len(i1) == 6 and j1["status"] == "done", (CALLS, j1["status"], len(i1)))
check("묶어서 받은 결과도 문제마다 맞게 저장된다 (섞이지 않음)", all(i1[f"B_0{k}"]["payload"]["test_cases"][0]["expected_output"] == str(k) and i1[f"B_0{k}"]["payload"]["description"] == f"{k}를 출력하시오" for k in range(1, 7)))

CALLS.update(batch=0, single=0)
j2, i2 = asyncio.run(run(ai_drop_last))
check("묶음 응답에서 빠진 문제는 따로 처리한다 (묶음 2번 + 개별 2번)", CALLS == {"batch": 2, "single": 2} and len(i2) == 6 and j2["status"] == "done", (CALLS, len(i2)))

def failing_batch(user, images=None, info=None, system=None):
    if "[여러 문제]" in user: raise RuntimeError("묶음 호출 실패")
    return ai_all(user, images, info, system)
CALLS.update(batch=0, single=0)
j3, i3 = asyncio.run(run(failing_batch))
check("묶음 호출이 실패하면 문제마다 따로 처리한다 (6번)", CALLS["single"] == 6 and len(i3) == 6 and j3["status"] == "done", (CALLS, j3["status"]))

print("3. 프롬프트 캐시 데우기")
import threading
EV = []
_lk = threading.Lock()
def ai_events(user, images=None, info=None, system=None):
    with _lk: EV.append("start")
    import time as _t; _t.sleep(0.15)
    out = ai_all(user, images, info, system)
    with _lk: EV.append("end")
    return out
os.environ.pop("INTAKE_BATCH", None)
os.environ["INTAKE_LIGHT_ROWS"] = "off"
EV.clear(); CALLS.update(batch=0, single=0)
j4, i4 = asyncio.run(run(ai_events))
check("같은 프롬프트의 6문제: 첫 호출이 끝난 뒤에 나머지가 시작된다 (캐시를 데움)", EV[:2] == ["start", "end"] and EV.count("start") == 6 and len(i4) == 6, EV[:6])
check("나머지는 동시에 처리된다 (두 번째 호출이 끝나기 전에 다른 호출이 시작)", EV[2:4] == ["start", "start"], EV[:8])
os.environ["INTAKE_WARMUP"] = "off"
EV.clear()
j5, i5 = asyncio.run(run(ai_events))
check("INTAKE_WARMUP=off 이면 처음부터 모두 동시에 시작한다", EV[:2] == ["start", "start"] and len(i5) == 6, EV[:6])
os.environ.pop("INTAKE_WARMUP")
os.environ.pop("INTAKE_LIGHT_ROWS", None)

print(f"{NL}결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
