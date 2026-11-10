"""원본 캡처 시험 (가짜 변환·가짜 그리기): 문제 ↔ 쪽 짝짓기, 저장·조회·보관 기간 삭제.
noti_test 폴더에서:  python test_capture.py
(실제 PDF 를 그리는 부분은 poppler/pypdfium2, 워드·PPT 변환은 LibreOffice 가 있는 환경에서만 되므로 여기서는 그 둘을 가짜로 바꿔 끼운다)"""
import asyncio, base64, os, sys
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
from app.problem.models.problem import Problem  # noqa: F401
import app.problem.models.coding_problem, app.problem.models.multiple_choice_problem, app.problem.models.short_answer_problem, app.problem.models.subjective_problem  # noqa: F401
from app.inputdata.intake import router as intake_router, service
from app.inputdata.intake.models import IntakeCapture, IntakeItem, IntakeJob
from app.inputdata.intake.readers import capture as cap

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1; print("  ✅", name)
    else: bad += 1; print("  ❌", name, extra)

print("1. 문제 ↔ 쪽 짝짓기")
P = ["표지 자료구조 중간 점검 1쪽", "문제 1. 스택의 특징으로 옳은 것은? ① FIFO ② LIFO 정답 ②\n문제 2. 큐의 삽입 연산 이름을 쓰시오", "정답 enqueue\n문제 3. 이진 탐색의 시간 복잡도를 쓰시오 정답 O(log n)", "끝 쪽 자료 마지막 쪽입니다"]
check("문제가 한 쪽에 있으면 그 쪽 하나", cap.find_pages("문제 1. 스택의 특징으로 옳은 것은?\n① FIFO ② LIFO 정답 ②", P) == [2])
check("공백·줄바꿈이 달라도 찾는다", cap.find_pages("문제1.스택의특징으로   옳은 것은?", P) == [2])
check("문제가 두 쪽에 걸치면 시작 쪽부터 끝 쪽까지", cap.find_pages("문제 2. 큐의 삽입 연산 이름을 쓰시오\n정답 enqueue", P) == [2, 3], cap.find_pages("문제 2. 큐의 삽입 연산 이름을 쓰시오\n정답 enqueue", P))
check("못 찾으면 빈 목록", cap.find_pages("없는 문장입니다 정말로 없는", P) == [])
check("너무 짧은 줄만 있으면 빈 목록", cap.find_pages("ab\ncd", P) == [])
check("한 문제에 붙이는 쪽은 최대 3쪽", len(cap.find_pages("표지 자료구조 중간 점검 1쪽" + chr(10) + "끝 쪽 자료 마지막 쪽입니다", P)) == 3)

print("2. 캡처 만들기 (가짜 변환·그리기)")
orig_to_pdf, orig_pages_text = cap.to_pdf, cap.pages_text
FAKE = {"office": True}
def fake_to_pdf(path, outdir, timeout=120):
    if path.endswith(".pdf"): return path
    return path if FAKE["office"] else None
cap.to_pdf = fake_to_pdf
TEXTS = {"f0.pdf": P, "f1.docx": ["워드 문서 1쪽 시작 부분 글", "워드 문서 2쪽 문제 글 두번째"]}
cap.pages_text = lambda pdf: TEXTS.get(os.path.basename(pdf), [])
render = lambda pdf, page, dpi, n: f"JPG:{os.path.basename(pdf)}:{page}".encode()
recs = [{"key": "A", "원본조각": "문제 1. 스택의 특징으로 옳은 것은?\n① FIFO ② LIFO 정답 ②"}, {"key": "B", "원본조각": "워드 문서 2쪽 문제 글 두번째"}, {"key": "C", "원본조각": "어디에도 없는 문제 글입니다"}]
files = [("a.pdf", ".pdf", b"%PDF"), ("b.docx", ".docx", b"x"), ("t.md", ".md", b"# md")]
r = cap.capture(files, recs, 40, 100, render=render)
check("PDF 와 워드(변환 가능)의 쪽이 이미지로 만들어진다", r["status"] == "done" and {(c["file"], c["page"]) for c in r["captures"]} == {("a.pdf", 2), ("b.docx", 2)}, r)
check("문제마다 어느 쪽인지 기록된다 (못 찾은 문제 C 는 없음)", r["map"] == {"A": [{"file": "a.pdf", "page": 2}], "B": [{"file": "b.docx", "page": 2}]}, r["map"])
check("md 같은 글 파일은 캡처하지 않는다", not any(c["file"] == "t.md" for c in r["captures"]))
check("이미지는 JPEG 로 온다", all(c["mime"] == "image/jpeg" and c["data"].startswith(b"JPG:") for c in r["captures"]))
r2 = cap.capture(files, recs, 1, 100, render=render)
check("파일 하나당 쪽 수 상한을 지킨다 (상한 1)", len([c for c in r2["captures"] if c["file"] == "a.pdf"]) <= 1 and len(r2["captures"]) <= 2)
FAKE["office"] = False
r3 = cap.capture([("b.docx", ".docx", b"x")], recs, 40, 100, render=render)
check("변환 도구(LibreOffice)가 없으면 워드는 '지원 안 함' + 캡처 없음", r3["status"] == "unsupported" and r3["captures"] == [] and r3["unsupported"] == ["b.docx"], r3)
check("PDF 는 도구 없이도 되므로 같이 올려도 PDF 만 캡처된다", cap.capture(files, recs, 40, 100, render=render)["unsupported"] == ["b.docx"] and cap.capture(files, recs, 40, 100, render=render)["status"] == "done")
FAKE["office"] = True
check("캡처할 파일이 없으면 none", cap.capture([("t.md", ".md", b"x")], recs, 40, 100, render=render)["status"] == "none")
TEXTS["f0.pdf"] = []                                                       # 글 층이 없는 스캔 PDF
scan = cap.capture([("s.pdf", ".pdf", b"%PDF")], [{"key": "S1", "원본형식": "PDF", "page": 3, "원본조각": "그림으로만 있는 문제"}], 40, 100, render=render)
check("글을 못 찾는 스캔 PDF 는 레코드가 아는 쪽 번호로 캡처한다", scan["map"] == {"S1": [{"file": "s.pdf", "page": 3}]}, scan)
TEXTS["f0.pdf"] = P

print("3. 저장 · 조회 · 보관 기간")
async def scenario():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine); service.set_session_factory(S)
    cap.capture.__globals__["jpeg_of"] = render if False else cap.jpeg_of
    real_capture = cap.capture
    cap_calls = []
    def patched(files, records, max_pages, dpi):
        cap_calls.append(len(files)); return real_capture(files, records, max_pages, dpi, render=render)
    service.capture_mod.capture = patched
    async with S() as db:
        for u in ("u1", "u2"): await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": u})
        db.add(IntakeJob(job_id="J1", maker_id="u1", status="processing", input_kind="원본", file_names=["a.pdf"], options={}, records_total=3))
        db.add(IntakeJob(job_id="J0", maker_id="u1", status="done", input_kind="원본", file_names=["old.pdf"], options={}, records_total=1))
        db.add(IntakeItem(job_id="J1", seq=1, out_index=0, source_key="A", status="pending", record={**recs[0], "입력종류": "원본", "원본형식": "워드"}))
        db.add(IntakeItem(job_id="J1", seq=2, out_index=0, source_key="C", status="pending", record={**recs[2], "입력종류": "원본", "원본형식": "워드"}))
        db.add(IntakeItem(job_id="J1", seq=1, out_index=1, source_key="A", status="pending", record=None, result_id="A-2"))
        db.add(IntakeCapture(job_id="J0", file_name="old.pdf", page_no=1, data=b"old", created_at=datetime.now(timezone.utc) - timedelta(days=40)))
        await db.commit()
        ids = {(i.source_key, i.out_index): i.item_id for i in (await db.execute(select(IntakeItem))).scalars().all()}
    who = {"u": "u1"}
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": who["u"]}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=30)
    out = {}
    out["before"] = (await c.get(f"/intake/items/{ids[('A', 0)]}/original")).json()
    await service.capture_job("J1", [("a.pdf", ".pdf", b"%PDF")], recs[:1] + [recs[2]])
    out["A"] = (await c.get(f"/intake/items/{ids[('A', 0)]}/original")).json()
    out["A2"] = (await c.get(f"/intake/items/{ids[('A', 1)]}/original")).json()          # 방식 분할(두 번째 결과)도 같은 원본 캡처
    out["C"] = (await c.get(f"/intake/items/{ids[('C', 0)]}/original")).json()
    who["u"] = "u2"; out["other"] = (await c.get(f"/intake/items/{ids[('A', 0)]}/original")).status_code; who["u"] = "u1"
    async with S() as db:
        out["old_left"] = len((await db.execute(select(IntakeCapture).where(IntakeCapture.job_id == "J0"))).scalars().all())
        out["new_rows"] = len((await db.execute(select(IntakeCapture).where(IntakeCapture.job_id == "J1"))).scalars().all())
        out["job"] = (await db.get(IntakeJob, "J1")).options
    os.environ["INTAKE_CAPTURE"] = "off"; await service.capture_job("J1", [("a.pdf", ".pdf", b"%PDF")], recs); os.environ.pop("INTAKE_CAPTURE")
    out["calls"] = cap_calls
    await engine.dispose()
    return out
o = asyncio.run(scenario())
check("캡처 전에는 '만드는 중'(pending) 으로 알려 준다", o["before"]["capture_status"] == "pending" and o["before"]["captures"] == [], o["before"])
a = o["A"]
check("캡처 뒤 원본 API 가 쪽 이미지(base64)를 준다", a["capture_status"] == "ready" and len(a["captures"]) == 1 and base64.b64decode(a["captures"][0]["b64"]) == b"JPG:f0.pdf:2" and a["captures"][0]["page"] == 2, a["capture_status"])
check("글(text)도 함께 와서 이미지가 없을 때의 대체로 쓸 수 있다", a["text"] and "스택" in a["text"])
check("방식 분할로 나뉜 두 번째 결과도 같은 원본 캡처를 받는다", o["A2"]["capture_status"] == "ready" and len(o["A2"]["captures"]) == 1)
check("쪽을 못 찾은 문제는 이미지 없이 'done' 작업의 none", o["C"]["captures"] == [] and o["C"]["capture_status"] in ("none", "done"), o["C"]["capture_status"])
check("다른 사용자는 볼 수 없다 (404)", o["other"] == 404)
check("보관 기간(30일)이 지난 캡처는 지워진다", o["old_left"] == 0)
check("새 캡처가 저장된다 (쪽 1개)", o["new_rows"] == 1, o["new_rows"])
check("작업에 캡처 결과 상태가 기록된다", o["job"].get("capture", {}).get("status") == "done", o["job"])
check("INTAKE_CAPTURE=off 면 캡처를 만들지 않는다", o["calls"] == [1], o["calls"])

cap.to_pdf, cap.pages_text = orig_to_pdf, orig_pages_text
print(f"결과: 통과 {ok} / 실패 {bad}")
sys.exit(1 if bad else 0)
