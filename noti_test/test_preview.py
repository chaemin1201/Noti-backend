"""AI 를 부르기 전 파싱 미리보기 (AI 호출 없음): 문제 수·경계·경고를 보여 주고, 작업을 만들지 않으며 AI 를 부르지 않는지.
noti_test 폴더에서:  python test_preview.py"""
import asyncio, os, sys, tempfile
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
from app.inputdata.intake import router as intake_router, service, parsing

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {extra}")

LONG = "다음 설명을 읽고 프로그램을 작성하시오. 입력과 출력 예를 참고하여 조건에 맞게 작성합니다. " * 3
TXT3 = f"문제 PY11-0001\n{LONG}\n\n문제 PY11-0002\n{LONG}\n\n문제 PY11-0003\n짧음\n"
TXT_DUP = f"문제 PY11-0001\n{LONG}\n\n문제 PY11-0001\n{LONG}\n"
CSV = "이름,설명\n문제 A-1,첫째 문제 설명입니다. 합을 출력하시오.\n문제 A-2,둘째 문제 설명입니다. 곱을 출력하시오.\n"

def build(files, **kw):
    with tempfile.TemporaryDirectory() as d:
        tables, originals, labels = [], [], []
        for name, body in files:
            p = os.path.join(d, name); open(p, "w", encoding="utf-8").write(body)
            (tables if parsing.kind_of(name) == "table" else originals).append(p); labels.append(name)
        kind, recs = parsing.build_records(tables, originals, kw.get("pattern"), [n for n, _ in files if parsing.kind_of(n) == "original"],
                                           table_labels=[n for n, _ in files if parsing.kind_of(n) == "table"])
        return parsing.preview_of(kind, recs)

print("1. 문서를 문제로 나눈 결과")
pv = build([("a.txt", TXT3)])
check("문제 3개로 나뉘고 종류는 원본", pv["records_total"] == 3 and pv["input_kind"] == "원본", (pv["records_total"], pv["input_kind"]))
check("각 문제의 이름·글자 수·첫 줄이 나온다", [p["key"] for p in pv["problems"]] == ["PY11-0001", "PY11-0002", "PY11-0003"] and all(p["chars"] > 0 and p["head"] for p in pv["problems"]))
check("본문이 짧은 문제(경계 의심)에 경고가 붙고 정상 문제에는 없다", pv["problems"][2]["warnings"] and not pv["problems"][0]["warnings"] and pv["problems_with_warnings"] == 1, pv["problems"][2]["warnings"])
check("문서에서 같은 문제 ID 가 반복되면(쪽마다 되풀이되는 제목) 문제 하나로 합치고 가장 긴 구간만 남긴다", build([("d.txt", TXT_DUP)])["records_total"] == 1)
dupcsv = build([("u.csv", CSV.replace("A-2", "A-1"))])
check("엑셀에서 같은 이름이 두 번 나오면 두 행 모두에 경고", dupcsv["records_total"] == 2 and all(p["warnings"] for p in dupcsv["problems"]), [p["warnings"] for p in dupcsv["problems"]])

print("2. 표 입력")
pt = build([("t.csv", CSV)])
check("CSV 두 행이 엑셀 입력 2개가 된다", pt["records_total"] == 2 and pt["by_kind"] == {"엑셀": 2}, pt["by_kind"])
check("표 입력은 본문이 짧다는 경고를 내지 않는다", pt["warnings_total"] == 0, [p["warnings"] for p in pt["problems"]])
check("빈 항목을 AI 가 채울 문제 수를 센다 (정답코드·유형 없음)", pt["needs_filling"] == 2, pt["needs_filling"])

print("3. 한도")
os.environ["INTAKE_MAX_PROBLEMS"] = "2"
try: check("문제 수가 한도를 넘으면 over_limit", build([("a.txt", TXT3)])["over_limit"] is True)
finally: os.environ.pop("INTAKE_MAX_PROBLEMS", None)
check("글 요약에 경고가 표시된다", "⚠" in parsing.format_text(pv) and "PY11-0003" in parsing.format_text(pv))

print("4. API: 작업을 만들지 않고 AI 도 부르지 않는다")
async def api():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    S = async_sessionmaker(engine)
    async with S() as db:
        await db.execute(text('INSERT INTO "user" (user_id) VALUES (:u)'), {"u": "u1"}); await db.commit()
    service.set_session_factory(S)
    called = []
    def boom(): called.append(1); raise AssertionError("미리보기에서 AI 를 부르면 안 됩니다")
    service._default_ai = boom
    app = FastAPI(); app.include_router(intake_router.router)
    async def _db():
        async with S() as db: yield db
    app.dependency_overrides[get_db] = _db; app.dependency_overrides[get_current_user] = lambda: {"sub": "u1"}
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60)
    r = await c.post("/intake/preview", files=[("files", ("a.txt", TXT3.encode("utf-8"), "text/plain"))])
    check("200 으로 문제 3개 요약을 돌려준다", r.status_code == 200 and r.json()["records_total"] == 3, r.text[:200])
    check("작업이 만들어지지 않는다", (await c.get("/intake/jobs")).json() == [])
    check("AI 설정을 읽지도 않는다", not called)
    r = await c.post("/intake/preview", files=[("files", ("x.exe", b"abc", "application/octet-stream"))])
    check("지원하지 않는 형식은 400", r.status_code == 400, r.status_code)
    r = await c.post("/intake/preview", files=[("files", ("n.txt", "그냥 평범한 글입니다.".encode("utf-8"), "text/plain"))])
    check("문제를 찾지 못하면 422 와 안내", r.status_code == 422 and "문제를 찾지" in r.text, (r.status_code, r.text[:120]))
    await engine.dispose()
asyncio.run(api())

print(f"\n결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
