"""문제를 동시에 처리하는 기능과, 그림이 많아 첫 호출이 끊기면 그림을 줄여 다시 보내는 동작 시험 (가짜 AI).
noti_test 폴더에서:  python test_concurrency.py        (python-docx, Pillow 필요)"""
import asyncio, io, json, os, sys, threading, time
import _bootstrap
_bootstrap.setup(sqlite=True)
os.environ["INTAKE_MAX_FILES"] = "30"
try:
    import docx
    from PIL import Image
except ImportError as e:
    print(f"⏭ 건너뜀: {e.name} 가 필요합니다"); sys.exit(2)
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
from app.inputdata.intake import router as intake_router, service, llm

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
def make_docx(n, with_pics=False):
    d = docx.Document()
    for i in range(1, n + 1):
        d.add_paragraph(f"실습 {i}. 문제 {i} 를 풀어 보시오. 설명 글입니다.")
        if with_pics:
            b = io.BytesIO(); Image.new("RGB", (1500, 900), (10 * i, 50, 50)).save(b, "PNG")
            for _ in range(6): d.add_paragraph("그림").add_run().add_picture(io.BytesIO(b.getvalue()))
    buf = io.BytesIO(); d.save(buf); return buf.getvalue()

def reply(user):
    rec = json.loads(user.split("입력: ", 1)[1])
    return json.dumps({"id": rec["id"], "payload": {"problemType": "주관식", "title": rec["id"], "description": rec["원본조각"], "answer_text": ""},
                       "review": {"상태": "등록가능", "보류사유": None, "입력종류": "원본", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": [], "참고": []}}, ensure_ascii=False)

async def run(ai, docx_bytes, label):
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
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=120)
    t0 = time.time()
    r = await c.post("/intake/jobs", files=[("files", (label, docx_bytes, MIME))])
    job = r.json()["job_id"]
    for _ in range(400):
        j = (await c.get(f"/intake/jobs/{job}")).json()
        if j["status"] != "processing": break
        await asyncio.sleep(0.1)
    items = (await c.get(f"/intake/jobs/{job}/items")).json()
    await engine.dispose()
    return j, items, time.time() - t0

print("1. 동시 처리")
lock, cur, peak, calls = threading.Lock(), [0], [0], []
def slow_ai(user, images=None):
    with lock: cur[0] += 1; peak[0] = max(peak[0], cur[0]); calls.append(json.loads(user.split("입력: ", 1)[1])["id"])
    time.sleep(0.6)
    with lock: cur[0] -= 1
    return reply(user)
os.environ["INTAKE_CONCURRENCY"] = "3"
j, items, secs = asyncio.run(run(slow_ai, make_docx(6), "자바_문제.docx"))
check("6문제가 모두 처리된다", j["status"] == "done" and len(items) == 6 and all(i["status"] == "needs_input" for i in items), (j["status"], [i["status"] for i in items]))
check("동시에 최대 3개까지 호출한다", peak[0] == 3, peak[0])
check("순차(약 3.6초)보다 빠르다", secs < 3.0, f"{secs:.1f}초")
check("문제마다 결과가 섞이지 않는다 (결과 id 와 제목정보의 원래 이름이 같고, 제목 코드는 서로 다름)", sorted(i["result_id"] for i in items) == sorted(set(i["result_id"] for i in items)) and all(i["result_id"] == i["review"]["제목정보"]["원래이름"] for i in items) and len({i["payload"]["title"] for i in items}) == len(items))
os.environ["INTAKE_CONCURRENCY"] = "1"; peak[0] = 0
j, items, secs = asyncio.run(run(slow_ai, make_docx(3), "자바_문제.docx"))
check("INTAKE_CONCURRENCY=1 이면 하나씩 처리한다", j["status"] == "done" and peak[0] == 1 and len(items) == 3, (peak[0], len(items)))

print("2. AI 오류가 나면 멈추고, 이어서 처리할 수 있다")
os.environ["INTAKE_CONCURRENCY"] = "2"; os.environ["INTAKE_MAX_CONSEC_FAIL"] = "2"
def bad_ai(user, images=None):
    time.sleep(0.1); raise llm.TransientLLMError("혼잡")
j, items, _ = asyncio.run(run(bad_ai, make_docx(6), "자바_문제.docx"))
st = [i["status"] for i in items]
check("연속 실패가 한도에 닿으면 paused", j["status"] == "paused" and "혼잡" in (j.get("message") or ""), (j["status"], j.get("message")))
check("실패한 것은 ai_failed, 시작하지 않은 것은 pending 으로 남는다 (resume 으로 이어서)", st.count("ai_failed") >= 2 and st.count("pending") >= 1 and "needs_input" not in st, st)
del os.environ["INTAKE_MAX_CONSEC_FAIL"]

print("3. 그림이 많아 첫 호출이 끊기면 그림을 줄여 다시 보낸다")
seen = []
def img_ai(user, images=None):
    seen.append((len(images or []), sum(len(i["b64"]) for i in (images or [])), "그림을 줄여 다시 보냄" in user))
    if images and len(seen) == 1: raise llm.TransientLLMError("끊김")
    return reply(user)
os.environ["INTAKE_CONCURRENCY"] = "1"
j, items, _ = asyncio.run(run(img_ai, make_docx(2, with_pics=True), "자바_문제.docx"))
check("첫 호출은 그림 6장, 다시 보낼 때는 4장으로 줄이고 용량도 작으며, 다음 문제는 원래 그림으로 보낸다", len(seen) == 3 and seen[0][0] == 6 and seen[1][0] == 4 and seen[1][1] < seen[0][1] and seen[2][0] == 6, seen)
check("줄여서 보냈다는 사실이 AI 입력에 들어간다", seen[1][2] and not seen[0][2], seen)
check("결과는 정상으로 처리된다", j["status"] == "done" and all(i["status"] == "needs_input" for i in items) and len(items) == 2, (j["status"], [i["status"] for i in items]))

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
