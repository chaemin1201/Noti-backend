"""실제 AI 로 보안 장치를 눈으로 확인하는 도구: (1) 개인정보가 들어 있는 문제지를 올렸을 때 AI 서비스로 실제 전송된 글에 개인정보가 없는지, (2) 하루 한도를 넘으면 AI 를 부르지 않고 거절하는지.
AI 는 문제 3개만 부른다 (비용 거의 없음). 임시 DB 를 쓰므로 실제 DB 는 건드리지 않는다. 키는 출력하지 않는다.
noti_test 폴더에서:  python diag_security.py"""
import asyncio, json, os, sys, tempfile
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
from app.inputdata.intake import router as intake_router, service, config

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
NL = chr(10)
os.environ["INTAKE_DAILY_PROBLEMS"] = "4"                  # 이 시험에서만: 하루 4문제 (3문제 올린 뒤 2문제를 더 올리면 거절돼야 함)
os.environ["INTAKE_MAX_FILES"] = "5"

DOC = ("자바 실습 과제 학번 : 20231234 이름 : 홍길동" + NL + "연락처 010-1234-5678 / hong@school.ac.kr" + NL + NL +
       "문제 JV01-0001" + NL + "두 정수를 입력받아 합을 출력하시오. (문의: 010-9876-5432)" + NL + "입력 1: 3 4" + NL + "출력 1: 7" + NL + NL +
       "문제 JV01-0002" + NL + "정수가 짝수이면 '짝수', 홀수이면 '홀수'를 출력하시오." + NL + "성명 : 김철수" + NL + "입력 1: 4" + NL + "출력 1: 짝수" + NL + NL +
       "문제 JV01-0003" + NL + "1부터 5까지의 합을 출력하시오." + NL + "출력 1: 15")
SECRETS = ["20231234", "홍길동", "010-1234-5678", "hong@school.ac.kr", "010-9876-5432", "김철수"]

real, model = service._default_ai()
SENT = []
def spy(user, images=None, info=None, system=None):
    SENT.append(user)                                      # AI 서비스로 가기 직전의 글을 그대로 기록한다
    return real(user, images, info, system)
service._default_ai = lambda: (spy, model)

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)
    async with S() as db:
        await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": "u1"}); await db.commit()
    service.set_session_factory(S)
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=120)
    files = [("files", ("자바_과제.txt", DOC.encode("utf-8"), "text/plain"))]

    print("=== 1. 개인정보가 들어 있는 문제지를 올린다 (원본에는 학번·이름·전화·이메일이 있음)")
    for s in SECRETS: print(f"   원본에 있음: {s}")
    r = await c.post("/intake/jobs", files=files)
    print("   업로드 응답:", r.status_code, {k: r.json().get(k) for k in ("records_total", "input_kind")})
    job = r.json()["job_id"]
    for _ in range(600):
        j = (await c.get(f"/intake/jobs/{job}")).json()
        if j["status"] != "processing": break
        await asyncio.sleep(0.5)
    print("   처리:", j["status"], j["counts"], "| AI 호출 수:", len(SENT))

    print("=== 2. AI 서비스로 실제 전송된 글에서 개인정보를 찾는다")
    blob = NL.join(SENT)
    for s in SECRETS: print(f"   {'❌ 전송됨' if s in blob else '✅ 없음  '}: {s}")
    print("   --- 전송된 글(첫 문제, 입력 JSON 부분) ---")
    first = SENT[0].split("입력: ", 1)[1]
    print("   " + first[:420])

    print("=== 3. 서버에 저장된 입력(DB)에도 개인정보가 없는지")
    items = (await c.get(f"/intake/jobs/{job}/items", params={"with_record": True})).json()
    stored = json.dumps([i.get("record") for i in items], ensure_ascii=False)
    for s in SECRETS: print(f"   {'❌ 저장됨' if s in stored else '✅ 없음  '}: {s}")
    memos = [m for i in items for m in ((i.get("record") or {}).get("intake") or {}).get("메모", []) if "개인정보" in m]
    print("   메모:", memos[:2])

    print("=== 4. 하루 한도 (이 시험에서만 하루 4문제로 낮춤): 이미 3문제를 올렸고 2문제를 더 올리면?")
    before = len(SENT)
    two = DOC.split("문제 JV01-0003")[0]
    r2 = await c.post("/intake/jobs", files=[("files", ("자바_과제2.txt", two.encode("utf-8"), "text/plain"))])
    print("   응답:", r2.status_code, r2.json().get("detail", r2.json()))
    print("   AI 호출 증가:", len(SENT) - before, "(0 이어야 함)")
    r3 = await c.post("/intake/preview", files=[("files", ("자바_과제2.txt", two.encode("utf-8"), "text/plain"))])
    print("   미리보기(한도에 세지 않음):", r3.status_code)
    await engine.dispose()

asyncio.run(main())
