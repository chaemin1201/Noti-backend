"""부제목·문제의도를 AI 가 문제를 보고 채우는지 시험 (가짜 AI).
noti_test 폴더에서:  python test_meta_fill.py        (httpx, aiosqlite 필요)"""
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
from app.inputdata.intake import router as intake_router, service, config, parsing, models
from app.inputdata.intake.checks import fix

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {str(extra)[:300]}")

NL = chr(10)
print("1. 메타 호출 글")
req = json.loads(fix.meta_request_payload({"title": "T-1", "problemType": "코딩", "description": "합을 구하시오", "reference_codes": [{"code": "print(1)"}]}, ["subtitle", "intent"]))
check("메타 호출 글에 이름·유형·설명·정답 코드와 요청 키가 들어간다", req["요청"] == ["subtitle", "intent"] and req["이름"] == "T-1" and req["유형"] == "코딩" and "합을" in req["설명"] and req["정답코드"] == "print(1)", req)

print("2. 업로드 흐름: 큰 호출이 부제목·문제의도를 빠뜨리면 짧은 호출로 채운다")
CALLS = {"main": 0, "meta": 0}
def ai(user, images=None, info=None, system=None):
    if system:                                                     # 메타 호출
        CALLS["meta"] += 1
        d = json.loads(user)
        out = {}
        if "subtitle" in d["요청"]: out["subtitle"] = d["이름"] + " 요약"
        if "intent" in d["요청"]: out["intent"] = d["이름"] + " 으로 확인할 개념"
        return json.dumps(out, ensure_ascii=False)
    CALLS["main"] += 1
    f = json.JSONDecoder().raw_decode(user.split("입력: ", 1)[1])[0]["fields"]
    p = {"problemType": "코딩", "title": f["이름"], "description": f["설명"], "rating_mode": "none", "problem_condition": ["[필수] 정수만 출력"],
         "test_cases": [{"input": "", "expected_output": f["출력"], "is_hidden": False}], "reference_codes": [{"language": "python", "code": f["정답코드"], "is_main": True}]}
    fill = [{"항목": "부제목", "내용": "이미 있음", "근거": "x", "검증": "미검증"}, {"항목": "문제의도", "내용": "이미 있음", "근거": "x", "검증": "미검증"}] if f["이름"] == "M_01" else []
    return json.dumps({"id": f["이름"], "payload": p, "review": {"상태": "등록가능", "보류사유": None, "입력종류": "엑셀", "정리": [], "복구": [], "채움": fill, "조언": [], "확인필요": [], "참고": []}}, ensure_ascii=False)
HEAD = ["이름", "유형", "설명", "정답코드", "입력", "출력", "조건", "언어"]
buf = io.StringIO(); w = csv.writer(buf); w.writerow(HEAD)
for i in (1, 2, 3): w.writerow([f"M_0{i}", "코딩", f"{i}를 출력하시오", f"print({i})", "", str(i), "조건 문장 태그 없음", "Python"])      # 태그 없는 조건 → 가벼운 호출이 아니라 일반 호출
CSV = buf.getvalue().encode("utf-8-sig")

async def run():
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
    r = await c.post("/intake/jobs", files=[("files", ("문제.csv", CSV, "text/csv"))], data={"auto_register": "false"})
    job = r.json()["job_id"]
    for _ in range(300):
        if (await c.get(f"/intake/jobs/{job}")).json()["status"] != "processing": break
        await asyncio.sleep(0.05)
    items = (await c.get(f"/intake/jobs/{job}/items")).json()
    await engine.dispose()
    return {i["result_id"]: i for i in items}

os.environ["INTAKE_LIGHT_ROWS"] = "off"
got = asyncio.run(run())
f = lambda it: {x["항목"]: x for x in it["review"]["채움"]}
check("부제목·문제의도가 빠진 문제(M_02, M_03)는 메타 호출로 채워진다", f(got["M_02"]).get("부제목", {}).get("내용") == "M_02 요약" and f(got["M_03"]).get("문제의도", {}).get("내용") == "M_03 으로 확인할 개념", [f(got[k]) for k in ("M_02", "M_03")])
check("AI 가 이미 채운 문제(M_01)는 다시 묻지 않는다 (큰 호출 3번 + 메타 호출 2번)", CALLS == {"main": 3, "meta": 2} and f(got["M_01"])["부제목"]["내용"] == "이미 있음", CALLS)
check("채움에는 '미검증' 으로 기록한다", f(got["M_02"])["부제목"]["검증"] == "미검증")
wrapped = json.loads(models.wrap(got["M_02"]["payload"], None, got["M_02"]["review"])["description"])
check("등록할 때 설명 화면의 칸(subtitle, intent)에 들어간다", wrapped["subtitle"] == "M_02 요약" and wrapped["intent"] == "M_02 으로 확인할 개념", wrapped)

CALLS.update(main=0, meta=0)
os.environ["INTAKE_FILL_META"] = "off"
got2 = asyncio.run(run())
check("INTAKE_FILL_META=off 이면 메타 호출을 하지 않는다", CALLS["meta"] == 0 and "부제목" not in f(got2["M_02"]), CALLS)
os.environ.pop("INTAKE_FILL_META"); os.environ.pop("INTAKE_LIGHT_ROWS")

print(f"{NL}결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
