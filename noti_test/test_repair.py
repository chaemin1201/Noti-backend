"""AI 결과가 서버 검사에서 막힐 때, 이유를 알려 주고 AI 가 한 번 고쳐 쓰게 하는 단계 시험 (가짜 AI).
실제 사례: 작은 모델이 정답 코드와 테스트 케이스를 비워 내서 막혔다.
noti_test 폴더에서:  python test_repair.py        (python-docx, Pillow 필요)"""
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
os.environ["INTAKE_FILL_META"] = "off"          # 이 시험은 AI 호출 횟수를 세므로 부제목·문제의도를 채우는 추가 호출은 끈다 (test_meta_fill.py 가 따로 확인)

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


SEP = chr(10) * 2 + "[서버 검사 결과]"
def good(rec_id, desc):
    return {"id": rec_id, "payload": {"problemType": "코딩", "title": rec_id, "description": desc, "rating_mode": "none",
            "problem_condition": ["[필수] 출력한다"], "test_cases": [{"input": "", "expected_output": "3", "is_hidden": False}],
            "reference_codes": [{"language": "python", "code": "print(1 + 2)", "is_main": True}]},
            "review": {"상태": "등록가능", "보류사유": None, "입력종류": "원본", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": [], "참고": []}}
def weak(rec_id, desc):                                    # 정답 코드와 테스트 케이스를 비워 낸 결과
    g = good(rec_id, desc); g["payload"].pop("reference_codes"); g["payload"].pop("test_cases"); g["payload"]["problem_condition"] = []; return g

print("1. 막힐 결과는 이유와 함께 돌려보내 한 번 고쳐 쓴다")
os.environ["INTAKE_CONCURRENCY"] = "1"; os.environ["INTAKE_REPAIR_ROUNDS"] = "1"
prompts = []
def ai(user, images=None):
    prompts.append(user); rec = json.loads(user.split("입력: ", 1)[1].split(SEP)[0])
    if "[서버 검사 결과]" in user: return json.dumps(good(rec["id"], rec["원본조각"]), ensure_ascii=False)
    return json.dumps(weak(rec["id"], rec["원본조각"]), ensure_ascii=False)
j, items, _ = asyncio.run(run(ai, make_docx(2), "자바_문제.docx"))
st = sorted(i["status"] for i in items)
check("약한 결과가 고쳐 쓴 결과로 바뀌어 막히지 않는다", j["status"] == "done" and "blocked" not in st and len(items) == 2, st)
check("문제마다 AI 를 2번(처음 + 고쳐 쓰기) 부른다", len(prompts) == 4, len(prompts))
rp = next(p for p in prompts if "[서버 검사 결과]" in p)
check("고쳐 쓰기 요청에 서버가 막은 이유와 앞서 낸 결과가 들어간다", "test_cases" in rp or "reference_codes" in rp and "앞서 낸 결과" in rp and "이유:" in rp, rp[-400:])
check("고쳐 쓴 결과의 정답 코드·테스트 케이스가 저장된다", all(i["payload"]["reference_codes"] and i["payload"]["test_cases"] for i in items))

print("2. 끄거나, 고쳐도 안 되면 막힌 채로 둔다 (무한 반복하지 않음)")
prompts.clear(); os.environ["INTAKE_REPAIR_ROUNDS"] = "0"
j, items, _ = asyncio.run(run(ai, make_docx(2), "자바_문제.docx"))
check("INTAKE_REPAIR_ROUNDS=0 이면 고쳐 쓰지 않고 막힌다", len(prompts) == 2 and all(i["status"] == "blocked" for i in items), ([i["status"] for i in items], len(prompts)))
def stubborn(user, images=None):
    prompts.append(user); rec = json.loads(user.split("입력: ", 1)[1].split(SEP)[0]); return json.dumps(weak(rec["id"], rec["원본조각"]), ensure_ascii=False)
prompts.clear(); os.environ["INTAKE_REPAIR_ROUNDS"] = "1"
j, items, _ = asyncio.run(run(stubborn, make_docx(2), "자바_문제.docx"))
check("필수 항목이 비어 막힌 결과는 한 번 더(총 2번) 고쳐 쓰게 하고 그래도 같으면 막힌 채로 둔다", len(prompts) == 6 and all(i["status"] == "blocked" for i in items), ([i["status"] for i in items], len(prompts)))
def boom(user, images=None):
    prompts.append(user)
    if "[서버 검사 결과]" in user: raise RuntimeError("고쳐 쓰기 중 오류")
    rec = json.loads(user.split("입력: ", 1)[1]); return json.dumps(weak(rec["id"], rec["원본조각"]), ensure_ascii=False)
j, items, _ = asyncio.run(run(boom, make_docx(2), "자바_문제.docx"))
check("고쳐 쓰기 호출이 실패해도 처음 결과는 버리지 않는다 (막힘으로 저장)", all(i["status"] == "blocked" for i in items) and j["status"] == "done", ([i["status"] for i in items], j["status"]))

print("3. 코딩 문제에 테스트 케이스가 없으면 사람에게 넘기기 전에 AI 가 만들게 한다")
def no_tests(rec_id, desc):                                 # 정답 코드와 조건은 있고 테스트 케이스만 비운 결과 (조건이 있어 스키마는 통과한다)
    g = good(rec_id, desc); g["payload"]["test_cases"] = []; return g
prompts.clear(); os.environ["INTAKE_REPAIR_ROUNDS"] = "1"
def ai3(user, images=None):
    prompts.append(user); rec = json.loads(user.split("입력: ", 1)[1].split(SEP)[0])
    return json.dumps((good if SEP in user else no_tests)(rec["id"], rec["원본조각"]), ensure_ascii=False)
j, items, _ = asyncio.run(run(ai3, make_docx(2), "자바_문제.docx"))
check("테스트 케이스가 비면 이유를 알려 주고 다시 만들게 한다 (문제마다 2번 호출)", len(prompts) == 4 and any("test_cases" in p and "테스트 케이스가 필요합니다" in p for p in prompts), len(prompts))
check("고친 뒤에는 테스트 케이스가 들어 있고 확인필요가 붙지 않는다", all(i["payload"]["test_cases"] for i in items) and not any(i["review"].get("확인필요") for i in items), [(len(i["payload"].get("test_cases") or []), i["review"].get("확인필요")) for i in items])
def graphic(user, images=None):
    prompts.append(user); rec = json.loads(user.split("입력: ", 1)[1]); g = no_tests(rec["id"], rec["원본조각"]); g["review"]["확인필요"] = ["그래픽 출력이라 테스트 케이스 없음"]; return json.dumps(g, ensure_ascii=False)
prompts.clear()
j, items, _ = asyncio.run(run(graphic, make_docx(2), "자바_문제.docx"))
check("그래픽·난수처럼 이유를 적은 경우는 다시 요청하지 않는다", len(prompts) == 2, len(prompts))

print("4. JSON 한 줄이 아닌 출력은 형식만 다시 요청한다")
prompts.clear(); os.environ["INTAKE_REPAIR_ROUNDS"] = "1"
def chatty(user, images=None):
    prompts.append(user); rec = json.loads(user.split("입력: ", 1)[1].split(SEP)[0])
    if "JSON 한 줄을 읽지 못했습니다" in user: return json.dumps(good(rec["id"], rec["원본조각"]), ensure_ascii=False)
    return "죄송하지만 이 문제는 설명이 필요합니다. 다음과 같이 정리했습니다: 문제 본문이 길어서 요약합니다."
j, items, _ = asyncio.run(run(chatty, make_docx(2), "자바_문제.docx"))
check("읽을 수 없는 출력은 형식 안내와 함께 한 번 더 요청해서 처리된다 (ai_failed 로 남지 않음)", len(prompts) == 4 and all(i["status"] != "ai_failed" for i in items) and len(items) == 2, ([i["status"] for i in items], len(prompts)))
prompts.clear(); os.environ["INTAKE_REPAIR_ROUNDS"] = "0"
j, items, _ = asyncio.run(run(chatty, make_docx(2), "자바_문제.docx"))
check("INTAKE_REPAIR_ROUNDS=0 이면 다시 요청하지 않는다", len(prompts) == 2 and all(i["status"] == "ai_failed" for i in items), ([i["status"] for i in items], len(prompts)))

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
