"""새 형식(.db, .txt, .pptx)이 업로드 API 에서 받아들여지고 끝까지 처리되는지 (가짜 AI).
noti_test 폴더에서:  python test_upload_formats.py"""
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



import sqlite3, tempfile, zipfile
def fake(user, images=None):
    rec = json.loads(user.split("입력: ", 1)[1])
    desc = rec.get("원본조각") or (rec.get("fields") or {}).get("설명") or "설명"
    return json.dumps({"id": rec["id"] if "id" in rec else rec["fields"]["이름"].replace("문제 ", ""), "payload": {"problemType": "주관식", "title": rec["id"] if "id" in rec else rec["fields"]["이름"].replace("문제 ", ""), "description": desc, "answer_text": ""},
                       "review": {"상태": "등록가능", "보류사유": None, "입력종류": "원본", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": [], "참고": []}}, ensure_ascii=False)
def mk_db():
    p = os.path.join(tempfile.mkdtemp(), "p.db"); c = sqlite3.connect(p); c.execute("create table problem (title text, description text, problem_type text)")
    c.executemany("insert into problem values (?, ?, ?)", [("DB1_01 가", "첫째를 설명하시오", "주관식"), ("DB1_02 나", "둘째를 설명하시오", "주관식")]); c.commit(); c.close()
    return open(p, "rb").read()
NL = chr(10)
TXT = NL.join(["문제 1: 첫째를 설명하시오.", "내용", "문제 2: 둘째를 설명하시오.", "내용"]).encode("cp949")
def mk_pptx():
    import io
    NS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    sp = lambda t: f'<p:sp><p:nvSpPr><p:cNvPr id="1" name="x"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:p><a:r><a:t>{t}</a:t></a:r></a:p></p:txBody></p:sp>'
    sld = lambda t: f'<p:sld {NS}><p:cSld><p:spTree>{sp(t)}</p:spTree></p:cSld></p:sld>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("ppt/presentation.xml", f'<p:presentation {NS}><p:sldIdLst><p:sldId id="256" r:id="rId1"/><p:sldId id="257" r:id="rId2"/></p:sldIdLst></p:presentation>')
        z.writestr("ppt/_rels/presentation.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://x/slide" Target="slides/slide1.xml"/><Relationship Id="rId2" Type="http://x/slide" Target="slides/slide2.xml"/></Relationships>')
        z.writestr("ppt/slides/slide1.xml", sld("실습 1. 첫째 슬라이드 문제를 푸시오")); z.writestr("ppt/slides/slide2.xml", sld("실습 2. 둘째 슬라이드 문제를 푸시오"))
    return b.getvalue()

async def run_files(files):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)
    async with S() as db:
        await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": "u1"}); await db.commit()
    service.set_session_factory(S); service._default_ai = lambda: (fake, "fake")
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=120)
    r = await c.post("/intake/jobs", files=files)
    if r.status_code != 202: await engine.dispose(); return r, None, None
    job = r.json()["job_id"]
    for _ in range(300):
        j = (await c.get(f"/intake/jobs/{job}")).json()
        if j["status"] != "processing": break
        await asyncio.sleep(0.1)
    items = (await c.get(f"/intake/jobs/{job}/items")).json(); await engine.dispose()
    return r, j, items

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
for label, name, data, mime, n in (("SQLite DB", "문제.db", mk_db(), "application/octet-stream", 2), ("CP949 텍스트", "문제.txt", TXT, "text/plain", 2), ("PPT", "슬라이드.pptx", mk_pptx(), PPTX, 2)):
    r, j, items = asyncio.run(run_files([("files", (name, data, mime))]))
    check(f"{label}: 업로드가 접수되고(202) 문제 {n}개가 끝까지 처리된다", r.status_code == 202 and j and j["status"] == "done" and len(items) == n and all(i["status"] in ("needs_input", "registered", "needs_review") for i in items), (r.status_code, r.text[:100], j and j["counts"]))
r, j, items = asyncio.run(run_files([("files", ("문제.db", mk_db(), "application/octet-stream")), ("files", ("문제.txt", TXT, "text/plain")), ("files", ("슬라이드.pptx", mk_pptx(), PPTX))]))
check("DB + 텍스트 + PPT 를 한 작업에 섞어도 6문제가 모두 처리된다 (표와 원본이 섞인 '혼합')", r.status_code == 202 and r.json()["input_kind"] == "혼합" and j["status"] == "done" and len(items) == 6, (r.status_code, r.text[:120], j and j["counts"]))
r, j, items = asyncio.run(run_files([("files", ("옛것.ppt", b"x", "application/vnd.ms-powerpoint"))]))
check("구형 .ppt 는 .pptx 로 저장해 달라는 안내와 함께 거절한다", r.status_code == 422 and ".pptx" in r.text, (r.status_code, r.text[:120]))
r, j, items = asyncio.run(run_files([("files", ("가짜.db", b"not sqlite", "application/octet-stream"))]))
check("SQLite 가 아닌 .db 는 안내와 함께 거절한다", r.status_code == 422 and "SQLite" in r.text, (r.status_code, r.text[:120]))

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
