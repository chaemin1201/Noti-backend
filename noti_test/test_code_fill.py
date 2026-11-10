"""다시 쓰기로도 비어 있는 제공 코드·정답 코드를 서버가 채우는지 시험 (가짜 AI).
noti_test 폴더에서:  python test_code_fill.py        (httpx, aiosqlite 필요)"""
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
from app.inputdata.intake.checks import fix

passed = failed = 0
def check(name, cond, extra=""):
    global passed, failed
    if cond: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name} {str(extra)[:300]}")

NL = chr(10)
print("1. 단위")
d = "Book 클래스를 구현하세요." + NL + "class Book {" + NL + "  int price;" + NL + "public:" + NL + "  Book(int p);" + NL + "};" + NL + NL + "1) 생성자를 구현하세요."
code, rest = fix.extract_code_block(d)
check("설명에서 코드 블록(3줄 이상 이어진 코드 줄)을 떼어 낸다", code and code.startswith("class Book {") and code.endswith("};") and "class Book" not in rest and "1) 생성자를 구현하세요." in rest, (code, rest))
check("한글 문장뿐인 설명에서는 코드를 찾지 않는다", fix.extract_code_block("합을 구하시오." + NL + "두 수를 입력받아 출력하시오." + NL + "조건을 지키시오.")[0] is None)
check("코드가 2줄뿐이면(우연히 같은 줄일 수 있음) 찾지 않는다", fix.extract_code_block("설명입니다." + NL + "int a = 1;" + NL + "int b = 2;" + NL + "끝입니다")[0] is None)
check("정답 코드 응답을 읽는다 (제공 코드 포함 전체 코드)", fix.parse_code('{"reference_codes":[{"language":"cpp","code":"int main(){}"}]}', "cpp") == [{"language": "cpp", "code": "int main(){}", "is_main": True}])
check("읽을 수 없는 응답은 None", fix.parse_code("몰라요", "cpp") is None and fix.parse_code('{"reference_codes":[]}', "cpp") is None)

print("2. 업로드 흐름: AI 가 다시 써도 제공 코드·정답 코드를 비우면 서버가 채운다")
DOC = ("C++ 실습 문서" + NL + NL + "문제 CF11-0001" + NL + "책의 정보를 저장하는 Book 클래스에서 생성자를 구현하세요. cout 으로 출력합니다." + NL +
       "class Book {" + NL + "  int price;" + NL + "public:" + NL + "  Book(int p);" + NL + "  void show() { cout << price << endl; }" + NL + "};" + NL + NL + "입출력 예" + NL + "입력 없음" + NL + "출력 100")
CALLS = {"main": 0, "code": 0, "meta": 0}
def ai(user, images=None, info=None, system=None):
    if system == fix.META_SYSTEM:
        CALLS["meta"] += 1
        return json.dumps({"subtitle": "생성자 구현", "intent": "클래스 생성자 이해"}, ensure_ascii=False)
    if system == fix.CODE_SYSTEM:
        CALLS["code"] += 1
        return json.dumps({"reference_codes": [{"language": "cpp", "code": "#include <iostream>" + NL + "using namespace std;" + NL + "class Book { int price; public: Book(int p) : price(p) {} void show() { cout << price << endl; } };" + NL + "int main() { Book b(100); b.show(); }", "is_main": True}]}, ensure_ascii=False)
    CALLS["main"] += 1                                       # 큰 호출은 몇 번을 다시 시켜도 제공 코드·정답 코드를 비운다 (실제로 가끔 일어나는 일)
    p = {"problemType": "디버깅", "title": "CF11-0001", "description": "책의 정보를 저장하는 Book 클래스에서 생성자를 구현하세요. cout 으로 출력합니다.", "rating_mode": "none",
         "test_cases": [{"input": "", "expected_output": "100", "is_hidden": False}]}
    return json.dumps({"id": "CF11-0001", "payload": p, "review": {"상태": "등록가능", "보류사유": None, "입력종류": "원본", "정리": [], "복구": [], "채움": [], "조언": [], "확인필요": [], "참고": []}}, ensure_ascii=False)

async def run(path):
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
    r = await c.post("/intake/jobs", files=[("files", ("cpp_문서.txt", open(path, "rb").read(), "text/plain"))], data={"auto_register": "false"})
    if r.status_code != 202:
        await engine.dispose(); raise SystemExit(f"업로드 실패 {r.status_code}: {r.text[:200]}")
    job = r.json()["job_id"]
    for _ in range(300):
        if (await c.get(f"/intake/jobs/{job}")).json()["status"] != "processing": break
        await asyncio.sleep(0.05)
    items = (await c.get(f"/intake/jobs/{job}/items", params={"with_record": True})).json()
    await engine.dispose()
    return items

with tempfile.TemporaryDirectory() as dd:
    p = os.path.join(dd, "cpp_문서.txt"); open(p, "w", encoding="utf-8").write(DOC)
    items = asyncio.run(run(p))
    it = items[0]; pl = it["payload"] or {}
    check("제공 코드가 설명의 코드 블록에서 base_code 로 옮겨진다", it["status"] == "needs_review" and pl.get("base_code") and "class Book {" in pl["base_code"][0]["code"] and pl["base_code"][0]["language"] == "cpp", (it["status"], it["check_fails"], sorted(pl)))
    check("설명에서는 그 코드 블록이 빠진다", "class Book {" not in pl.get("description", "") and "생성자를 구현하세요" in pl.get("description", ""), pl.get("description"))
    check("정답 코드가 전용 짧은 호출로 채워지고 '손 추적' 으로 기록된다", pl.get("reference_codes") and CALLS["code"] == 1 and any(x["항목"] == "reference_codes" and x["검증"] == "손 추적" for x in it["review"]["채움"]), (CALLS, it["review"]["채움"]))
    check("큰 호출은 다시 쓰기까지 몇 번 한 뒤 멈춘다 (무한히 부르지 않음)", CALLS["main"] <= 3, CALLS)
    check("서버 검사를 통과한다 (막히지 않음)", not it["check_fails"], it["check_fails"])
    CALLS.update(main=0, code=0, meta=0)
    os.environ["INTAKE_FILL_CODE"] = "off"
    items2 = asyncio.run(run(p))
    check("INTAKE_FILL_CODE=off 이면 채우지 않고 막힌 채로 둔다", items2[0]["status"] == "blocked" and CALLS["code"] == 0, (items2[0]["status"], CALLS))
    os.environ.pop("INTAKE_FILL_CODE")

print(f"{NL}결과: 통과 {passed} / 실패 {failed}")
sys.exit(1 if failed else 0)
